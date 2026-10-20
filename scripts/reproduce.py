"""Execute synthetic fixtures, dbt transformations, and negative/positive controls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CASES = sorted((ROOT / 'cases').iterdir())


def dbt(*args):
    subprocess.run(['dbt', *args, '--profiles-dir', str(ROOT)], cwd=ROOT, check=True)


def reproduce(selection='all'):
    selected = CASES if selection == 'all' else [CASES[int(selection.split('-')[1]) - 1]]
    for case in CASES:
        spec = importlib.util.spec_from_file_location('generator', case / 'generate.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.generate(ROOT)
    events = ROOT / 'seeds/events.csv'
    full_events = events.read_text()
    # Initial load contains only original deliveries. Resends arrive in batch two.
    events.write_text('\n'.join(full_events.splitlines()[:101]) + '\n')
    try:
        dbt('seed', '--full-refresh')
        dbt('build', '--full-refresh')
    finally:
        events.write_text(full_events)
    dbt('seed', '--full-refresh')
    dbt('run', '--select', 'case1_bug', 'case1_fixed')
    dbt('test')
    results = {}
    with duckdb.connect(str(ROOT / 'casebook.duckdb')) as con:
        for case in selected:
            n = int(case.name[:2])
            check = (case / 'regression.sql').read_text()
            before = len(con.execute(check.format(table=f'case{n}_bug')).fetchall())
            after = len(con.execute(check.format(table=f'case{n}_fixed')).fetchall())
            assert before > 0 and after == 0, (case.name, before, after)
            investigation = con.execute((case / 'investigation.sql').read_text())
            columns = [c[0] for c in investigation.description]
            evidence = [dict(zip(columns, row)) for row in investigation.fetchall()]
            result = {'synthetic': True, 'case': case.name, 'regression_violations_before': before,
                      'regression_violations_after': after, 'investigation': evidence}
            if n == 1:
                result.update(input_deliveries=con.sql('select count(*) from events').fetchone()[0],
                              fixed_events=con.sql('select count(*) from case1_fixed').fetchone()[0],
                              tie_winner_amount=con.sql("select amount from case1_fixed where event_id=1").fetchone()[0])
            elif n == 2:
                before_count=con.sql('select count(*) from case2_bug').fetchone()[0]
                after_count=con.sql('select count(*) from case2_fixed').fetchone()[0]
                total=con.sql('select count(*) from activity').fetchone()[0]
                result.update(total_activity=total, before_matches=before_count, after_matches=after_count,
                              recovered_share=(after_count-before_count)/total)
            else:
                result.update(evaluation_date='2025-01-03',
                              apparent_error_rate=con.sql('select error_rate from case3_bug').fetchone()[0],
                              active_error_rate=con.sql('select error_rate from case3_fixed').fetchone()[0])
            (case / 'results.json').write_text(json.dumps(result, indent=2, default=str)+'\n')
            results[case.name]=result
    return results


if __name__ == '__main__':
    reproduce(sys.argv[1] if len(sys.argv)>1 else 'all')
