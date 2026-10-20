"""Unit-economics dashboard, local and adjustable.

The static page in docs/dashboard is the client version. This one keeps the
knobs: the target LTV/CAC and the channel shown can be moved and the
conclusion watched as it changes, rather than taken on trust. It reads the
same committed tables in reports/, so it needs no database.
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unit_economics import reports  # noqa: E402
from unit_economics.config import CHANNELS, COSTS  # noqa: E402
from unit_economics.metrics import break_even_cac  # noqa: E402

CARBON, IVORY, STEEL, COBALT = "#050505", "#F6F5F0", "#7E8791", "#5B6CFF"

st.set_page_config(page_title="Unit economics por canal", layout="wide")
st.markdown(
    f"""<style>
    .stApp {{ background: {IVORY}; }}
    h1, h2, h3 {{ color: {CARBON}; letter-spacing: -0.02em; font-family: Lato, sans-serif; }}
    [data-testid="stMetricValue"] {{ color: {CARBON}; }}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_data
def load() -> dict[str, pd.DataFrame]:
    return reports.read()


tables = load()
summary, monthly = tables["channel_summary"], tables["channel_monthly"]
h = reports.headline_values(tables)

st.title("Unit economics por canal de aquisição")
st.warning(
    "Dados simulados: a Tecelã Tecidos é uma loja fictícia, gerada a partir do funcionamento de um "
    "e-commerce real. Canal e investimento vêm do dataset; só a taxa de pagamento e o custo por pedido são premissas."
)

target_ratio = st.sidebar.slider("Meta de LTV/CAC", 1.0, 5.0, 3.0, 0.5)
st.sidebar.caption(
    f"Premissas: Pix {COSTS.payment_fee_pix:.1%} · cartão {COSTS.payment_fee_card:.1%} · "
    f"boleto R$ {COSTS.payment_fee_boleto:.2f} · embalagem R$ {COSTS.variable_order_cost:.2f}/pedido"
)

left, middle, right, far = st.columns(4)
left.metric("LTV/CAC, canais pagos (12 meses)", f"{h['paid_ltv_cac']:.2f}x")
middle.metric("CAC pago", f"R$ {h['paid_cac']:,.0f}")
right.metric("Payback pago", f"{h['paid_payback_months']:.0f} meses")
far.metric("Recompra em 12 meses", f"{h['repeat_rate_horizon']:.0%}")

paid = summary[summary["channel"].isin(CHANNELS.paid) & ~summary["small_sample"]].copy()
paid["ceiling"] = paid["ltv"].apply(lambda ltv: break_even_cac(ltv, target_ratio))
paid["clears_target"] = paid["cac"] <= paid["ceiling"]

st.subheader(f"CAC de cada canal pago contra o teto para {target_ratio:g}x")
chart_data = paid.melt(id_vars="label", value_vars=["cac", "ceiling"], var_name="medida", value_name="valor")
chart_data["medida"] = chart_data["medida"].map({"cac": "CAC", "ceiling": f"teto {target_ratio:g}x"})
st.altair_chart(
    alt.Chart(chart_data).mark_bar().encode(
        x=alt.X("valor:Q", title="R$ por cliente"),
        y=alt.Y("label:N", title=None, sort="-x"),
        color=alt.Color("medida:N", scale=alt.Scale(range=[CARBON, COBALT]), legend=alt.Legend(title=None)),
        yOffset="medida:N",
    ).properties(height=280),
    width="stretch",
)
cleared = paid.loc[paid["clears_target"], "label"].tolist()
st.caption(f"Abaixo do teto: {', '.join(cleared) if cleared else 'nenhum canal pago'}.")

st.dataframe(
    summary[["label", "spend", "new_customers", "cac", "cac_share_of_first_margin", "ltv",
             "ltv_cac_ratio", "payback_months", "small_sample"]],
    width="stretch", hide_index=True,
)
st.caption("Canais sem investimento registrado mostram CAC vazio: indefinido, não zero.")

st.subheader("CAC por mês")
labels = summary.set_index("channel")["label"]
channel = st.selectbox("Canal", ["paid_total", *CHANNELS.paid], format_func=lambda c: labels.get(c, c))
trend = monthly[(monthly["channel"] == channel) & monthly["cac"].notna()]
st.altair_chart(
    alt.Chart(trend).mark_line(point=True, color=COBALT).encode(
        x=alt.X("month:N", title=None),
        y=alt.Y("cac:Q", title="CAC (R$)"),
        tooltip=["month", "spend", "new_customers", "cac", "events", "small_sample"],
    ).properties(height=280),
    width="stretch",
)
