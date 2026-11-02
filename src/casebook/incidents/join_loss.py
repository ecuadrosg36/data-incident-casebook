"""Incident 01: the daily impressions report drops most of its volume overnight.

Story (all data generated): an ad platform logs impressions. A reporting model joins them to a campaign
dimension that is refreshed once a week. A seasonal launch sends most traffic to new campaigns that the
dimension does not know yet, and an INNER JOIN drops those rows without any error.
"""

from collections.abc import Collection

import duckdb

from casebook.case import CaseFile, Evidence, Incident, Metric, pct, verdict
from casebook.checks import LayerLoss, failed_partitions, reconcile

DAYS = 14
IMPRESSIONS_PER_DAY = 20_000
OLD_CAMPAIGNS = 40
NEW_CAMPAIGNS = 8
LAUNCH_DAY = 12  # day of the month the new campaigns go live
NEW_TRAFFIC_PERCENT = 70
DIMENSION_SNAPSHOT = "2026-03-08"

SETUP_SQL = f"""
CREATE OR REPLACE TABLE raw_impressions AS
SELECT i AS impression_id,
       TIMESTAMP '2026-03-01' + INTERVAL (i // {IMPRESSIONS_PER_DAY}) DAY
                              + INTERVAL (hash(i, 'second') % 86400) SECOND AS served_at,
       CASE WHEN i // {IMPRESSIONS_PER_DAY} + 1 >= {LAUNCH_DAY} AND hash(i, 'mix') % 100 < {NEW_TRAFFIC_PERCENT}
            THEN {OLD_CAMPAIGNS} + 1 + hash(i, 'new') % {NEW_CAMPAIGNS}
            ELSE 1 + hash(i, 'old') % {OLD_CAMPAIGNS} END AS campaign_id
FROM range({DAYS * IMPRESSIONS_PER_DAY}) t(i);

-- Weekly snapshot taken before the launch, so it only has the old campaigns.
CREATE OR REPLACE TABLE dim_campaigns AS
SELECT range + 1 AS campaign_id, 'Advertiser ' || ((range % 6) + 1) AS advertiser,
       DATE '{DIMENSION_SNAPSHOT}' AS snapshot_date
FROM range({OLD_CAMPAIGNS});

CREATE OR REPLACE VIEW stg_impressions AS
SELECT impression_id, CAST(served_at AS DATE) AS day, campaign_id FROM raw_impressions;
"""

REPORT_BEFORE = """
CREATE OR REPLACE TABLE rpt_daily AS
SELECT s.day, c.advertiser, count(*) AS impressions
FROM stg_impressions s
JOIN dim_campaigns c USING (campaign_id)
GROUP BY ALL
"""

REPORT_AFTER = """
CREATE OR REPLACE TABLE rpt_daily AS
SELECT s.day, coalesce(c.advertiser, 'Unknown (not in dimension yet)') AS advertiser, count(*) AS impressions
FROM stg_impressions s
LEFT JOIN dim_campaigns c USING (campaign_id)
GROUP BY ALL
"""


def _losses(con: duckdb.DuckDBPyConnection) -> list[LayerLoss]:
    """Rows in staging vs impressions counted in the report, per day."""
    return reconcile(con, "stg_impressions", "rpt_daily", by="day", downstream_measure="sum(impressions)")


def _daily(con: duckdb.DuckDBPyConnection, sql: str) -> dict[str, int]:
    return {str(day): int(n) for day, n in con.execute(sql).fetchall()}


def _span(values: Collection[int]) -> str:
    low, high = min(values), max(values)
    return f"{low:,}" if low == high else f"{low:,}–{high:,}"


def _evidence(con: duckdb.DuckDBPyConnection) -> tuple[Evidence, ...]:
    raw = _daily(con, "SELECT CAST(served_at AS DATE), count(*) FROM raw_impressions GROUP BY 1")
    staging_losses = failed_partitions(
        reconcile(con, "(SELECT CAST(served_at AS DATE) AS day FROM raw_impressions)", "stg_impressions", by="day")
    )
    report_losses = failed_partitions(_losses(con))
    lost_rows = sum(loss.lost for loss in report_losses)
    orphans, orphan_rows, first_seen = con.execute(
        "SELECT count(DISTINCT campaign_id), count(*), min(day) "
        "FROM stg_impressions ANTI JOIN dim_campaigns USING (campaign_id)"
    ).fetchone()
    return (
        Evidence(
            "The source sent less data",
            "Raw impressions per day",
            f"{_span(raw.values())} every day, no drop",
            verdict(max(raw.values()) != min(raw.values())),
        ),
        Evidence(
            "Staging filtered rows out",
            "Reconcile raw vs staging per day",
            f"{len(staging_losses)} days with a gap",
            verdict(bool(staging_losses)),
        ),
        Evidence(
            "The report step loses rows",
            "Reconcile staging rows vs report impressions per day",
            f"{len(report_losses)} days lose rows, {lost_rows:,} rows in total",
            verdict(bool(report_losses)),
        ),
        Evidence(
            "Lost rows belong to campaigns missing from the dimension",
            "Anti-join staging to dim_campaigns",
            f"{orphans} campaign IDs, {orphan_rows:,} rows, first seen {first_seen}; "
            f"dimension snapshot {DIMENSION_SNAPSHOT}",
            verdict(orphan_rows == lost_rows),
        ),
    )


def investigate(con: duckdb.DuckDBPyConnection) -> CaseFile:
    con.execute(SETUP_SQL)
    con.execute(REPORT_BEFORE)
    report = _daily(con, "SELECT day, sum(impressions) FROM rpt_daily GROUP BY 1")
    normal = sum(n for day, n in report.items() if int(day[-2:]) < LAUNCH_DAY) / (LAUNCH_DAY - 1)
    worst_day = min(report, key=report.get)
    days_failing_before = len(failed_partitions(_losses(con)))
    evidence = _evidence(con)

    con.execute(REPORT_AFTER)
    after = _daily(con, "SELECT day, sum(impressions) FROM rpt_daily GROUP BY 1")
    unknown = con.execute(
        "SELECT sum(impressions) FILTER (WHERE advertiser LIKE 'Unknown%') / sum(impressions) "
        "FROM rpt_daily WHERE day = ?",
        [worst_day],
    ).fetchone()[0]
    days_failing_after = len(failed_partitions(_losses(con)))

    return CaseFile(
        number=1,
        slug="silent-join-loss",
        title="Daily impressions dropped overnight",
        symptom=(
            f"On {worst_day} the impressions report showed {report[worst_day]:,}, "
            f"down {pct(1 - report[worst_day] / normal)} from a "
            f"normal day ({normal:,.0f}). No job failed and no alert fired."
        ),
        evidence=evidence,
        root_cause=(
            "The report joins impressions to `dim_campaigns` with an INNER JOIN. The dimension is a weekly "
            f"snapshot (last one {DIMENSION_SNAPSHOT}). Campaigns launched on day {LAUNCH_DAY} were not in it yet, "
            "so every impression for them was dropped silently."
        ),
        fix=(
            "Use a LEFT JOIN and label rows with no campaign as `Unknown (not in dimension yet)`. Totals stay "
            "right, and the unknown share shows how stale the dimension is."
        ),
        guard=(
            "`reconcile(stg_impressions, rpt_daily)` runs after every build and fails it if any day loses rows. "
            "A model that drops data now breaks loudly instead of quietly."
        ),
        metrics=(
            Metric(f"Impressions in report on {worst_day}", f"{report[worst_day]:,}", f"{after[worst_day]:,}"),
            Metric("Days where report ≠ staging", str(days_failing_before), str(days_failing_after)),
            Metric(f"Share labelled Unknown on {worst_day}", "hidden", pct(unknown)),
        ),
    )


INCIDENT = Incident(1, "silent-join-loss", "Daily impressions dropped overnight", investigate)
