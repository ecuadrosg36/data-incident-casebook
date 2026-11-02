from collections.abc import Iterator

import duckdb
import pytest

from casebook.checks import (
    LayerLoss,
    duplicate_share,
    failed_partitions,
    is_idempotent,
    key_shapes,
    match_rate,
    reconcile,
)


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE up AS SELECT * FROM (VALUES (1, 'a'), (1, 'b'), (2, 'c'), (3, 'd')) t(day, k);
            CREATE TABLE down AS SELECT * FROM (VALUES (1, 2), (2, 0), (4, 5)) t(day, n);
            """
        )
        yield connection


def test_reconcile_finds_lost_and_invented_rows(con: duckdb.DuckDBPyConnection) -> None:
    losses = reconcile(con, "up", "down", by="day", downstream_measure="sum(n)")

    assert [(x.partition, x.rows_in, x.rows_out) for x in losses] == [
        ("1", 2, 2),
        ("2", 1, 0),
        ("3", 1, 0),
        ("4", 0, 5),
    ]
    assert [x.partition for x in failed_partitions(losses)] == ["2", "3", "4"]


def test_failed_partitions_respects_tolerance() -> None:
    losses = [LayerLoss("a", 100, 99), LayerLoss("b", 100, 90), LayerLoss("c", 0, 0)]

    assert [x.partition for x in failed_partitions(losses, tolerance=0.05)] == ["b"]
    assert losses[1].lost == 10
    assert losses[2].lost_share == 0.0


def test_match_rate_counts_distinct_keys(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE r AS SELECT * FROM (VALUES ('a'), ('c'), ('z')) t(k)")

    assert match_rate(con, "up", "r", "k", "k") == pytest.approx(0.5)
    assert match_rate(con, "(SELECT * FROM up WHERE false)", "r", "k", "k") == 0.0


def test_key_shapes_turn_letters_and_digits_into_patterns(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE keys AS SELECT * FROM (VALUES ('PE-000123'), ('MX-000001'), ('pe_12')) t(k)")

    assert key_shapes(con, "keys", "k") == {"AA-999999": 2, "AA_99": 1}


def test_duplicate_share(con: duckdb.DuckDBPyConnection) -> None:
    assert duplicate_share(con, "up", "day") == pytest.approx(0.25)
    assert duplicate_share(con, "(SELECT * FROM up WHERE false)", "day") == 0.0


def test_is_idempotent() -> None:
    store: list[int] = []

    assert is_idempotent(load=lambda: store.append(1), measure=lambda: len(store)) is False
    assert is_idempotent(load=lambda: None, measure=lambda: 42) is True


def test_rows_out_of_nowhere_count_as_invented() -> None:
    assert LayerLoss("x", 0, 5).lost_share == -1.0
