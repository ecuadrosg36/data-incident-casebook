select event_id, count(*) deliveries, max(source_updated_at) latest_source_update from events group by event_id having count(*) > 1 order by event_id;
