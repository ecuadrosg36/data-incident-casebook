select sum(error_rows)::double / sum(rows_written) as error_rate from {{ ref('write_history') }}
