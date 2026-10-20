{{ config(materialized='incremental', unique_key='event_id', incremental_strategy='delete+insert') }}
select * from {{ ref('events') }}
