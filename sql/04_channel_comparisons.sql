-- Month-over-month and year-over-year comparisons, per channel and in total.
--
-- Two roll-ups are added to the channels, built from sums and never from
-- averages of the channels' own rates:
--   'paid_total'  every channel with a media line,
--   'all'         the whole store: total spend over every new customer, the
--                 blended CAC finance would quote.
--
-- Each month carries the seasonal events the store itself ran (its [SAZ]
-- campaigns, from the dataset) and the documented Meta pause, so a jump can
-- be read against its cause. Channel-months with few new customers are
-- flagged rather than interpreted.

CREATE OR REPLACE TABLE month_events AS
WITH months AS (
    SELECT DISTINCT month FROM channel_monthly
),
seasonal AS (
    SELECT m.month, s.event
    FROM months m
    JOIN stg_seasonal_campaigns s
      ON date_diff('day',
                   greatest(strptime(m.month, '%Y-%m')::DATE, s.starts),
                   least((strptime(m.month, '%Y-%m') + INTERVAL 1 MONTH)::DATE - 1,
                         COALESCE(s.ends, getvariable('data_end')::DATE))) + 1
         >= getvariable('seasonal_min_days')::INTEGER
),
labels AS (
    SELECT month, event FROM seasonal
    UNION
    SELECT month, event FROM documented_events
)
SELECT month, string_agg(event, ' · ' ORDER BY event) AS events
FROM labels
GROUP BY month;

CREATE OR REPLACE TABLE channel_comparisons AS
WITH rollup_curve AS (
    -- Cumulative margin of every paid cohort of a month, added across channels.
    SELECT c.cohort_month AS month, c.months_since,
           SUM(c.cumulative_margin) AS cumulative_margin
    FROM channel_cohort_curve c
    WHERE list_contains(getvariable('paid_channels')::VARCHAR[], c.channel)
    GROUP BY ALL
),
rollup_spend AS (
    SELECT month, SUM(spend) AS spend
    FROM channel_monthly
    WHERE is_paid
    GROUP BY month
),
rollup_payback AS (
    SELECT r.month,
           MIN(r.months_since) FILTER (WHERE r.cumulative_margin >= s.spend) + 1 AS payback_months,
           MAX(r.months_since) + 1                                         AS months_observed
    FROM rollup_curve r JOIN rollup_spend s USING (month)
    WHERE s.spend > 0
    GROUP BY r.month
),
rollups AS (
    SELECT
        CASE WHEN grp = 'paid' THEN 'paid_total' ELSE 'all' END            AS channel,
        month,
        grp = 'paid'                                                       AS is_paid,
        SUM(spend)                                                         AS spend,
        SUM(new_customers)                                                 AS new_customers,
        SUM(first_order_revenue)                                           AS first_order_revenue,
        SUM(first_order_margin)                                            AS first_order_margin,
        SUM(margin_in_horizon)                                             AS margin_in_horizon,
        SUM(orders_in_horizon)                                             AS orders_in_horizon,
        SUM(repeat_90d)                                                    AS repeat_90d,
        BOOL_AND(is_mature)                                                AS is_mature,
        SUM(orders)                                                        AS orders,
        SUM(revenue)                                                       AS revenue,
        SUM(contribution_margin)                                           AS contribution_margin
    FROM (
        SELECT *, 'paid' AS grp FROM channel_monthly WHERE is_paid
        UNION ALL
        SELECT *, 'all' AS grp FROM channel_monthly
    )
    GROUP BY ALL
),
rollup_rows AS (
    SELECT
        r.*,
        -- 'all' is paid for the store's whole acquisition: its payback is
        -- the paid cohorts' (no spend reaches the unpaid ones).
        CASE WHEN r.channel = 'paid_total' THEN p.payback_months END        AS payback_months,
        CASE WHEN r.channel = 'paid_total' THEN p.months_observed END       AS months_observed,
        r.contribution_margin - r.spend                                     AS margin_after_media,
        CASE WHEN r.new_customers > 0 THEN r.spend / r.new_customers END    AS cac,
        CASE WHEN r.first_order_margin > 0 THEN r.spend / r.first_order_margin END AS cac_share_of_first_margin,
        CASE WHEN r.is_mature AND r.new_customers > 0
             THEN r.margin_in_horizon / r.new_customers END                 AS ltv,
        CASE WHEN r.is_mature AND r.spend > 0
             THEN r.margin_in_horizon / r.spend END                         AS ltv_cac,
        r.new_customers < getvariable('small_sample')::INTEGER              AS small_sample
    FROM rollups r
    LEFT JOIN rollup_payback p USING (month)
),
base AS (
    SELECT channel, month, is_paid, spend, new_customers, first_order_revenue, first_order_margin,
           margin_in_horizon, orders_in_horizon, repeat_90d, is_mature, orders, revenue,
           contribution_margin, payback_months, months_observed, margin_after_media, cac,
           cac_share_of_first_margin, ltv, ltv_cac, small_sample
    FROM channel_monthly
    UNION ALL
    SELECT channel, month, is_paid, spend, new_customers, first_order_revenue, first_order_margin,
           margin_in_horizon, orders_in_horizon, repeat_90d, is_mature, orders, revenue,
           contribution_margin, payback_months, months_observed, margin_after_media, cac,
           cac_share_of_first_margin, ltv, ltv_cac, small_sample
    FROM rollup_rows
),
-- Every channel gets every month, so LAG(1) is always the calendar month
-- before and LAG(12) the same month a year earlier.
grid AS (
    SELECT c.channel, m.month
    FROM (SELECT DISTINCT channel FROM base) c,
         (SELECT DISTINCT month FROM base) m
),
dense AS (
    SELECT g.channel, g.month, b.* EXCLUDE (channel, month)
    FROM grid g LEFT JOIN base b USING (channel, month)
),
lagged AS (
    SELECT
        d.*,
        LAG(spend, 1)               OVER w AS spend_prev_month,
        LAG(new_customers, 1)       OVER w AS new_customers_prev_month,
        LAG(revenue, 1)             OVER w AS revenue_prev_month,
        LAG(contribution_margin, 1) OVER w AS margin_prev_month,
        LAG(cac, 1)                 OVER w AS cac_prev_month,
        LAG(spend, 12)              OVER w AS spend_prev_year,
        LAG(new_customers, 12)      OVER w AS new_customers_prev_year,
        LAG(revenue, 12)            OVER w AS revenue_prev_year,
        LAG(contribution_margin, 12) OVER w AS margin_prev_year,
        LAG(cac, 12)                OVER w AS cac_prev_year
    FROM dense d
    WINDOW w AS (PARTITION BY channel ORDER BY month)
)
SELECT
    l.*,
    e.events,
    spend / NULLIF(spend_prev_month, 0) - 1                       AS spend_mom,
    new_customers / NULLIF(new_customers_prev_month, 0) - 1       AS new_customers_mom,
    revenue / NULLIF(revenue_prev_month, 0) - 1                   AS revenue_mom,
    contribution_margin / NULLIF(margin_prev_month, 0) - 1        AS margin_mom,
    cac / NULLIF(cac_prev_month, 0) - 1                           AS cac_mom,
    spend / NULLIF(spend_prev_year, 0) - 1                        AS spend_yoy,
    new_customers / NULLIF(new_customers_prev_year, 0) - 1        AS new_customers_yoy,
    revenue / NULLIF(revenue_prev_year, 0) - 1                    AS revenue_yoy,
    contribution_margin / NULLIF(margin_prev_year, 0) - 1         AS margin_yoy,
    cac / NULLIF(cac_prev_year, 0) - 1                            AS cac_yoy
FROM lagged l
LEFT JOIN month_events e USING (month)
WHERE l.is_paid IS NOT NULL      -- the grid's empty cells are only there for LAG
ORDER BY channel, month;

CREATE OR REPLACE TABLE monthly_totals AS
SELECT * FROM channel_comparisons WHERE channel = 'all' ORDER BY month;

-- Where each real of revenue goes, per month, before media and after it.
CREATE OR REPLACE TABLE monthly_pnl AS
WITH costs AS (
    SELECT
        order_month                AS month,
        COUNT(*)                   AS orders,
        SUM(revenue)               AS revenue,
        SUM(product_cost)          AS product_cost,
        SUM(freight_cost)          AS freight_cost,
        SUM(freight_charged)       AS freight_charged,
        SUM(refunds)               AS refunds,
        SUM(restocked_cost)        AS restocked_cost,
        SUM(payment_fee)           AS payment_fee,
        SUM(variable_order_cost)   AS variable_order_cost,
        SUM(contribution_margin)   AS contribution_margin
    FROM order_economics
    WHERE order_month BETWEEN getvariable('analysis_start')::VARCHAR AND getvariable('analysis_end')::VARCHAR
    GROUP BY order_month
)
SELECT c.*,
       s.spend,
       c.contribution_margin - s.spend AS margin_after_media
FROM costs c
LEFT JOIN (SELECT month, SUM(spend) AS spend FROM channel_spend_monthly GROUP BY month) s USING (month)
ORDER BY month;
