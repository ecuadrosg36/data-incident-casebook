select * from {{ ref('case3_fixed') }} where error_rate > 0.02
