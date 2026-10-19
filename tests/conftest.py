"""A hand-built copy of the ecommerce tables, small enough to check by hand.

Every row exists to exercise one rule of the staging, and the expected
numbers in the tests are worked out from these rows in the comments there.

People
    1, 2   two accounts of the same person (same CPF)
    3      legacy customer, imported from the previous platform
    4      a staff test account
    5      a company (no CPF): one cancelled order, then a paid one with no session
    6      one paid order with a session but no attribution row (-> direct)
    7      one paid order credited to generic Google Search
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _write(raw: Path, name: str, rows: list[dict], columns: list[str]) -> None:
    frame = pd.DataFrame(rows, columns=columns)
    for column in frame.columns:
        if column.endswith("_id"):
            frame[column] = pd.array(frame[column], dtype="Int64")
    frame.to_parquet(raw / f"{name}.parquet", index=False)


def build_raw(raw: Path, extra_orders: int = 0) -> Path:
    """Write the fixture tables into ``raw``.

    ``extra_orders`` adds that many more people acquired by Meta in January
    2024, without touching any spend row: the anti-circularity test uses it.
    """
    raw.mkdir(parents=True, exist_ok=True)

    clientes = [
        dict(cliente_id=1, tipo_cliente="hobby", tipo_pessoa="PF", cadastrado_em=_ts("2024-01-01 10:00"),
             origem_cadastro="checkout", cpf_hash="cpf-a", conta_teste=0),
        dict(cliente_id=2, tipo_cliente="hobby", tipo_pessoa="PF", cadastrado_em=_ts("2024-03-01 10:00"),
             origem_cadastro="checkout", cpf_hash="cpf-a", conta_teste=0),
        dict(cliente_id=3, tipo_cliente="atelie", tipo_pessoa="PF", cadastrado_em=_ts("2022-05-01 10:00"),
             origem_cadastro="importacao_legado", cpf_hash="cpf-legacy", conta_teste=0),
        dict(cliente_id=4, tipo_cliente="hobby", tipo_pessoa="PF", cadastrado_em=_ts("2023-09-20 10:00"),
             origem_cadastro="checkout", cpf_hash="cpf-staff", conta_teste=1),
        dict(cliente_id=5, tipo_cliente="confeccao", tipo_pessoa="PJ", cadastrado_em=_ts("2024-01-19 10:00"),
             origem_cadastro="checkout", cpf_hash=None, conta_teste=0),
        dict(cliente_id=6, tipo_cliente="costureira", tipo_pessoa="PF", cadastrado_em=_ts("2024-01-24 10:00"),
             origem_cadastro="checkout", cpf_hash="cpf-b", conta_teste=0),
        dict(cliente_id=7, tipo_cliente="hobby", tipo_pessoa="PF", cadastrado_em=_ts("2024-01-27 10:00"),
             origem_cadastro="checkout", cpf_hash="cpf-c", conta_teste=0),
    ]

    # pedido_id, cliente, sessão, status, criado_em, subtotal, desconto, frete, teste
    pedidos_spec = [
        (1, 1, 11, "entregue", "2024-01-10 09:00", 190.0, 10.0, 20.0, 0),
        (2, 2, 12, "devolvido", "2024-03-05 09:00", 100.0, 0.0, 0.0, 0),
        (3, 3, 13, "entregue", "2024-01-15 09:00", 120.0, 0.0, 0.0, 0),
        (4, 4, 14, "pago", "2024-01-16 09:00", 50.0, 49.0, 0.0, 1),
        (5, 5, 15, "cancelado", "2024-01-20 09:00", 300.0, 0.0, 0.0, 0),
        (6, 5, None, "entregue", "2024-02-01 09:00", 400.0, 0.0, 0.0, 0),
        (7, 6, 17, "entregue", "2024-01-25 09:00", 80.0, 0.0, 0.0, 0),
        (8, 7, 18, "entregue", "2024-01-28 09:00", 150.0, 0.0, 0.0, 0),
    ]
    itens_spec = [  # item, pedido, quantidade, custo_unitario
        (1, 1, 2.0, 30.0), (2, 2, 2.0, 20.0), (3, 3, 1.0, 50.0), (4, 4, 1.0, 10.0),
        (5, 5, 1.0, 100.0), (6, 6, 4.0, 50.0), (7, 7, 1.0, 30.0), (8, 8, 1.0, 20.0),
    ]
    fretes_spec = {1: 25.0, 2: 10.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 30.0, 7: 5.0, 8: 10.0}
    metodo = {1: "pix", 2: "cartao_credito", 3: "pix", 4: "pix", 5: "cartao_credito", 6: "boleto", 7: "pix", 8: "pix"}
    # last_click and first_click credit per order: (canal, meta_campanha, google_campanha)
    last_click = {1: ("Paid Social", 1, None), 2: ("Email", None, None), 3: ("Paid Search", None, 10),
                  5: ("Paid Social", 1, None), 8: ("Paid Search", None, 11)}
    first_click = {1: ("Organic Search", None, None), 2: ("Email", None, None), 3: ("Paid Search", None, 10),
                   5: ("Paid Social", 1, None), 8: ("Paid Search", None, 11)}

    next_id = 100
    for k in range(extra_orders):
        next_id += 1
        clientes.append(dict(cliente_id=next_id, tipo_cliente="hobby", tipo_pessoa="PF",
                             cadastrado_em=_ts("2024-01-29 10:00"), origem_cadastro="checkout",
                             cpf_hash=f"cpf-extra-{k}", conta_teste=0))
        pedidos_spec.append((next_id, next_id, 1000 + next_id, "entregue", "2024-01-29 09:00", 100.0, 0.0, 0.0, 0))
        itens_spec.append((next_id, next_id, 1.0, 40.0))
        fretes_spec[next_id] = 10.0
        metodo[next_id] = "pix"
        last_click[next_id] = ("Paid Social", 1, None)
        first_click[next_id] = ("Paid Social", 1, None)

    _write(raw, "clientes", clientes, list(clientes[0]))
    _write(raw, "cupons", [dict(cupom_id=1, codigo="BEMVINDA10", tipo_desconto="percentual", canal="primeira_compra",
                                valido_de=date(2022, 1, 1), valido_ate=None)],
           ["cupom_id", "codigo", "tipo_desconto", "canal", "valido_de", "valido_ate"])
    _write(raw, "pedidos", [
        dict(pedido_id=p, cliente_id=c, sessao_id=s, cupom_id=None, canal_venda="site", status=st,
             criado_em=_ts(ts), subtotal=sub, desconto=d, frete=f, total=sub - d + f, pedido_teste=t)
        for p, c, s, st, ts, sub, d, f, t in pedidos_spec
    ], ["pedido_id", "cliente_id", "sessao_id", "cupom_id", "canal_venda", "status", "criado_em",
        "subtotal", "desconto", "frete", "total", "pedido_teste"])
    _write(raw, "itens_pedido", [
        dict(item_pedido_id=i, pedido_id=p, variante_id=1, quantidade=q, preco_unitario=0.0,
             custo_unitario=c, total_item=0.0)
        for i, p, q, c in itens_spec
    ], ["item_pedido_id", "pedido_id", "variante_id", "quantidade", "preco_unitario", "custo_unitario", "total_item"])
    totals = {p: sub - d + f for p, _, _, _, _, sub, d, f, _ in pedidos_spec}
    paid_status = {p: st for p, _, _, st, *_ in pedidos_spec}
    pagamentos = []
    for p, total in totals.items():
        if metodo[p] == "cartao_credito" and paid_status[p] == "cancelado":
            pagamentos.append(dict(pagamento_id=p, pedido_id=p, tentativa=1, metodo="cartao_credito",
                                   parcelas=1, valor=total, status="recusado"))
            continue
        # A refused attempt before the approved one costs nothing.
        if p == 7:
            pagamentos.append(dict(pagamento_id=900, pedido_id=p, tentativa=1, metodo="cartao_credito",
                                   parcelas=1, valor=total, status="recusado"))
        pagamentos.append(dict(pagamento_id=p, pedido_id=p, tentativa=2 if p == 7 else 1, metodo=metodo[p],
                               parcelas=1, valor=total, status="aprovado"))
    _write(raw, "pagamentos", pagamentos,
           ["pagamento_id", "pedido_id", "tentativa", "metodo", "parcelas", "valor", "status"])
    _write(raw, "fretes", [dict(frete_id=p, pedido_id=p, valor_cobrado=0.0, custo_real=c, frete_gratis=0)
                           for p, c in fretes_spec.items()],
           ["frete_id", "pedido_id", "valor_cobrado", "custo_real", "frete_gratis"])
    _write(raw, "devolucoes", [
        # Order 2: R$30 refunded, one metre back in stock (R$20 of cost recovered).
        dict(devolucao_id=1, pedido_id=2, item_pedido_id=2, motivo="desistencia", quantidade=1.0,
             valor_reembolsado=30.0, status="concluida"),
        # Refused: nothing is refunded.
        dict(devolucao_id=2, pedido_id=7, item_pedido_id=7, motivo="desistencia", quantidade=1.0,
             valor_reembolsado=0.0, status="recusada"),
    ], ["devolucao_id", "pedido_id", "item_pedido_id", "motivo", "quantidade", "valor_reembolsado", "status"])
    _write(raw, "movimentacoes_estoque", [
        dict(movimentacao_id=1, tipo="entrada_devolucao", quantidade=1.0, pedido_id=2, devolucao_id=1),
        dict(movimentacao_id=2, tipo="saida_venda", quantidade=-2.0, pedido_id=1, devolucao_id=None),
    ], ["movimentacao_id", "tipo", "quantidade", "pedido_id", "devolucao_id"])

    atribuicoes, aid = [], 0
    for model, credit in (("last_click", last_click), ("first_click", first_click)):
        for p, (canal, meta, google) in credit.items():
            aid += 1
            atribuicoes.append(dict(atribuicao_id=aid, pedido_id=p, modelo=model, sessao_id=10 + p, posicao=1,
                                    canal=canal, meta_campanha_id=meta, google_campanha_id=google,
                                    peso=1.0, receita_atribuida=totals[p]))
    _write(raw, "atribuicoes", atribuicoes,
           ["atribuicao_id", "pedido_id", "modelo", "sessao_id", "posicao", "canal",
            "meta_campanha_id", "google_campanha_id", "peso", "receita_atribuida"])

    _write(raw, "meta_campanhas", [
        dict(campanha_id=1, nome="[PROSP] Lookalike", objetivo="OUTCOME_SALES", estrategia="prospeccao",
             inicio=date(2023, 10, 1), fim=None),
        dict(campanha_id=2, nome="[SAZ] Black Friday 2024", objetivo="OUTCOME_SALES", estrategia="sazonal",
             inicio=date(2024, 11, 8), fim=date(2024, 12, 3)),
    ], ["campanha_id", "nome", "objetivo", "estrategia", "inicio", "fim"])
    _write(raw, "meta_conjuntos", [dict(conjunto_id=1, campanha_id=1), dict(conjunto_id=2, campanha_id=2)],
           ["conjunto_id", "campanha_id"])
    _write(raw, "meta_anuncios", [dict(anuncio_id=100, conjunto_id=1), dict(anuncio_id=101, conjunto_id=2)],
           ["anuncio_id", "conjunto_id"])
    _write(raw, "meta_metricas_diarias", [
        dict(data=date(2024, 1, 5), anuncio_id=100, investimento=150.0, impressoes=1000, cliques_link=10,
             compras=3, valor_compras=600.0),
        dict(data=date(2024, 2, 10), anuncio_id=100, investimento=50.0, impressoes=400, cliques_link=4,
             compras=1, valor_compras=100.0),
        dict(data=date(2024, 11, 15), anuncio_id=101, investimento=70.0, impressoes=800, cliques_link=8,
             compras=1, valor_compras=90.0),
    ], ["data", "anuncio_id", "investimento", "impressoes", "cliques_link", "compras", "valor_compras"])
    _write(raw, "google_campanhas", [
        dict(campanha_id=10, nome="Search | Marca", tipo_canal="SEARCH", campanha_marca=1,
             inicio=date(2023, 10, 1), fim=None),
        dict(campanha_id=11, nome="Search | Tecidos por Metro", tipo_canal="SEARCH", campanha_marca=0,
             inicio=date(2023, 10, 1), fim=None),
    ], ["campanha_id", "nome", "tipo_canal", "campanha_marca", "inicio", "fim"])
    _write(raw, "google_grupos_anuncio", [dict(grupo_id=200, campanha_id=10), dict(grupo_id=201, campanha_id=11)],
           ["grupo_id", "campanha_id"])
    _write(raw, "google_metricas_diarias", [
        dict(data=date(2024, 1, 10), grupo_id=200, investimento=20.0, impressoes=100, cliques=5,
             conversoes=1.0, valor_conversao=120.0),
        dict(data=date(2024, 1, 12), grupo_id=201, investimento=80.0, impressoes=300, cliques=9,
             conversoes=1.0, valor_conversao=150.0),
    ], ["data", "grupo_id", "investimento", "impressoes", "cliques", "conversoes", "valor_conversao"])
    return raw


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    return build_raw(tmp_path / "raw")
