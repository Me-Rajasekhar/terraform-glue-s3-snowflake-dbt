{{ config(materialized='view') }}
with raw as (
  select
    order_id::string as order_id,
    customer_id::string as customer_id,
    amount::number as amount,
    order_ts::timestamp_ntz as order_ts,
    ingestion_date::date as ingestion_date
  from {{ source('upcrewpro','stg_orders') }}
)
select * from raw where order_ts is not null
