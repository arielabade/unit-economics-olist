-- One row per customer: cohort, orders, GMV and contribution margin.
--
-- Contribution margin follows the marketplace model, not the retail one:
--   commission   = gmv * take_rate
--   payment cost = gmv * psp_fee_rate     (charged on the whole transaction)
--   support cost = variable_support_cost * orders
-- Charging margin on GMV instead of on the commission would overstate the
-- economics by roughly the inverse of the take rate.

CREATE OR REPLACE VIEW customer_economics AS
WITH per_customer AS (
    SELECT
        o.customer_unique_id,
        MIN(o.purchase_month)              AS cohort_month,
        MIN(o.purchased_at)                AS first_purchase_at,
        MAX(o.purchased_at)                AS last_purchase_at,
        COUNT(DISTINCT o.order_id)         AS orders,
        SUM(v.gmv)                         AS gmv
    FROM stg_orders o
    JOIN stg_order_value v USING (order_id)
    GROUP BY o.customer_unique_id
)
SELECT
    customer_unique_id,
    cohort_month,
    first_purchase_at,
    last_purchase_at,
    orders,
    ROUND(gmv, 2)                                                   AS gmv,
    ROUND(
        gmv * getvariable('take_rate')::DOUBLE
        - gmv * getvariable('psp_fee_rate')::DOUBLE
        - orders * getvariable('variable_support_cost')::DOUBLE
    , 2)                                                            AS contribution_margin,
    -- Observed lifetime in months. Zero for a single-purchase customer, which
    -- is the honest value: nothing has been observed beyond the first order.
    DATE_DIFF('month', first_purchase_at, last_purchase_at)         AS observed_lifetime_months
FROM per_customer;
