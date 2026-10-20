select a.tenant, a.raw_user_id from activity a left join users u on a.tenant=u.tenant and a.raw_user_id=u.user_id where u.user_id is null order by 1,2;
