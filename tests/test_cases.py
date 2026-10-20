"""Integration assertions against artifacts produced by make verify."""
import json
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def con():
    with duckdb.connect(str(ROOT / 'casebook.duckdb'), read_only=True) as connection:
        yield connection


def test_latest_and_tie_break(con):
    assert con.sql('select count(*) from case1_fixed').fetchone()[0] == 100
    assert con.sql('select amount from case1_fixed where event_id=1').fetchone()[0] == 999
    assert con.sql('select amount from case1_fixed where event_id=2').fetchone()[0] == 12
    # Rank result does not depend on physical input order.
    assert con.sql('''select amount from (select * from events order by delivery_sequence desc)
        qualify row_number() over(partition by event_id order by source_updated_at desc,
        ingested_at desc, delivery_sequence desc)=1 order by event_id limit 1''').fetchone()[0] == 999


def test_composite_identity_preserves_tenant(con):
    assert con.sql('select count(*) from case2_fixed').fetchone()[0] == 100
    assert con.sql("select count(*) from case2_fixed where tenant='a'").fetchone()[0] == 50
    assert con.sql('select count(*) from identity_map').fetchone()[0] == 20


def test_freshness_evidence(con):
    assert str(con.sql("select max(write_date) from write_history where table_name='legacy'").fetchone()[0]) == '2024-01-01'
    assert con.sql('select error_rate from case3_fixed').fetchone()[0] == pytest.approx(.01)


@pytest.mark.parametrize('case', sorted((ROOT / 'cases').iterdir()))
def test_committed_evidence_matches_database(case, con):
    result=json.loads((case/'results.json').read_text())
    n=int(case.name[:2]); query=(case/'regression.sql').read_text()
    for suffix, key in [('bug','regression_violations_before'),('fixed','regression_violations_after')]:
        assert len(con.execute(query.format(table=f'case{n}_{suffix}')).fetchall()) == result[key]
    assert result['synthetic'] is True
