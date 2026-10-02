-- Channel x cohort-month unit economics.
--
-- Spend is joined in, never derived from acquisitions. Unpaid channels have no
-- spend row at all, so their CAC stays NULL: an organic customer does not have
-- a CAC of zero, they have no CAC.

CREATE OR REPLACE VIEW channel_monthly AS
WITH acquisition AS (
    SELECT
        ch.channel,
        ce.cohort_month                      AS month,
        COUNT(*)                             AS new_customers,
        SUM(ce.gmv)                          AS gmv,
        SUM(ce.contribution_margin)          AS contribution_margin,
        SUM(ce.orders)                       AS orders
    FROM customer_economics ce
    JOIN customer_channel ch USING (customer_unique_id)
    GROUP BY ch.channel, ce.cohort_month
)
SELECT
    a.channel,
    a.month,
    a.new_customers,
    ROUND(a.gmv, 2)                                              AS gmv,
    ROUND(a.contribution_margin, 2)                              AS contribution_margin,
    ROUND(a.contribution_margin / a.new_customers, 2)            AS margin_per_customer,
    s.spend,
    CASE WHEN s.spend IS NOT NULL AND a.new_customers > 0
         THEN ROUND(s.spend / a.new_customers, 2) END            AS cac,
    CASE WHEN s.spend IS NOT NULL AND s.spend > 0 AND a.new_customers > 0
         THEN ROUND((a.contribution_margin / a.new_customers)
                    / (s.spend / a.new_customers), 2) END        AS ltv_cac_ratio
FROM acquisition a
LEFT JOIN channel_spend s
       ON s.channel = a.channel AND s.month = a.month
ORDER BY a.month, a.channel;
