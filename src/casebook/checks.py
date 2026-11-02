"""Reusable data checks. Each incident uses them to investigate, and each fix keeps one running as a guard.

They take SQL relations (a table name or a subquery in parentheses) that the caller controls.
"""

from collections.abc import Callable
from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class LayerLoss:
    partition: str
    rows_in: int
    rows_out: int

    @property
    def lost(self) -> int:
        return self.rows_in - self.rows_out

    @property
    def lost_share(self) -> float:
        """Negative when rows appear downstream. Rows out of nowhere count as -100%."""
        if self.rows_in == 0:
            return -1.0 if self.rows_out else 0.0
        return self.lost / self.rows_in


def reconcile(
    con: duckdb.DuckDBPyConnection,
    upstream: str,
    downstream: str,
    by: str,
    measure: str = "count(*)",
    downstream_measure: str | None = None,
) -> list[LayerLoss]:
    """Compare a measure between two layers, partition by partition. Gaps mean a step lost or invented data.

    Use downstream_measure when the lower layer is aggregated, e.g. count(*) upstream vs sum(n) downstream.
    """
    rows = con.execute(
        f"""
        SELECT CAST(p AS VARCHAR), coalesce(u.m, 0), coalesce(d.m, 0)
        FROM (SELECT {by} AS p, {measure} AS m FROM {upstream} GROUP BY 1) u
        FULL OUTER JOIN (SELECT {by} AS p, {downstream_measure or measure} AS m FROM {downstream} GROUP BY 1) d
        USING (p)
        ORDER BY 1
        """
    ).fetchall()
    return [LayerLoss(p, int(rows_in), int(rows_out)) for p, rows_in, rows_out in rows]


def failed_partitions(losses: list[LayerLoss], tolerance: float = 0.0) -> list[LayerLoss]:
    """Partitions where the downstream layer lost (or gained) more than the tolerance."""
    return [loss for loss in losses if abs(loss.lost_share) > tolerance]


def match_rate(con: duckdb.DuckDBPyConnection, left: str, right: str, left_key: str, right_key: str) -> float:
    """Share of distinct left keys that find a partner on the right."""
    matched, total = con.execute(
        f"""
        SELECT count(*) FILTER (WHERE r.k IS NOT NULL), count(*)
        FROM (SELECT DISTINCT {left_key} AS k FROM {left}) l
        LEFT JOIN (SELECT DISTINCT {right_key} AS k FROM {right}) r USING (k)
        """
    ).fetchone()
    return matched / total if total else 0.0


def key_shapes(con: duckdb.DuckDBPyConnection, relation: str, column: str) -> dict[str, int]:
    """Profile a key column by shape: letters become A and digits become 9, so 'PE-00123' is 'AA-99999'."""
    rows = con.execute(
        f"""
        SELECT regexp_replace(regexp_replace({column}, '[A-Za-z]', 'A', 'g'), '[0-9]', '9', 'g') AS shape,
               count(*) AS n
        FROM {relation} GROUP BY shape ORDER BY n DESC
        """
    ).fetchall()
    return {shape: int(n) for shape, n in rows}


def duplicate_share(con: duckdb.DuckDBPyConnection, relation: str, key: str) -> float:
    """Share of rows that are extra copies of a key already seen."""
    rows, distinct = con.execute(f"SELECT count(*), count(DISTINCT {key}) FROM {relation}").fetchone()
    return (rows - distinct) / rows if rows else 0.0


def is_idempotent(load: Callable[[], None], measure: Callable[[], float], runs: int = 2) -> bool:
    """Run a load several times; a safe load gives the same result every time."""
    results = []
    for _ in range(runs):
        load()
        results.append(measure())
    return len(set(results)) == 1
