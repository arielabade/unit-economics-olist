"""Unit-economics dashboard.

Built so the assumptions are adjustable in the interface: the take rate and the
target LTV/CAC drive everything downstream, and a reviewer should be able to
move them and watch the conclusion change rather than take it on trust.
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from unit_economics.config import CHANNELS, MARGIN  # noqa: E402
from unit_economics.metrics import break_even_cac  # noqa: E402
from unit_economics.summary import channel_summary, repeat_purchase_rate  # noqa: E402

CARBON, IVORY, STEEL, COBALT = "#050505", "#F6F5F0", "#7E8791", "#5B6CFF"
PROCESSED = ROOT / "data" / "processed"

st.set_page_config(page_title="Unit economics by channel", layout="wide")
st.markdown(
    f"""<style>
    .stApp {{ background: {IVORY}; }}
    h1, h2, h3 {{ color: {CARBON}; letter-spacing: -0.02em; }}
    [data-testid="stMetricValue"] {{ color: {CARBON}; }}
    </style>""",
    unsafe_allow_html=True,
)


@st.cache_data
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not (PROCESSED / "channel_monthly.parquet").exists():
        st.error("Processed data missing. Run `python -m unit_economics.pipeline` first.")
        st.stop()
    return (
        pd.read_parquet(PROCESSED / "channel_monthly.parquet"),
        pd.read_parquet(PROCESSED / "customer_economics.parquet"),
    )


channel_monthly, customer_economics = load()

st.title("Unit economics by acquisition channel")
st.caption(
    "Olist marketplace, 2017-02 to 2018-08. Order and revenue data are real. "
    "Acquisition channel and media spend are SIMULATED — see the README."
)

target_ratio = st.sidebar.slider("Target LTV/CAC", 1.0, 5.0, 3.0, 0.5)
st.sidebar.caption(
    f"Take rate {MARGIN.take_rate:.0%} · payment {MARGIN.psp_fee_rate:.1%} · "
    f"support R${MARGIN.variable_support_cost:.2f}/order"
)

summary = channel_summary(channel_monthly)
repeat_rate = repeat_purchase_rate(customer_economics)

left, middle, right = st.columns(3)
left.metric("Customers", f"{summary['new_customers'].sum():,}")
middle.metric("Repeat purchase rate", f"{repeat_rate:.2%}")
right.metric(
    "Blended margin per customer",
    f"R$ {customer_economics['contribution_margin'].sum() / len(customer_economics):.2f}",
)

st.subheader("The constraint")
st.markdown(
    f"**{1 - repeat_rate:.2%} of customers buy exactly once.** There is no second order to recover "
    "acquisition cost from, so CAC has to clear on the first purchase. That makes the first-order "
    "contribution margin the hard ceiling for what any paid channel can spend."
)

paid = summary[summary["paid"]].copy()
paid["ceiling"] = paid["margin_per_customer"].apply(lambda m: break_even_cac(m, target_ratio))
paid["clears_target"] = paid["cac"] <= paid["ceiling"]

st.subheader(f"Paid channels against a {target_ratio:g}x target")
chart_data = paid.melt(
    id_vars="channel", value_vars=["cac", "ceiling"], var_name="measure", value_name="value"
)
st.altair_chart(
    alt.Chart(chart_data)
    .mark_bar()
    .encode(
        x=alt.X("value:Q", title="BRL per customer"),
        y=alt.Y("channel:N", title=None, sort="-x"),
        color=alt.Color(
            "measure:N",
            scale=alt.Scale(domain=["cac", "ceiling"], range=[COBALT, STEEL]),
            legend=alt.Legend(title=None),
        ),
        yOffset="measure:N",
    )
    .properties(height=220),
    use_container_width=True,
)

st.dataframe(
    summary[
        ["channel", "paid", "new_customers", "margin_per_customer", "cac",
         "ltv_cac_ratio", "acquisition_share_of_first_margin", "break_even_cac"]
    ],
    use_container_width=True,
    hide_index=True,
)
st.caption(
    "Unpaid channels show no CAC because they have no media line. "
    "That is different from a CAC of zero, which would make organic look like the best channel in the table."
)

st.subheader("CAC over time")
trend = channel_monthly[channel_monthly["channel"].isin(CHANNELS.paid_channels)]
st.altair_chart(
    alt.Chart(trend)
    .mark_line(point=True)
    .encode(
        x=alt.X("month:N", title=None),
        y=alt.Y("cac:Q", title="CAC (BRL)"),
        color=alt.Color("channel:N", scale=alt.Scale(scheme="category10"), legend=alt.Legend(title=None)),
    )
    .properties(height=280),
    use_container_width=True,
)
