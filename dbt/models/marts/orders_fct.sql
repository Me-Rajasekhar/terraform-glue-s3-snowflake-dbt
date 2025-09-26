{{ config(materialized='table') }}
with orders as (
  select * from {{ ref('stg_orders') }}
)
select
  order_id,
  customer_id,
  amount,
  order_ts,
  date_trunc('day', order_ts) as order_date,
  ingestion_date
from orders
