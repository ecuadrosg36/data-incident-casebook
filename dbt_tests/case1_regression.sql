select event_id from {{ ref('case1_fixed') }} group by event_id having count(*) > 1
