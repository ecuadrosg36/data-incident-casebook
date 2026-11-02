"""Incident 03: revenue in the dashboard is higher than in finance's ledger.

Story (all data generated): order events arrive in daily batches. The event stream switches to
at-least-once delivery, so some events arrive two or three times. The load appends each batch as is, and an
operator re-runs one day after a timeout. Both inflate revenue.
"""

import duckdb

from casebook.case import CaseFile, Evidence, Incident, Metric, pct, verdict
from casebook.checks import duplicate_share, is_idempotent

DAYS = 10
ORDERS_PER_DAY = 5_000
AT_LEAST_ONCE_FROM_DAY = 6
RETRY_PERCENT = 8
RERUN_DAY = "2026-05-08"

SETUP_SQL = f"""
CREATE OR REPLACE TABLE ledger AS  -- finance's truth: one row per order
SELECT 'evt-' || range AS event_id,
       DATE '2026-05-01' + CAST(range // {ORDERS_PER_DAY} AS INTEGER) AS order_date,
       round(10 + hash(range, 'amount') % 9000 / 100.0, 2) AS amount
FROM range({DAYS * ORDERS_PER_DAY});

-- What lands from the stream: from day {AT_LEAST_ONCE_FROM_DAY}, some events are delivered more than once.
CREATE OR REPLACE TABLE landing_events AS
SELECT l.*, l.order_date AS batch_date,
       CAST(l.order_date AS TIMESTAMP) + INTERVAL (copy * 7) MINUTE AS ingested_at
FROM ledger l, range(3) c(copy)
WHERE copy = 0
   OR (day(l.order_date) >= {AT_LEAST_ONCE_FROM_DAY} AND copy = 1
       AND hash(l.event_id, 'retry') % 100 < {RETRY_PERCENT})
   OR (day(l.order_date) >= {AT_LEAST_ONCE_FROM_DAY} AND copy = 2 AND hash(l.event_id, 'retry') % 100 < 1);
"""

APPEND_TABLE = "CREATE OR REPLACE TABLE fct_orders (event_id VARCHAR, order_date DATE, amount DOUBLE)"
APPEND_LOAD = """
INSERT INTO fct_orders SELECT event_id, order_date, amount FROM landing_events WHERE batch_date = ?
"""

# The fix: one row per event inside the batch, then an upsert on the primary key.
SAFE_TABLE = "CREATE OR REPLACE TABLE fct_orders (event_id VARCHAR PRIMARY KEY, order_date DATE, amount DOUBLE)"
SAFE_LOAD = """
INSERT OR REPLACE INTO fct_orders
SELECT event_id, order_date, amount FROM landing_events WHERE batch_date = ?
QUALIFY row_number() OVER (PARTITION BY event_id ORDER BY ingested_at DESC) = 1
"""


def _load_all(con: duckdb.DuckDBPyConnection, table_sql: str, load_sql: str) -> None:
    con.execute(table_sql)
    for (day,) in con.execute("SELECT DISTINCT batch_date FROM landing_events ORDER BY 1").fetchall():
        con.execute(load_sql, [day])


def _revenue_gap(con: duckdb.DuckDBPyConnection) -> float:
    dashboard, ledger = con.execute(
        "SELECT (SELECT sum(amount) FROM fct_orders), (SELECT sum(amount) FROM ledger)"
    ).fetchone()
    return dashboard / ledger - 1


def _rerun_is_safe(con: duckdb.DuckDBPyConnection, load_sql: str) -> bool:
    return is_idempotent(
        load=lambda: con.execute(load_sql, [RERUN_DAY]),
        measure=lambda: con.execute("SELECT round(sum(amount), 2) FROM fct_orders").fetchone()[0],
    )


def _evidence(con: duckdb.DuckDBPyConnection) -> tuple[Evidence, ...]:
    avg_before, avg_after = con.execute(
        f"""
        SELECT avg(amount) FILTER (WHERE day(order_date) < {AT_LEAST_ONCE_FROM_DAY}),
               avg(amount) FILTER (WHERE day(order_date) >= {AT_LEAST_ONCE_FROM_DAY})
        FROM (SELECT DISTINCT event_id, order_date, amount FROM fct_orders)
        """
    ).fetchone()
    orders_per_day = {
        n for (n,) in con.execute("SELECT count(DISTINCT event_id) FROM fct_orders GROUP BY order_date").fetchall()
    }
    dup_early = duplicate_share(
        con, f"(SELECT * FROM fct_orders WHERE day(order_date) < {AT_LEAST_ONCE_FROM_DAY})", "event_id"
    )
    dup_late = duplicate_share(
        con, f"(SELECT * FROM fct_orders WHERE day(order_date) >= {AT_LEAST_ONCE_FROM_DAY})", "event_id"
    )
    append_rerun_safe = _rerun_is_safe(con, APPEND_LOAD)  # runs last: it loads the day again
    return (
        Evidence(
            "Prices went up",
            "Average amount per distinct order, before vs after the jump",
            f"{avg_before:,.2f} vs {avg_after:,.2f}",
            verdict(abs(avg_after / avg_before - 1) > 0.05),
        ),
        Evidence(
            "There were more orders",
            "Distinct order events per day",
            f"{', '.join(f'{n:,}' for n in sorted(orders_per_day))} per day",
            verdict(len(orders_per_day) > 1),
        ),
        Evidence(
            "The same event is stored more than once",
            "Extra copies of an event_id in fct_orders",
            f"{pct(dup_early)} of rows before day {AT_LEAST_ONCE_FROM_DAY}, {pct(dup_late)} after",
            verdict(dup_late > dup_early),
        ),
        Evidence(
            "Re-running a day adds it again",
            f"Load {RERUN_DAY} twice and compare revenue",
            "no change" if append_rerun_safe else "revenue changes on every re-run",
            verdict(not append_rerun_safe),
        ),
    )


def investigate(con: duckdb.DuckDBPyConnection) -> CaseFile:
    con.execute(SETUP_SQL)
    _load_all(con, APPEND_TABLE, APPEND_LOAD)
    con.execute(APPEND_LOAD, [RERUN_DAY])  # the operator's re-run after a timeout
    gap_before = _revenue_gap(con)
    dup_rows_before = con.execute("SELECT count(*) - count(DISTINCT event_id) FROM fct_orders").fetchone()[0]
    evidence = _evidence(con)

    _load_all(con, SAFE_TABLE, SAFE_LOAD)
    con.execute(SAFE_LOAD, [RERUN_DAY])
    gap_after = _revenue_gap(con)
    dup_rows_after = con.execute("SELECT count(*) - count(DISTINCT event_id) FROM fct_orders").fetchone()[0]
    rerun_safe = _rerun_is_safe(con, SAFE_LOAD)

    return CaseFile(
        number=3,
        slug="duplicate-events",
        title="Dashboard revenue is higher than the ledger",
        symptom=(
            f"Revenue in the dashboard is {pct(gap_before)} above finance's ledger for the same period, and the "
            f"gap only started on day {AT_LEAST_ONCE_FROM_DAY}."
        ),
        evidence=evidence,
        root_cause=(
            f"From day {AT_LEAST_ONCE_FROM_DAY} the event stream delivers at least once, so about "
            f"{RETRY_PERCENT}% of events arrive more than once. The load appends every batch as received, "
            f"and appending is not safe to repeat: the re-run of {RERUN_DAY} added the whole day again."
        ),
        fix=(
            "Give `fct_orders` a primary key on `event_id`. Each batch keeps one row per event (the latest "
            "`ingested_at`) and is upserted with `INSERT OR REPLACE`. Dedupe comes first: given the same key twice "
            "in one batch, the upsert silently keeps whichever copy it meets first, not the latest one."
        ),
        guard=(
            "Two tests run in CI: `duplicate_share(fct_orders, event_id) == 0`, and `is_idempotent()` loads the "
            "same day twice and requires identical revenue."
        ),
        metrics=(
            Metric("Dashboard revenue vs ledger", f"+{pct(gap_before)}", pct(gap_after)),
            Metric("Duplicate rows in fct_orders", f"{dup_rows_before:,}", f"{dup_rows_after:,}"),
            Metric("Safe to re-run a day", "no", "yes" if rerun_safe else "no"),
        ),
    )


INCIDENT = Incident(3, "duplicate-events", "Dashboard revenue is higher than the ledger", investigate)
