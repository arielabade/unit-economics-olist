-- Order and customer economics.
--
-- The store is a retailer, not a marketplace: it keeps the whole sale and
-- pays for the goods. Contribution margin is therefore built on revenue minus
-- the costs of serving the order, before any media spend:
--
--   contribution_margin = revenue                (products - discount + freight charged)
--                       - product_cost           (quantity x unit cost, from the order items)
--                       - freight_cost           (what the carrier really charged)
--                       - refunds                (approved or completed returns)
--                       + restocked_cost         (product cost recovered when the item went back to stock)
--                       - payment_fee            (ASSUMED rate x amount paid, by method)
--                       - variable_order_cost    (ASSUMED packaging and service per order)
--
-- Only the last two are assumptions (config.py). Everything else is read
-- from the dataset.

CREATE OR REPLACE TABLE order_economics AS
SELECT
    o.order_id,
    o.customer_id,
    o.is_legacy,
    o.ordered_at,
    o.order_month,
    o.revenue,
    c.product_cost,
    c.freight_cost,
    o.freight_charged,
    c.refunds,
    c.restocked_cost,
    c.payment_method,
    CASE c.payment_method
        WHEN 'pix'            THEN c.amount_paid * getvariable('fee_pix')::DOUBLE
        WHEN 'cartao_credito' THEN c.amount_paid * getvariable('fee_card')::DOUBLE
        WHEN 'boleto'         THEN getvariable('fee_boleto')::DOUBLE
        ELSE 0
    END                                                                      AS payment_fee,
    getvariable('variable_order_cost')::DOUBLE                               AS variable_order_cost,
    ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.ordered_at, o.order_id) AS order_seq
FROM stg_orders o
JOIN stg_order_costs c USING (order_id);

CREATE OR REPLACE TABLE order_economics AS
SELECT
    *,
    revenue - product_cost - freight_cost - refunds + restocked_cost
            - payment_fee - variable_order_cost                              AS contribution_margin
FROM order_economics;

-- One row per person. Acquisition is the first paid order. Legacy customers
-- (imported from the previous platform) keep their orders here but are never
-- counted as acquired, because their first order in this database was not
-- their first order.
CREATE OR REPLACE TABLE customer_economics AS
WITH firsts AS (
    SELECT customer_id,
           order_id                AS first_order_id,
           ordered_at              AS first_order_at,
           order_month             AS cohort_month,
           revenue                 AS first_order_revenue,
           contribution_margin     AS first_order_margin
    FROM order_economics
    WHERE order_seq = 1
),
seconds AS (
    SELECT customer_id, ordered_at AS second_order_at
    FROM order_economics
    WHERE order_seq = 2
),
horizon AS (
    SELECT
        e.customer_id,
        COUNT(*)                                                              AS orders,
        SUM(e.revenue)                                                        AS revenue,
        SUM(e.contribution_margin)                                            AS contribution_margin,
        COUNT(*) FILTER (WHERE date_diff('month', date_trunc('month', f.first_order_at),
                                         date_trunc('month', e.ordered_at))
                               < getvariable('ltv_horizon_months')::INTEGER)  AS orders_in_horizon,
        SUM(e.contribution_margin) FILTER (
                         WHERE date_diff('month', date_trunc('month', f.first_order_at),
                                         date_trunc('month', e.ordered_at))
                               < getvariable('ltv_horizon_months')::INTEGER)  AS margin_in_horizon
    FROM order_economics e
    JOIN firsts f USING (customer_id)
    GROUP BY e.customer_id
)
SELECT
    f.customer_id,
    BOOL_OR(c.is_legacy)                                                      AS is_legacy,
    f.cohort_month,
    f.first_order_id,
    f.first_order_at,
    f.first_order_revenue,
    f.first_order_margin,
    s.second_order_at,
    date_diff('day', f.first_order_at, s.second_order_at)                     AS days_to_second_order,
    h.orders,
    h.revenue,
    h.contribution_margin,
    h.orders_in_horizon,
    h.margin_in_horizon,
    -- A cohort is mature when its whole LTV horizon has been observed: the
    -- last horizon month ends before the last complete month of data.
    (strptime(f.cohort_month, '%Y-%m') + to_months(getvariable('ltv_horizon_months')::INTEGER))
        <= date_trunc('month', getvariable('data_end')::DATE)                 AS is_mature
FROM firsts f
JOIN horizon h USING (customer_id)
JOIN stg_customers c ON c.customer_id = f.customer_id
LEFT JOIN seconds s USING (customer_id)
GROUP BY ALL;

-- Which channel acquired each customer: the credit of their first order.
-- Under last_click or first_click this is one channel with weight 1. Under
-- linear or data_driven a customer is shared across channels, and every
-- count downstream is a sum of weights.
CREATE OR REPLACE TABLE customer_channel AS
SELECT ce.customer_id, oc.channel, oc.weight
FROM customer_economics ce
JOIN stg_order_channel oc ON oc.order_id = ce.first_order_id
WHERE NOT ce.is_legacy;
