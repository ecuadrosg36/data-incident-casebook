# Data incident casebook

Three reproducible **synthetic** investigations for Senior Data Engineer reviewers.
These are local simulations, not claims of employment incidents or business impact.

- [Duplicate events](cases/01-duplicate-events/WRITEUP.md): rank deliveries before incremental ingestion to restore one row per event with deterministic timestamp ties.
- [Composite identity change](cases/02-identity-change/WRITEUP.md): explicit mapping restores 40 of 100 activity matches while retaining tenant boundaries.
- [Stale table](cases/03-stale-table/WRITEUP.md): write history separates a combined 20.75% historical rate from a 1% active-window rate.

Use Python **3.12**, [uv](https://docs.astral.sh/uv/), and GNU-compatible make:

```sh
make setup
make case-1
make case-2
make case-3
make verify
```

Each case target reproduces its full investigation and evidence. All targets use one
local DuckDB database and shared dbt project; run them sequentially. `make verify`
regenerates all evidence, executes `dbt build`, and runs pytest. No credentials,
services, external datasets, or API calls are needed. CI installs locked dependencies
and runs those same checks; dbt telemetry is disabled. Dependency downloads are the
only required network access in CI.

Each case includes a deterministic data generator (no random sampling), bug and fix
SQL, investigation SQL, regression query, writeup, and committed `results.json`.
Executable dbt models live in `models/`; case-local SQL copies make reviews easier.
[Verified results](docs/results.md) describes the machine-readable evidence contract.
Regressions deliberately fail against broken relations and pass against fixed ones.
Bug models remain queryable for comparison but are not presented as correct outputs.

The incremental demonstration uses DuckDB delete-and-insert, not warehouse-specific
MERGE syntax. It reads full source history for correctness at this fixture size.
Generated data and committed evidence contain no personal or production information.
