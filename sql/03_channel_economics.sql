-- Channel x month unit economics.
--
-- Three things meet on (channel, month), and they are always reported side
-- by side, never one without the others:
--
--   * spend            what the platforms charged that month (media line),
--   * acquisition      customers whose first order fell in that month, with
--                      that order's revenue and margin, and the margin the
--                      cohort went on to produce over the LTV horizon,
--   * activity         every paid order credited to the channel that month,
--                      new or returning customer, with its margin.
--
-- Spend is joined in from the platforms. It is never derived from
-- acquisitions, so CAC cannot collapse into an input fed to the model.
-- A channel with no media line has spend NULL, and its CAC stays NULL: an
-- organic customer does not have a CAC of zero, they have no CAC.
--
-- Rates are ratios of sums (total spend / total customers), never averages
-- of per-row rates.

CREATE OR REPLACE TABLE channel_spend_monthly AS
SELECT channel, month, SUM(spend) AS spend
FROM stg_media_daily
GROUP BY ALL;

CREATE OR REPLACE TABLE channel_acquisition AS
SELECT
    cc.channel,
    ce.cohort_month                                   AS month,
    SUM(cc.weight)                                    AS new_customers,
    SUM(cc.weight * ce.first_order_revenue)           AS first_order_revenue,
    SUM(cc.weight * ce.first_order_margin)            AS first_order_margin,
    SUM(cc.weight * ce.margin_in_horizon)             AS margin_in_horizon,
    SUM(cc.weight * ce.orders_in_horizon)             AS orders_in_horizon,
    SUM(cc.weight * (ce.days_to_second_order <= 90)::INTEGER)  AS repeat_90d,
    BOOL_AND(ce.is_mature)                            AS is_mature
FROM customer_channel cc
JOIN customer_economics ce USING (customer_id)
GROUP BY ALL;

CREATE OR REPLACE TABLE channel_activity AS
SELECT
    oc.channel,
    oe.order_month                                    AS month,
    SUM(oc.weight)                                    AS orders,
    SUM(oc.weight * oe.revenue)                       AS revenue,
    SUM(oc.weight * oe.contribution_margin)           AS contribution_margin
FROM stg_order_channel oc
JOIN order_economics oe USING (order_id)
GROUP BY ALL;

-- Cumulative margin of each channel-cohort, month by month after acquisition.
-- Only fully observed months enter: a cohort's month k counts when it ended
-- before the last (partial) month of data.
CREATE OR REPLACE TABLE channel_cohort_curve AS
WITH grid AS (
    SELECT a.channel, a.month AS cohort_month, a.new_customers, k.months_since
    FROM channel_acquisition a,
         range(0, 48) AS k(months_since)
    WHERE strptime(a.month, '%Y-%m') + to_months(k.months_since::INTEGER)
          < date_trunc('month', getvariable('data_end')::DATE)
),
margin AS (
    SELECT cc.channel,
           ce.cohort_month,
           date_diff('month', strptime(ce.cohort_month, '%Y-%m'), date_trunc('month', oe.ordered_at)) AS months_since,
           SUM(cc.weight * oe.contribution_margin) AS margin,
           SUM(cc.weight)                          AS orders
    FROM customer_channel cc
    JOIN customer_economics ce USING (customer_id)
    JOIN order_economics oe ON oe.customer_id = cc.customer_id
    GROUP BY ALL
)
SELECT
    g.channel,
    g.cohort_month,
    g.months_since,
    g.new_customers,
    COALESCE(m.orders, 0)                                                 AS orders,
    COALESCE(m.margin, 0)                                                 AS margin,
    SUM(COALESCE(m.margin, 0)) OVER (
        PARTITION BY g.channel, g.cohort_month ORDER BY g.months_since)  AS cumulative_margin
FROM grid g
LEFT JOIN margin m USING (channel, cohort_month, months_since);

CREATE OR REPLACE TABLE channel_monthly AS
WITH keys AS (
    SELECT channel, month FROM channel_acquisition
    UNION SELECT channel, month FROM channel_activity
    UNION SELECT channel, month FROM channel_spend_monthly
),
payback AS (
    -- Months of margin the cohort needs to cover what was spent to acquire
    -- it, counting the acquisition month: 1 means the first month paid.
    SELECT c.channel, c.cohort_month AS month,
           MIN(c.months_since) FILTER (WHERE c.cumulative_margin >= s.spend) + 1 AS payback_months,
           MAX(c.months_since) + 1                                         AS months_observed
    FROM channel_cohort_curve c
    JOIN channel_spend_monthly s ON s.channel = c.channel AND s.month = c.cohort_month
    WHERE s.spend > 0
    GROUP BY ALL
),
joined AS (
    SELECT
        k.channel,
        k.month,
        list_contains(getvariable('paid_channels')::VARCHAR[], k.channel)     AS is_paid,
        -- A paid channel that spent nothing in a month spent 0.00, which is a
        -- measurement. A channel with no media line has no spend at all.
        CASE WHEN list_contains(getvariable('paid_channels')::VARCHAR[], k.channel)
             THEN COALESCE(s.spend, 0) END                                   AS spend,
        COALESCE(a.new_customers, 0)                                         AS new_customers,
        COALESCE(a.first_order_revenue, 0)                                   AS first_order_revenue,
        COALESCE(a.first_order_margin, 0)                                    AS first_order_margin,
        a.margin_in_horizon,
        a.orders_in_horizon,
        a.repeat_90d,
        -- Maturity belongs to the month, not to whoever was acquired in it: a
        -- paid channel that spent and acquired nobody still has a mature month.
        (strptime(k.month, '%Y-%m') + to_months(getvariable('ltv_horizon_months')::INTEGER))
            <= date_trunc('month', getvariable('data_end')::DATE)            AS is_mature,
        COALESCE(t.orders, 0)                                                AS orders,
        COALESCE(t.revenue, 0)                                               AS revenue,
        COALESCE(t.contribution_margin, 0)                                   AS contribution_margin,
        p.payback_months,
        p.months_observed
    FROM keys k
    LEFT JOIN channel_spend_monthly s USING (channel, month)
    LEFT JOIN channel_acquisition a   USING (channel, month)
    LEFT JOIN channel_activity t      USING (channel, month)
    LEFT JOIN payback p               USING (channel, month)
)
SELECT
    *,
    contribution_margin - COALESCE(spend, 0)                                 AS margin_after_media,
    CASE WHEN spend IS NOT NULL AND new_customers > 0
         THEN spend / new_customers END                                      AS cac,
    CASE WHEN spend IS NOT NULL AND first_order_margin > 0
         THEN spend / first_order_margin END                                 AS cac_share_of_first_margin,
    CASE WHEN is_mature AND new_customers > 0
         THEN margin_in_horizon / new_customers END                          AS ltv,
    CASE WHEN is_mature AND spend > 0
         THEN margin_in_horizon / spend END                                  AS ltv_cac,
    new_customers < getvariable('small_sample')::INTEGER                     AS small_sample
FROM joined
WHERE month BETWEEN getvariable('analysis_start')::VARCHAR AND getvariable('analysis_end')::VARCHAR
ORDER BY month, channel;
