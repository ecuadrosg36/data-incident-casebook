-- Fixed evaluation date makes this historical synthetic investigation reproducible.
select sum(error_rows)::double / sum(rows_written) as error_rate
from {{ ref('write_history') }} where write_date >= date '2025-01-01'
