select tenant, raw_user_id from activity except select tenant, raw_user_id from {{ ref('case2_fixed') }}
