export DBT_SEND_ANONYMOUS_USAGE_STATS := false
.PHONY: setup case-1 case-2 case-3 verify
setup:
	uv sync --frozen
case-1 case-2 case-3:
	uv run python -m scripts.reproduce $@
verify:
	uv run python -m scripts.reproduce all
	uv run dbt build --profiles-dir .
	uv run pytest
