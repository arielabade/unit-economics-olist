# Notas para entrevista — unit-economics-olist

Documento interno. Não faz parte da documentação pública do projeto. Os números citados aqui vêm de
`reports/headline.csv`; se mudarem, regere com `python -m unit_economics.reports`.

---

## As 3 decisões técnicas mais importantes

### 1. Margem de varejo sobre custos reais, não sobre comissão

**O que fiz:** a fonte passou a ser uma loja própria (Tecelã Tecidos, dados simulados do repositório
`ecommerce`), não um marketplace. A margem de contribuição de cada pedido é venda − custo do produto − frete
pago à transportadora − reembolsos + custo de itens que voltaram ao estoque − taxa de pagamento − embalagem.

**Por quê:** varejo paga pela mercadoria e pelo frete. A fórmula de take rate da versão Olist estaria errada
aqui por ordem de grandeza. Tudo que o dataset registra é usado; só taxa de pagamento e custo por pedido são
premissas, e a sensibilidade mostra que elas mexem no LTV/CAC pago em no máximo 0,06.

**Achado que veio disso:** o frete grátis é custo. A loja pagou R$ 0,95 mi a mais às transportadoras do que
cobrou dos clientes (2,5% da receita).

### 2. Canal e investimento lidos, nunca derivados — a trava anti-circularidade continua

**O que fiz:** canal = atribuição do 1º pedido pago (last click, a mesma regra do `dim_clientes` da fonte),
com busca do Google separada em marca e genérica. Investimento = gasto diário de Meta e Google no mesmo código
de canal. A simulação por hash e o orçamento como fatia da receita foram removidos.

**Como protegi:** um teste roda o SQL real duas vezes, com 9 clientes a mais adquiridos pela Meta: o
investimento da Meta não pode mudar e o CAC tem que cair 10 vezes. Se alguém fizer o gasto depender de
aquisições, o CAC vira constante por construção e o teste quebra.

### 3. Indefinido continua indefinido, e taxa é razão de somas

Canal sem investimento registrado (orgânico, direto, e-mail, sem rastreio) tem CAC nulo, não zero. Toda taxa
é total ÷ total: um mês fraco com 20 clientes não pesa o mesmo que a Black Friday. O LTV só existe para coortes
observadas pelos 12 meses inteiros, e o LTV/CAC usa o investimento dessas mesmas coortes.

---

## 5 perguntas prováveis, com resposta

### 1. "Os dados são simulados. Que valor isso tem?"

O framework é o entregável. A diferença em relação à versão Olist é que agora nada é simulado por mim: canal e
investimento vêm do dataset, que é determinístico (seed fixa) e conferido na ingestão por contagem de linhas e
somas de controle. O projeto reconcilia ao centavo com os marts do dbt da própria fonte. O dashboard e o
README dizem que os dados são simulados em destaque.

### 2. "LTV/CAC de 1,47 é bom?"

Está acima do empate e abaixo do 3x de planejamento. O mais útil é o payback: a mídia paga leva 6 meses para
se pagar, porque o primeiro pedido deixa R$ 86 de margem contra R$ 209 de CAC. Quem paga a aquisição é a
recompra: 58% voltam em 12 meses.

### 3. "Então corta a Meta?"

Não pelo último clique. A Meta é 58% da verba e só empata em 12 meses (1,00x), mas na pausa de agosto/2025 a
loja perdeu 34% dos clientes novos de julho para agosto (4% no mesmo período de 2024), e os outros canais
perderam mais clientes (313) do que a própria Meta (174). Isso sugere que ela gera demanda que busca de marca e
orgânico recolhem. O próximo passo é um holdout por região e usar CAC incremental como teto.

### 4. "Qual premissa mais muda a conclusão?"

O horizonte de recompra contado no LTV: 6 meses dá 1,04x, 24 meses dá 2,11x. Como coortes antigas eram mais
baratas, também meço com as coortes fixas (1,65x em 12 meses → 2,11x em 24). Modelo de atribuição vem em
segundo (1,21x a 1,47x). Custos estimados quase não mexem.

### 5. "Como você sabe que os dados estão certos?"

Três camadas. Na ingestão, contagem de linhas e somas de controle de cada tabela contra o gerador com seed
fixa. Na modelagem, as armadilhas do dataset tratadas: contas duplicadas pelo CPF, pedidos de teste, clientes
legados que não são "novos", pedidos sem rastreio que não são redistribuídos. Nos testes, o SQL real roda numa
cópia montada à mão das tabelas da fonte, com cada regra coberta, e README e dashboard são testados contra os
mesmos `reports/`.

---

## Números para ter na ponta da língua

| | |
| --- | --- |
| Janela | 2023-10 a 2026-09 (36 meses) |
| Receita / margem de contribuição | R$ 38,24 mi / R$ 16,38 mi (42,8%) |
| Investimento em mídia | R$ 4,24 mi |
| Clientes novos / CAC da loja | 44.532 / R$ 95 |
| CAC pago / LTV 12 meses pago | R$ 209 / R$ 297 |
| LTV/CAC pago / payback | 1,47x / 6 meses |
| Meta: verba / LTV/CAC / payback | 58% / 1,00x / 14 meses |
| CAC pago ano 1 → ano 3 | R$ 170 → R$ 222 (verba +48%, clientes pagos +13%) |
| Recompra em 90 dias / 12 meses | 40% / 58% |
