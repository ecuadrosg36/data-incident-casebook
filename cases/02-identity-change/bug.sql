select a.*, u.user_id from {{ ref('activity') }} a join {{ ref('users') }} u on a.tenant=u.tenant and a.raw_user_id=u.user_id
