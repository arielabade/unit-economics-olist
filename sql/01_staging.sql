-- Staging: raw CSVs -> clean, analysis-ready views.
--
-- Two decisions are made here and they drive every number downstream.
--
-- 1. Identity. Olist has customer_id (one per ORDER) and customer_unique_id
--    (one per PERSON). Counting customers by customer_id reports 99,441
--    customers where there are 96,096 people, and makes repeat purchase
--    mathematically impossible to observe. Everything below keys on
--    customer_unique_id.
--
-- 2. Order filter. Only 'delivered' orders are counted. Cancelled and
--    unavailable orders carry no commission, so including them would inflate
--    revenue and understate CAC.

CREATE OR REPLACE VIEW stg_orders AS
SELECT
    o.order_id,
    c.customer_unique_id,
    o.order_purchase_timestamp::TIMESTAMP          AS purchased_at,
    strftime(o.order_purchase_timestamp, '%Y-%m')  AS purchase_month
FROM read_csv_auto(getvariable('orders_path')::VARCHAR, header = true)    AS o
JOIN read_csv_auto(getvariable('customers_path')::VARCHAR, header = true) AS c
  ON o.customer_id = c.customer_id
WHERE o.order_status = 'delivered';

-- Order value. Olist stores one row per ITEM, so an order's value is the sum of
-- its items. Freight is excluded from GMV: it is passed through to the carrier
-- and the marketplace takes no commission on it.
CREATE OR REPLACE VIEW stg_order_value AS
SELECT
    order_id,
    SUM(price)         AS gmv,
    SUM(freight_value) AS freight,
    COUNT(*)           AS item_count
FROM read_csv_auto(getvariable('items_path')::VARCHAR, header = true)
GROUP BY order_id;
