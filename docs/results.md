# Executed synthetic evidence

Run `make verify` to regenerate all three `results.json` files and validate the dbt
project and Python assertions. Python 3.12, dbt-duckdb, and DuckDB versions are pinned
by `uv.lock`. No benchmark, employer outcome, or production reliability claim is made.

| Case/report | Machine-readable output | Observed before → after |
| --- | --- | --- |
| [Duplicate events](../cases/01-duplicate-events/WRITEUP.md) | [JSON](../cases/01-duplicate-events/results.json) | 20 duplicate ID groups → 0; 121 deliveries → 100 unique events; tied winner amount 999 |
| [Identity change](../cases/02-identity-change/WRITEUP.md) | [JSON](../cases/02-identity-change/results.json) | 60 → 100 matches; recovered share 0.4 of 100 raw activities |
| [Stale table](../cases/03-stale-table/WRITEUP.md) | [JSON](../cases/03-stale-table/results.json) | 0.2075 combined historical rate → 0.01 active-window rate |

Each JSON object has `synthetic: true`, a stable `case` slug,
`regression_violations_before`, `regression_violations_after`, and `investigation`
rows from the case's SQL. Additional fields expose case-specific counts, rates,
and tie behavior. Rates are fractions, not percentage strings. The stale-table
`evaluation_date` is fixed; it is not a claim of present-day source freshness.

The runner refuses to emit evidence unless the regression catches the injected bug
and passes on the fix. Case 1 executes an initial load followed by a late-delivery
incremental run. Pytest checks semantic outcomes and evidence agreement. CI also
requires regenerated fixtures and case evidence to match the committed files.
Website consumers can link these reports and parse the JSON directly; this project
does not publish or modify a website.
