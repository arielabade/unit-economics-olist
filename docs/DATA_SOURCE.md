# Fonte de dados

Este projeto lê o banco do repositório irmão **`ecommerce`**: a *Tecelã Tecidos*, loja online
brasileira de tecidos **fictícia**, com dados **simulados** a partir do funcionamento de um
e-commerce real. Nada aqui é dado de uma empresa real. O repositório `ecommerce` só é lido,
nunca alterado.

| | |
| --- | --- |
| Banco | MySQL 8.4, banco `tecidos`, 33 tabelas (`ecommerce/schema.sql`) |
| Como sobe | `make ambiente && make dados && make mysql` no repositório `ecommerce` |
| Gerador | `ecommerce/gerador/`, determinístico: seed `20231001`, escala `1.0` |
| Período | 01/10/2023 a 13/10/2026 (outubro/2026 tem 13 dias e fica fora das comparações mensais) |
| Volume usado | 143.633 pedidos (133.649 pagos), 268.214 itens, 50.140 contas de cliente, 669.012 linhas de atribuição, 30.418 linhas diárias de mídia |
| Modelo de negócio | **Loja própria (varejo)**: a loja fica com a venda inteira e paga pela mercadoria. Não é marketplace |

## Como a ingestão garante o mesmo resultado a cada execução

`python -m unit_economics.ingest` lê 16 tabelas do MySQL (ou, com `--source csv`, os CSVs que
`make dados` grava em `ecommerce/data/csv`) e grava Parquet em `data/raw/`, em ordem de chave
primária. Depois confere:

- **contagem de linhas** de cada tabela contra o que o gerador produz com a seed e a escala
  acima (`config.EXPECTED_ROWS`);
- **somas de controle** das colunas de dinheiro (`config.EXPECTED_SUMS`): total dos pedidos, total
  dos itens, custo real do frete e investimento de Meta e Google, ao centavo.

Qualquer diferença interrompe a execução. Dados pessoais não saem da fonte: o CPF vira SHA-256 (só
serve para unir contas da mesma pessoa) e o e-mail vira apenas a marcação de conta de teste.

### Verificação feita em 19/10/2026

| Verificação | Resultado |
| --- | --- |
| `make mysql` (docker compose) | container `tecidos-mysql` saudável, carga concluída |
| Tabelas do banco x `schema.sql` | 33 de 33 tabelas, com as mesmas colunas, na mesma ordem, com os mesmos tipos e nulidade |
| Contagens do banco x resumo do gerador (`data/verdade/resumo.json`) | idênticas nas 33 tabelas |
| Gerador rodado duas vezes (`ESCALA=0.05`, saída fora do repositório) | 33 CSVs byte a byte idênticos |
| Ingestão rodada duas vezes | 16 arquivos Parquet byte a byte idênticos |
| Ingestão por MySQL x por CSV | mesmo schema nas 16 tabelas |
| Este projeto x marts do dbt do `ecommerce` (`fct_kpis_diarios`, `dim_clientes`) | mesmos 133.649 pedidos pagos, R$ 38.866.883,54 de receita, 47.093 novos clientes, R$ 4.295.525,84 de investimento, 49.575 pessoas após unir contas e o mesmo canal de aquisição por cliente |

## Tabelas do banco

Granularidade = o que uma linha representa. **Usada** = lida por este projeto.

| Tabela | Granularidade | Usada | Para quê |
| --- | --- | --- | --- |
| `clientes` | conta de cliente | sim | identidade (CPF → pessoa), base legada, conta de teste |
| `enderecos` | endereço de um cliente | não | — |
| `pedidos` | pedido | sim | receita, status, data, sessão (rastreado ou não), frete cobrado, desconto |
| `itens_pedido` | linha do pedido (SKU) | sim | custo do produto vendido (`quantidade × custo_unitario`) |
| `pagamentos` | tentativa de pagamento | sim | método do pagamento aprovado (base da taxa) |
| `fretes` | envio de um pedido (1:1) | sim | custo real do frete |
| `devolucoes` | item devolvido | sim | reembolso |
| `movimentacoes_estoque` | movimento de estoque | sim | se o item devolvido voltou ao estoque (custo recuperado) |
| `cupons` | cupom | lida, fora dos cálculos | documenta os cupons de influenciador, que não têm custo registrado |
| `atribuicoes` | pedido × modelo × sessão (toque) | sim | **canal de aquisição**, nos 4 modelos (`last_click`, `first_click`, `linear`, `data_driven`) |
| `meta_contas` | conta de anúncios Meta | não | — |
| `meta_campanhas` | campanha Meta | sim | campanhas sazonais `[SAZ]` (eventos) |
| `meta_conjuntos` | conjunto de anúncios | sim | ligação anúncio → campanha |
| `meta_anuncios` | anúncio | sim | ligação métrica → conjunto |
| `meta_metricas_diarias` | dia × anúncio | sim | **investimento Meta** e conversões que a Meta reporta |
| `google_contas` | conta Google Ads | não | — |
| `google_campanhas` | campanha Google | sim | tipo (Search, Shopping, PMax, Demand Gen), **marca x genérica**, eventos |
| `google_grupos_anuncio` | grupo de anúncios / asset group | sim | ligação métrica → campanha |
| `google_metricas_diarias` | dia × grupo de anúncios | sim | **investimento Google** e conversões que o Google reporta |
| `google_palavras_chave` | palavra-chave | não | — |
| `google_palavras_chave_metricas_diarias` | dia × palavra-chave | não | — (soma igual à do grupo) |
| `cliques_midia` | clique em anúncio que gerou sessão | não | já resolvido em `atribuicoes` |
| `sessoes` | sessão do site | não | já resolvida em `atribuicoes` |
| `eventos` | evento GA4 | não | — |
| `envios_conversao` | envio server-side à Meta CAPI / Google | não | — |
| `categorias`, `fornecedores`, `produtos`, `variantes`, `historico_precos` | catálogo | não | o custo usado é o gravado no item do pedido |
| `estoque`, `estoque_diario` | SKU / SKU × dia | não | — |
| `avaliacoes` | avaliação de produto | não | — |

## De onde vem cada número

| Conceito | Campos | Regra |
| --- | --- | --- |
| **Cliente** | `clientes.cliente_id`, `clientes.cpf` | contas com o mesmo CPF viram uma pessoa (a conta mais antiga), como no `stg_clientes` do dbt da fonte. Conta de teste da equipe fica fora |
| **Novo cliente** | 1º pedido pago da pessoa | clientes importados da plataforma anterior (`origem_cadastro = 'importacao_legado'`) não contam como adquiridos: a primeira compra deles aqui não foi a primeira |
| **Pedido** | `pedidos.status`, `pedidos.pedido_teste` | pago = `pago`, `enviado`, `entregue` ou `devolvido`. Cancelados, aguardando pagamento e pedidos de teste ficam fora |
| **Receita** | `pedidos.total` | produtos − desconto + frete cobrado (`total = subtotal − desconto + frete`) |
| **Custo do produto** | `itens_pedido.quantidade × custo_unitario` | custo gravado no momento da venda |
| **Custo do frete** | `fretes.custo_real` | o que a transportadora cobrou. A loja cobrou R$ 2,48 mi e pagou R$ 3,44 mi: o frete grátis é custo |
| **Devoluções** | `devolucoes.valor_reembolsado`, `movimentacoes_estoque.tipo = 'entrada_devolucao'` | reembolso aprovado ou concluído sai da margem; quando o item voltou ao estoque, o custo dele volta |
| **Taxa de pagamento** | `pagamentos.metodo` (dado) × taxa (**premissa**) | Pix 1,0%, cartão 3,5% do valor; boleto R$ 3,50 |
| **Embalagem e atendimento** | **premissa** | R$ 3,00 por pedido pago |
| **Canal de aquisição** | `atribuicoes.canal`, `modelo`, `peso`, `google_campanha_id` | canal do 1º pedido pago no modelo `last_click` (o mesmo do `dim_clientes` da fonte). Busca paga é separada em marca e genérica por `google_campanhas.campanha_marca`. Pedido sem sessão vira "sem rastreio" |
| **Investimento em mídia** | `meta_metricas_diarias.investimento`, `google_metricas_diarias.investimento` | gasto diário das plataformas, no mesmo código de canal da atribuição |
| **Eventos sazonais** | `meta_campanhas` (`estrategia = 'sazonal'`), `google_campanhas` | um mês é sazonal quando uma campanha sazonal da loja rodou pelo menos 7 dias nele. A pausa da prospecção Meta (04 a 24/08/2025) vem do README da fonte |

Mapa de canais (atribuição → este projeto):

| `atribuicoes.canal` | Código | Tem investimento? |
| --- | --- | --- |
| Paid Social | `paid_social` (Meta Ads) | sim |
| Paid Search, campanha de marca | `paid_search_brand` | sim |
| Paid Search, demais campanhas | `paid_search_generic` | sim |
| Cross-network | `performance_max` | sim |
| Paid Shopping | `paid_shopping` | sim |
| Paid Video | `paid_video` (Demand Gen) | sim |
| Organic Search, Direct, Organic Social, Email, Referral, WhatsApp | `organic_search`, `direct`, `organic_social`, `email`, `referral`, `whatsapp` | não: CAC indefinido |
| (pedido sem sessão) | `untracked` | não: CAC indefinido |

## O que é do dataset e o que é premissa

| Do dataset | Premissa (`src/unit_economics/config.py`) | Simulado por este projeto |
| --- | --- | --- |
| pedidos, receita, descontos, frete cobrado | taxa do Pix, do cartão e do boleto | **nada** |
| custo do produto, custo real do frete | custo de embalagem e atendimento por pedido | |
| devoluções, reembolsos, reestoque | horizonte do LTV (12 meses) e modelo de atribuição (`last_click`): escolhas de método, testadas na análise de sensibilidade | |
| canal de aquisição (atribuição) | | |
| investimento diário Meta e Google | | |

A simulação de canal por hash e a regra de investimento como fatia da receita, usadas na versão
com a base da Olist, foram **removidas**: canal e investimento agora vêm do dataset.

## O que está faltando

| Falta | Efeito | Tratamento |
| --- | --- | --- |
| Taxa cobrada pelo gateway | margem sem esse custo seria maior que a real | premissa por método; a sensibilidade mostra que muda o LTV/CAC pago em ±0,03 |
| Custo de embalagem, atendimento e operação por pedido | idem | premissa de R$ 3,00; ±50% muda o LTV/CAC pago em ±0,02 |
| Impostos sobre a venda (Simples, ICMS, PIS/COFINS) | a margem é **antes de impostos** | fora do escopo; declarado no dashboard |
| Custo de influenciadores (cupons `AGULHADEOURO15`, `LINHAEPONTO10`, `TESOURAMAGICA15`), de CRM/e-mail, de agência e de conteúdo orgânico | canais sem investimento registrado têm CAC indefinido, nunca zero | nenhum valor é inventado |
| Canal de ~15% dos novos clientes (pedido sem sessão: bloqueador de anúncios, WhatsApp) | parte deles veio de anúncio, então o CAC por canal pago tende a sair **acima** do real | aparecem como "sem rastreio"; o CAC da loja inteira (todo investimento ÷ todo cliente novo) não depende disso |
| Incrementalidade | CAC aqui é custo médio por cliente atribuído, não custo do cliente que não viria sem o anúncio | a pausa de ago/2025 é lida como sinal; o gabarito do gerador (`data/verdade/`) não é usado |
| Margem antes de 2023-10 dos clientes da base legada | não são tratados como adquiridos | excluídos das coortes |
