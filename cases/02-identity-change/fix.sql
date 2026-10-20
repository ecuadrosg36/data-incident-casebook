select a.*, u.user_id from {{ ref('activity') }} a
left join {{ ref('identity_map') }} m on a.raw_user_id=m.raw_user_id
join {{ ref('users') }} u on a.tenant=u.tenant and coalesce(m.canonical_user_id,a.raw_user_id)=u.user_id
