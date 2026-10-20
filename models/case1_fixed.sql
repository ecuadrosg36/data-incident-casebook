{{ config(materialized='incremental', unique_key='event_id', incremental_strategy='delete+insert') }}
-- Rank before merging. Sequence is a stable upstream delivery tie-breaker.
select * from {{ ref('events') }}
qualify row_number() over (partition by event_id order by source_updated_at desc, ingested_at desc, delivery_sequence desc) = 1
