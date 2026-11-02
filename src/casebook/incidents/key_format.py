"""Incident 02: customer match rate collapses after a CRM upgrade.

Story (all data generated): billing and CRM share a customer key like 'PE-000123'. After a CRM upgrade,
every contact the CRM touches is exported as 'pe_123' instead. Nothing errors; the join just stops matching.
"""

import duckdb

from casebook.case import CaseFile, Evidence, Incident, Metric, pct, verdict
from casebook.checks import key_shapes, match_rate

CUSTOMERS = 40_000
NEW_CONTACTS = 900
HISTORY_DAYS = 60
UPGRADE_DAY = 35  # days after 2026-03-01 when the CRM upgrade goes live
EXPECTED_SHAPE = r"^[A-Z]{2}-[0-9]{6}$"

SETUP_SQL = f"""
CREATE OR REPLACE TABLE billing_customers AS
SELECT ['PE', 'CO', 'MX'][1 + range % 3] || '-' || lpad(CAST(range + 1 AS VARCHAR), 6, '0') AS customer_key,
       range + 1 AS customer_number
FROM range({CUSTOMERS});

-- Existing customers plus some genuinely new contacts. Rows updated after the upgrade use the new key format.
CREATE OR REPLACE TABLE crm_contacts AS
WITH contacts AS (
    SELECT range + 1 AS n, ['PE', 'CO', 'MX'][1 + range % 3] AS country,
           DATE '2026-03-01' + CAST(hash(range, 'updated') % {HISTORY_DAYS} AS INTEGER) AS updated_on
    FROM range({CUSTOMERS + NEW_CONTACTS})
)
SELECT CASE WHEN updated_on >= DATE '2026-03-01' + {UPGRADE_DAY}
            THEN lower(country) || '_' || CAST(n AS VARCHAR)
            ELSE country || '-' || lpad(CAST(n AS VARCHAR), 6, '0') END AS crm_key,
       updated_on
FROM contacts;

-- The fix: one key format, applied to every source in staging.
CREATE OR REPLACE MACRO normalize_key(k) AS
    upper(regexp_extract(k, '^([A-Za-z]{{2}})', 1)) || '-' || lpad(regexp_extract(k, '([0-9]+)$', 1), 6, '0');
"""

UPGRADE_DATE = f"DATE '2026-03-01' + {UPGRADE_DAY}"


def _top_shapes(con: duckdb.DuckDBPyConnection, where: str) -> str:
    shapes = key_shapes(con, f"(SELECT crm_key FROM crm_contacts WHERE {where})", "crm_key")
    return ", ".join(f"`{shape}`" for shape in list(shapes)[:3])


def _evidence(con: duckdb.DuckDBPyConnection, rate_before_upgrade: float) -> tuple[Evidence, ...]:
    bad_billing = con.execute(
        f"SELECT count(*) FROM billing_customers WHERE NOT regexp_matches(customer_key, '{EXPECTED_SHAPE}')"
    ).fetchone()[0]
    unmatched, with_twin = con.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE b2.customer_key IS NOT NULL)
        FROM crm_contacts c
        LEFT JOIN billing_customers b ON c.crm_key = b.customer_key
        LEFT JOIN billing_customers b2 ON normalize_key(c.crm_key) = b2.customer_key
        WHERE b.customer_key IS NULL
        """
    ).fetchone()
    shapes_before = _top_shapes(con, f"updated_on < {UPGRADE_DATE}")
    shapes_after = _top_shapes(con, f"updated_on >= {UPGRADE_DATE}")
    return (
        Evidence(
            "Billing keys changed",
            "Billing keys that break the `AA-999999` shape",
            f"{bad_billing:,} of {CUSTOMERS:,}",
            verdict(bad_billing > 0),
        ),
        Evidence(
            "The unmatched contacts are new customers",
            "Unmatched CRM keys with a billing twin once normalized",
            f"{with_twin:,} of {unmatched:,} ({pct(with_twin / unmatched)}) already exist in billing",
            verdict(with_twin < unmatched / 2),
        ),
        Evidence(
            "The CRM changed its key format",
            "Key shapes in CRM, before vs after the upgrade date",
            f"before: {shapes_before} · after: {shapes_after}; match rate before upgrade {pct(rate_before_upgrade)}",
            verdict(shapes_before != shapes_after),
        ),
    )


def investigate(con: duckdb.DuckDBPyConnection) -> CaseFile:
    con.execute(SETUP_SQL)
    rate_before_upgrade = match_rate(
        con,
        f"(SELECT * FROM crm_contacts WHERE updated_on < {UPGRADE_DATE})",
        "billing_customers",
        "crm_key",
        "customer_key",
    )
    rate_before = match_rate(con, "crm_contacts", "billing_customers", "crm_key", "customer_key")
    unmatched_before = con.execute(
        "SELECT count(*) FROM crm_contacts ANTI JOIN billing_customers ON crm_key = customer_key"
    ).fetchone()[0]
    evidence = _evidence(con, rate_before_upgrade)

    con.execute("CREATE OR REPLACE VIEW stg_crm AS SELECT normalize_key(crm_key) AS customer_key FROM crm_contacts")
    rate_after = match_rate(con, "stg_crm", "billing_customers", "customer_key", "customer_key")
    unmatched_after = con.execute(
        "SELECT count(*) FROM stg_crm ANTI JOIN billing_customers USING (customer_key)"
    ).fetchone()[0]
    recovered = (unmatched_before - unmatched_after) / unmatched_before
    off_contract = con.execute(
        f"SELECT count(*) FROM stg_crm WHERE NOT regexp_matches(customer_key, '{EXPECTED_SHAPE}')"
    ).fetchone()[0]

    return CaseFile(
        number=2,
        slug="key-format-change",
        title="Customer match rate fell after a CRM upgrade",
        symptom=(
            f"The share of CRM contacts linked to a billing customer fell from {pct(rate_before_upgrade)} to "
            f"{pct(rate_before)}. Revenue per customer and churn reports started to look wrong."
        ),
        evidence=evidence,
        root_cause=(
            "After the upgrade the CRM exports keys as `pe_123` instead of `PE-000123`: lower case, "
            "underscore, no zero padding. Only contacts touched after the upgrade changed, so the drop "
            "grew day by day instead of appearing all at once."
        ),
        fix=(
            "A `normalize_key()` macro (upper-case country, dash, 6-digit zero-padded number) applied in staging "
            "to every source, so both sides are compared in one format."
        ),
        guard=(
            f"A contract check fails the build if any staged key breaks the shape `{EXPECTED_SHAPE}`, and the "
            "match rate is tracked daily so a slow slide is visible."
        ),
        metrics=(
            Metric("CRM contacts matched to billing", pct(rate_before), pct(rate_after)),
            Metric("Unmatched contacts", f"{unmatched_before:,}", f"{unmatched_after:,}"),
            Metric("Previously unmatched contacts recovered", "–", pct(recovered)),
            Metric("Staged keys breaking the format contract", "not checked", f"{off_contract:,}"),
        ),
    )


INCIDENT = Incident(2, "key-format-change", "Customer match rate fell after a CRM upgrade", investigate)
