-- Staging: the ecommerce tables (Parquet, written by the ingest) -> clean,
-- analysis-ready tables.
--
-- Four decisions are made here and they drive every number downstream.
--
-- 1. Identity. The same person sometimes has two accounts (different e-mails,
--    same CPF: the dataset's imperfection #15). Customers are merged on the
--    CPF hash into the oldest account, exactly as the source's own dbt model
--    stg_clientes does. Counting accounts instead of people would turn a
--    repeat purchase into a "new customer" and inflate acquisition.
--
-- 2. Order filter. An order counts when it was paid: status pago, enviado,
--    entregue or devolvido (a returned order was still paid, and its refund is a
--    cost, applied in 02). Cancelled, unpaid and staff test orders are out.
--
-- 3. Channel. Each paid order is credited to channels through the dataset's
--    attribution table, under one model (getvariable('attribution_model')).
--    Google Search is split into brand and non-brand by the campaign's
--    campanha_marca flag. An order with no session (ad blocker, WhatsApp
--    sale) is 'untracked': it is not redistributed to the other channels.
--
-- 4. Spend. Media spend is the platforms' own daily spend, mapped onto the
--    same channel codes. Only Meta and Google carry spend; every other
--    channel has no media line at all.

CREATE OR REPLACE TABLE stg_customers AS
SELECT
    cliente_id,
    -- The oldest account with the same CPF is the canonical one.
    CASE WHEN cpf_hash IS NULL THEN cliente_id
         ELSE MIN(cliente_id) OVER (PARTITION BY cpf_hash) END       AS customer_id,
    tipo_cliente                                                     AS customer_type,
    tipo_pessoa                                                      AS person_type,
    -- Imported from the previous platform: their first order in this
    -- database is not their first order, so they are never "acquired" here.
    origem_cadastro = 'importacao_legado'                            AS is_legacy
FROM read_parquet(getvariable('raw_dir') || '/clientes.parquet')
WHERE conta_teste = 0;

CREATE OR REPLACE TABLE stg_orders AS
SELECT
    p.pedido_id                                      AS order_id,
    c.customer_id,
    c.is_legacy,
    p.criado_em                                      AS ordered_at,
    strftime(p.criado_em, '%Y-%m')                   AS order_month,
    p.canal_venda                                    AS sales_channel,
    p.sessao_id IS NOT NULL                          AS is_tracked,
    p.cupom_id                                       AS coupon_id,
    p.subtotal,
    p.desconto                                       AS discount,
    p.frete                                          AS freight_charged,
    p.total                                          AS revenue
FROM read_parquet(getvariable('raw_dir') || '/pedidos.parquet') p
JOIN stg_customers c ON c.cliente_id = p.cliente_id
WHERE p.pedido_teste = 0
  AND p.status IN ('pago', 'enviado', 'entregue', 'devolvido');

-- Every cost the dataset records, per paid order. The two costs it does not
-- record (payment fee rates, per-order handling) are applied in 02 from
-- config.py, so this table holds only measured values plus the payment
-- method the fee depends on.
CREATE OR REPLACE TABLE stg_order_costs AS
WITH items AS (
    SELECT pedido_id,
           SUM(quantidade * custo_unitario) AS product_cost
    FROM read_parquet(getvariable('raw_dir') || '/itens_pedido.parquet')
    GROUP BY pedido_id
),
payment AS (
    -- One approved attempt per paid order; refused and expired attempts
    -- before it cost nothing.
    SELECT pedido_id,
           ANY_VALUE(metodo)  AS payment_method,
           SUM(valor)         AS amount_paid
    FROM read_parquet(getvariable('raw_dir') || '/pagamentos.parquet')
    WHERE status = 'aprovado'
    GROUP BY pedido_id
),
restocked AS (
    SELECT DISTINCT devolucao_id
    FROM read_parquet(getvariable('raw_dir') || '/movimentacoes_estoque.parquet')
    WHERE tipo = 'entrada_devolucao'
),
returns AS (
    -- Money goes back on an approved or completed return. When the item went
    -- back into stock, its product cost is recovered with it.
    SELECT d.pedido_id,
           SUM(d.valor_reembolsado)                                              AS refunds,
           SUM(CASE WHEN r.devolucao_id IS NOT NULL
                    THEN d.quantidade * i.custo_unitario ELSE 0 END)             AS restocked_cost
    FROM read_parquet(getvariable('raw_dir') || '/devolucoes.parquet') d
    JOIN read_parquet(getvariable('raw_dir') || '/itens_pedido.parquet') i
      ON i.item_pedido_id = d.item_pedido_id
    LEFT JOIN restocked r ON r.devolucao_id = d.devolucao_id
    WHERE d.status IN ('aprovada', 'concluida')
    GROUP BY d.pedido_id
)
SELECT
    o.order_id,
    COALESCE(i.product_cost, 0)      AS product_cost,
    COALESCE(f.custo_real, 0)        AS freight_cost,
    pay.payment_method,
    COALESCE(pay.amount_paid, 0)     AS amount_paid,
    COALESCE(r.refunds, 0)           AS refunds,
    COALESCE(r.restocked_cost, 0)    AS restocked_cost
FROM stg_orders o
LEFT JOIN items i     ON i.pedido_id = o.order_id
LEFT JOIN read_parquet(getvariable('raw_dir') || '/fretes.parquet') f ON f.pedido_id = o.order_id
LEFT JOIN payment pay ON pay.pedido_id = o.order_id
LEFT JOIN returns r   ON r.pedido_id = o.order_id;

-- Google campaign -> channel code. Shared by spend and by attributed orders,
-- so a customer and the money spent to acquire them land in the same bucket.
CREATE OR REPLACE TABLE stg_google_campaigns AS
SELECT
    campanha_id AS campaign_id,
    nome        AS campaign,
    CASE
        WHEN tipo_canal = 'SEARCH' AND campanha_marca = 1 THEN 'paid_search_brand'
        WHEN tipo_canal = 'SEARCH'                        THEN 'paid_search_generic'
        WHEN tipo_canal = 'SHOPPING'                      THEN 'paid_shopping'
        WHEN tipo_canal = 'PERFORMANCE_MAX'               THEN 'performance_max'
        WHEN tipo_canal = 'DEMAND_GEN'                    THEN 'paid_video'
    END         AS channel
FROM read_parquet(getvariable('raw_dir') || '/google_campanhas.parquet');

-- Credit per (paid order, channel) under the chosen attribution model. The
-- weights of one order sum to 1 for every model.
CREATE OR REPLACE TABLE stg_order_channel AS
WITH attributed AS (
    SELECT
        a.pedido_id                                   AS order_id,
        CASE a.canal
            WHEN 'Paid Search'    THEN g.channel
            WHEN 'Paid Social'    THEN 'paid_social'
            WHEN 'Cross-network'  THEN 'performance_max'
            WHEN 'Paid Shopping'  THEN 'paid_shopping'
            WHEN 'Paid Video'     THEN 'paid_video'
            WHEN 'Organic Search' THEN 'organic_search'
            WHEN 'Direct'         THEN 'direct'
            WHEN 'Organic Social' THEN 'organic_social'
            WHEN 'Email'          THEN 'email'
            WHEN 'Referral'       THEN 'referral'
            WHEN 'WhatsApp'       THEN 'whatsapp'
            ELSE 'unassigned'
        END                                           AS channel,
        a.peso                                        AS weight
    FROM read_parquet(getvariable('raw_dir') || '/atribuicoes.parquet') a
    LEFT JOIN stg_google_campaigns g ON g.campaign_id = a.google_campanha_id
    WHERE a.modelo = getvariable('attribution_model')::VARCHAR
)
SELECT o.order_id, a.channel, SUM(a.weight) AS weight
FROM stg_orders o
JOIN attributed a USING (order_id)
GROUP BY o.order_id, a.channel
UNION ALL
-- No attribution row: untracked when there is no session at all, direct when
-- there is one (same fallback as the source's fct_pedidos).
SELECT o.order_id,
       CASE WHEN o.is_tracked THEN 'direct' ELSE 'untracked' END,
       1.0
FROM stg_orders o
WHERE NOT EXISTS (SELECT 1 FROM attributed a WHERE a.order_id = o.order_id);

-- Daily spend per campaign, on the same channel codes.
CREATE OR REPLACE TABLE stg_media_daily AS
SELECT
    m.data                         AS spend_date,
    strftime(m.data, '%Y-%m')      AS month,
    'meta'                         AS platform,
    cp.campanha_id                 AS campaign_id,
    cp.nome                        AS campaign,
    'paid_social'                  AS channel,
    SUM(m.investimento)            AS spend,
    SUM(m.compras)                 AS platform_conversions,
    SUM(m.valor_compras)           AS platform_conversion_value
FROM read_parquet(getvariable('raw_dir') || '/meta_metricas_diarias.parquet') m
JOIN read_parquet(getvariable('raw_dir') || '/meta_anuncios.parquet')  an ON an.anuncio_id = m.anuncio_id
JOIN read_parquet(getvariable('raw_dir') || '/meta_conjuntos.parquet') cj ON cj.conjunto_id = an.conjunto_id
JOIN read_parquet(getvariable('raw_dir') || '/meta_campanhas.parquet') cp ON cp.campanha_id = cj.campanha_id
GROUP BY ALL
UNION ALL
SELECT
    g.data,
    strftime(g.data, '%Y-%m'),
    'google',
    c.campaign_id,
    c.campaign,
    c.channel,
    SUM(g.investimento),
    SUM(g.conversoes),
    SUM(g.valor_conversao)
FROM read_parquet(getvariable('raw_dir') || '/google_metricas_diarias.parquet') g
JOIN read_parquet(getvariable('raw_dir') || '/google_grupos_anuncio.parquet') gr ON gr.grupo_id = g.grupo_id
JOIN stg_google_campaigns c ON c.campaign_id = gr.campanha_id
GROUP BY ALL;

-- Seasonal campaigns the store itself ran, as the source records them. They
-- are what marks a month as seasonal: nothing is read from a calendar. Meta
-- and Google name the same date differently ("[SAZ] Festa Junina 2025 Chitas
-- e Xadrez", "PMax | Festa Junina 2025"), so the event is the date's name
-- and year.
CREATE OR REPLACE TABLE stg_seasonal_campaigns AS
WITH named AS (
    SELECT nome, inicio, fim
    FROM read_parquet(getvariable('raw_dir') || '/meta_campanhas.parquet')
    WHERE estrategia = 'sazonal'
    UNION ALL
    SELECT nome, inicio, fim
    FROM read_parquet(getvariable('raw_dir') || '/google_campanhas.parquet')
)
SELECT regexp_extract(nome, '(Black Friday|Natal|Festa Junina|Dia das Mães|Volta às Aulas) \d{4}') AS event,
       inicio AS starts,
       fim    AS ends
FROM named
WHERE regexp_extract(nome, '(Black Friday|Natal|Festa Junina|Dia das Mães|Volta às Aulas) \d{4}') <> '';
