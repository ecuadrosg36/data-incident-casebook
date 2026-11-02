# data-incident-casebook

[![CI](https://github.com/ecuadrosg36/data-incident-casebook/actions/workflows/ci.yml/badge.svg)](https://github.com/ecuadrosg36/data-incident-casebook/actions/workflows/ci.yml)

**How I debug data that is quietly wrong.** Three reproducible incidents, each worked like an investigation:
symptom → hypotheses → evidence → root cause → fix → a guard so it can't happen silently again.

Every number in the case files is computed by the code from generated data. Run `casebook run all` and you
get the same tables you see below.

| # | Incident | Root cause | Before → after |
|---|---|---|---|
| 01 | [Daily impressions dropped overnight](docs/01-silent-join-loss.md) | INNER JOIN to a dimension that was a week behind | report −70.2% on a launch day → totals match staging every day |
| 02 | [Customer match rate fell after a CRM upgrade](docs/02-key-format-change.md) | CRM started exporting `pe_123` instead of `PE-000123` | 57.0% matched → 97.8%; the 900 left are genuinely new contacts |
| 03 | [Dashboard revenue is higher than the ledger](docs/03-duplicate-events.md) | At-least-once delivery + an append-only load that was re-run | +15.3% vs ledger → 0.0%, and safe to re-run |

## The method

Each case file follows the same steps, because the hard part of an incident is usually not the fix but
finding *where* the data went wrong:

1. **Symptom:** what someone noticed, in their words and numbers.
2. **Hypotheses, cheapest first:** did the source change? Did a step drop rows? Did a key change?
3. **Evidence:** one query per hypothesis, with a verdict. Rejected hypotheses stay in the file: they show
   what was ruled out and how.
4. **Root cause** and **fix.**
5. **Guard:** a check that stays in the pipeline, so the same failure breaks a build instead of a report.
6. **Before and after**, measured the same way.

## Reusable checks

The guards come from [`checks.py`](src/casebook/checks.py), small functions you can drop into any DuckDB,
dbt or Airflow pipeline:

| Check | Catches |
|---|---|
| `reconcile(upstream, downstream, by=day)` | A step that loses or invents rows, day by day |
| `match_rate(left, right, ...)` | Joins that slowly stop matching |
| `key_shapes(table, column)` | Key format changes (`PE-000123` → `AA-999999`) |
| `duplicate_share(table, key)` | Repeated events or double loads |
| `is_idempotent(load, measure)` | Loads that change the result when re-run |

## Run it

```bash
uv sync
uv run casebook list
uv run casebook run 2          # one incident, by number or slug
uv run casebook run all
uv run casebook docs           # rewrite docs/ from the code
uv run pytest                  # 15 tests, ~99% coverage
```

A test checks that the case files in `docs/` match what the code produces, so the write-ups can't drift from
the evidence.

## Why these three

They are patterns I have seen in production in different forms: a join that drops rows without an error, an
identifier that changes format upstream, and duplicates from retries combined with a load that isn't safe to
repeat. The companies, systems and numbers here are made up. The data is generated with deterministic hashes,
so every run gives the same results.

## Next

- Incident 04: a timezone change that moves late-night orders to the next day.
- Run the same guards as dbt tests, so they work on Snowflake or BigQuery and not only on DuckDB.

MIT License.
