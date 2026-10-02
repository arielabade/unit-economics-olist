# Notas para entrevista — unit-economics-olist

Documento interno. Não faz parte da documentação pública do projeto.

---

## As 3 decisões técnicas mais importantes

### 1. Calcular margem sobre a comissão, não sobre o GMV

**O que fiz:** modelei a margem de contribuição como `GMV × take_rate − GMV × taxa_de_pagamento −
custo_de_suporte`, em vez de aplicar um percentual de margem sobre o GMV.

**Por quê:** o Olist é um marketplace. Ele não fica com os R$ 141 de um pedido, fica com a comissão
sobre ele. Tratar marketplace como varejista é o erro mais comum nessa análise e infla a economia do
negócio por aproximadamente o inverso do take rate — no caso, cerca de 6,7x. Com GMV médio de
R$ 141,43 por cliente, a margem real é R$ 16,13, não R$ 141.

**O trade-off:** o take rate não é publicado pelo Olist. Troquei um erro de ordem de grandeza por uma
premissa explícita e documentada. Por isso coloquei a tabela de sensibilidade no README: abaixo de
~12% de take rate, paid search e paid social deixam de se pagar.

### 2. Orçamento de mídia atrelado à receita do mês anterior, nunca às aquisições do mês

**O que fiz:** o gasto simulado é um percentual declarado da receita líquida do **mês anterior**.

**Por quê:** a tentação é simular o gasto como `clientes_adquiridos × CPA_alvo`. Se eu fizesse isso,
o CAC calculado seria exatamente o CPA_alvo por construção — o modelo devolveria a premissa que
recebeu, e a análise inteira seria circular. O lag de um mês também é como orçamento se define na
prática: você planeja com base no resultado do período fechado.

**Como protegi:** há um teste (`test_spend_is_independent_of_acquisitions`) que trava a assinatura da
função. Se alguém algum dia fizer a simulação de gasto enxergar o número de clientes, o teste quebra.

### 3. Manter "indefinido" como indefinido, em vez de virar zero

**O que fiz:** canais sem linha de mídia (orgânico, direto, referral) recebem `None` como gasto e
ficam com CAC nulo. Canal pago que gastou R$ 0,00 num mês recebe CAC igual a 0,00.

**Por quê:** são coisas diferentes. Se orgânico reportar CAC zero, ele vira o canal de melhor
performance em qualquer tabela ordenada por LTV/CAC — e alguém vai usar isso para justificar cortar
mídia paga. "Não tem CAC" e "tem CAC zero" levam a decisões opostas.

**Detalhe que apareceu no teste:** o pandas converte `None` em `NaN` numa coluna float, então o teste
não pode afirmar `is None`. Reescrevi para afirmar o invariante que realmente importa: `pd.isna(cac)`
**e** `cac != 0`.

---

## 5 perguntas prováveis, com resposta

### 1. "Você simulou o gasto de mídia. Então que valor isso tem?"

Separo os dois tipos de resultado, e isso está no README.

O achado de retenção — **97,00% dos clientes compram uma única vez** — vem de dado real do Olist e não
depende de nenhuma simulação. É ele que governa a tese: não existe segunda compra para recuperar o
CAC, então o CAC precisa fechar no primeiro pedido, e a margem do primeiro pedido vira teto duro.

Os números por canal demonstram o framework de medição. Nunca afirmo que são a performance real do
Olist, e deixo isso explícito no README, na docstring do módulo e no dashboard.

Se a pergunta for "por que não usou dado real de canal?", a resposta é que o Olist não publica. A
alternativa seria inventar e não declarar, que é pior.

### 2. "Por que DuckDB e SQL em vez de pandas?"

Três razões. A primeira é que o trabalho é junção e agregação sobre ~112 mil linhas, que é exatamente
o que SQL faz bem. A segunda é revisabilidade: um analista de negócio consegue ler
`02_customer_economics.sql` e conferir a fórmula de margem sem saber Python — e a fórmula de margem é
a parte que mais importa auditar. A terceira é que DuckDB roda in-process, então quem clonar o repo
reproduz tudo sem subir warehouse nenhum.

Detalhe de implementação que vale citar: o DuckDB não aceita parâmetro preparado dentro de
`CREATE VIEW`. Em vez de formatar string no SQL a partir do Python, publico as premissas como
variáveis de sessão (`SET VARIABLE`) e leio com `getvariable()`. Os arquivos `.sql` continuam
parametrizados e legíveis sozinhos.

### 3. "Esse LTV está certo? O cliente adquirido em agosto de 2018 teve quanto tempo para voltar?"

Está certo como **LTV observado**, e essa é a limitação. O dataset termina em 2018-08, então coortes
recentes são estruturalmente censuradas: tiveram menos tempo de janela e o LTV observado delas é
enviesado para baixo.

Isso importa menos aqui do que importaria em outro negócio, porque com 97% de compra única não há
muito o que observar depois do primeiro pedido. Mas é uma limitação real e está declarada no README.
É exatamente o problema que o projeto `clv-cohort-prediction` resolve, com BG/NBD e avaliação em
holdout.

### 4. "LTV/CAC de 1,4 é bom ou ruim?"

Está acima do break-even e bem abaixo do que se costuma planejar. O 3x é convenção de mercado, não
lei — mas serve de referência, e nessa convenção o CAC teto cairia de R$ 16,13 para R$ 5,38.

O número mais útil para a conversa não é o ratio, é este: paid search consome **71,4% da margem
inteira do primeiro pedido** para adquirir o cliente. Como ele não volta, sobra 28,6% de margem por
cliente adquirido para pagar todo o resto da operação.

A recomendação que tiro disso tem ordem: primeiro aumentar a margem por pedido (take rate, ticket
médio, custo de servir), depois mexer no orçamento. Escalar mídia com 1,4x só multiplica um problema
de margem.

E uma ressalva honesta: email/CRM dá 4,28x, mas CRM frequentemente captura demanda que já existia. O
número dele é o que eu testaria por incrementalidade antes de realocar verba.

### 5. "Como você sabe que os dados estão certos?"

Três camadas.

Na ingestão, `verify()` confere a contagem de linhas de cada arquivo contra os números publicados do
dataset. Se o mirror for truncado ou trocado, o run falha em vez de mudar o resultado em silêncio.

Na modelagem, a decisão de identidade: o Olist tem `customer_id` (um por **pedido**) e
`customer_unique_id` (um por **pessoa**). São 99.441 contra 96.096. Quem agrupa por `customer_id`
conclui que a taxa de recompra é zero, porque cada pedido vira um cliente novo. Essa é a pegadinha
clássica do dataset e é o que eu checo primeiro em qualquer base transacional.

Nos testes, 23 casos cobrindo as fórmulas, a reprodutibilidade da simulação e a trava anti-
circularidade. Incluindo um teste de que margem pode ser **negativa** em pedidos muito pequenos — um
pedido de R$ 10 não cobre o custo fixo de suporte, e o modelo precisa dizer isso em vez de truncar em
zero.

---

## Números para ter na ponta da língua

| | |
| --- | --- |
| Clientes com pedido entregue | 93.358 |
| Compra única | 97,00% |
| GMV médio por cliente | R$ 141,43 |
| Margem de contribuição por cliente | R$ 16,13 |
| CAC teto no break-even | R$ 16,13 |
| CAC teto a 3x | R$ 5,38 |
| LTV/CAC agregado dos canais pagos | 1,59 |
| Janela de análise | 2017-02 a 2018-08 |
