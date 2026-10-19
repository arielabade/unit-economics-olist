-- Repeat purchase and retention, by acquisition channel.
--
-- Only mature cohorts enter (the whole LTV horizon observed): a customer
-- acquired last month has not had the chance to come back, and mixing them
-- in would make every recent channel look disloyal.
--
-- channel_retention   one row per channel (+ 'paid_total', 'all'): share of
--                     customers who bought again within 90 days and within
--                     the horizon, orders per customer, LTV, and the pooled
--                     payback against the channel's CAC over the window.
-- channel_ltv_curve   average cumulative margin per customer, month by month
--                     after acquisition, pooled across the cohorts observed
--                     for that many months (ratio of sums).

CREATE OR REPLACE TABLE customer_retention AS
SELECT
    cc.channel,
    cc.weight,
    ce.customer_id,
    ce.cohort_month,
    ce.first_order_margin,
    ce.orders_in_horizon,
    ce.margin_in_horizon,
    (ce.days_to_second_order <= 90)::INTEGER        AS repeat_90d,
    (ce.orders_in_horizon >= 2)::INTEGER            AS repeat_in_horizon
FROM customer_channel cc
JOIN customer_economics ce USING (customer_id)
WHERE ce.is_mature
  AND ce.cohort_month BETWEEN getvariable('analysis_start')::VARCHAR AND getvariable('analysis_end')::VARCHAR;

CREATE OR REPLACE TABLE channel_ltv_curve AS
WITH tagged AS (
    SELECT channel, cohort_month, months_since, new_customers, cumulative_margin
    FROM channel_cohort_curve
    WHERE cohort_month BETWEEN getvariable('analysis_start')::VARCHAR AND getvariable('analysis_end')::VARCHAR
),
grouped AS (
    SELECT channel, months_since, new_customers, cumulative_margin FROM tagged
    UNION ALL
    SELECT 'paid_total', months_since, new_customers, cumulative_margin FROM tagged
    WHERE list_contains(getvariable('paid_channels')::VARCHAR[], channel)
    UNION ALL
    SELECT 'all', months_since, new_customers, cumulative_margin FROM tagged
)
SELECT channel, months_since,
       SUM(new_customers)                          AS customers_observed,
       SUM(cumulative_margin) / SUM(new_customers) AS cumulative_margin_per_customer
FROM grouped
GROUP BY ALL
HAVING SUM(new_customers) > 0
ORDER BY channel, months_since;

CREATE OR REPLACE TABLE channel_retention AS
WITH grouped AS (
    SELECT * FROM customer_retention
    UNION ALL
    SELECT * REPLACE ('paid_total' AS channel) FROM customer_retention
    WHERE list_contains(getvariable('paid_channels')::VARCHAR[], channel)
    UNION ALL
    SELECT * REPLACE ('all' AS channel) FROM customer_retention
),
retention AS (
    SELECT
        channel,
        SUM(weight)                                         AS mature_customers,
        SUM(weight * repeat_90d) / SUM(weight)              AS repeat_rate_90d,
        SUM(weight * repeat_in_horizon) / SUM(weight)       AS repeat_rate_in_horizon,
        SUM(weight * orders_in_horizon) / SUM(weight)       AS orders_per_customer_in_horizon,
        SUM(weight * first_order_margin) / SUM(weight)      AS first_order_margin_per_customer,
        SUM(weight * margin_in_horizon) / SUM(weight)       AS ltv
    FROM grouped
    GROUP BY channel
),
acquisition_cost AS (
    -- Spend and customers over every cohort of the window, mature or not:
    -- CAC is a fact on the day of acquisition and needs no maturity.
    SELECT channel, SUM(spend) AS spend, SUM(new_customers) AS new_customers
    FROM channel_comparisons
    GROUP BY channel
),
payback AS (
    SELECT c.channel,
           MIN(c.months_since) FILTER (
               WHERE c.cumulative_margin_per_customer >= a.spend / a.new_customers) + 1 AS payback_months,
           MAX(c.months_since) + 1                                                AS months_observed
    FROM channel_ltv_curve c
    JOIN acquisition_cost a USING (channel)
    WHERE a.spend > 0 AND a.new_customers > 0
    GROUP BY c.channel
)
SELECT
    r.*,
    a.spend,
    a.new_customers,
    CASE WHEN a.spend IS NOT NULL AND a.new_customers > 0 THEN a.spend / a.new_customers END AS cac,
    p.payback_months,
    p.months_observed
FROM retention r
LEFT JOIN acquisition_cost a USING (channel)
LEFT JOIN payback p USING (channel)
ORDER BY a.new_customers DESC NULLS LAST;
