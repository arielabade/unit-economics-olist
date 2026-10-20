"""Static client dashboard: ``docs/dashboard/index.html``, served by GitHub Pages.

Built from the same committed tables as the README (``reports/``), with
Plotly figures serialised into the page and plotly.js shipped next to it, so
it opens from any static host with no server and no CDN. The Streamlit app
remains the local, adjustable version.

The page reads top to bottom as a client conversation: summary, how the
months moved, how the channels compare, unit economics and the CAC ceiling,
how sensitive the answer is, and what to do. Every chart title states the
finding. Method details sit in a collapsible block at the end.

Run with ``python -m unit_economics.dashboard`` after ``unit_economics.reports``.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs_version
from plotly.utils import PlotlyJSONEncoder

from . import reports
from .config import CHANNELS, ROOT

OUT = ROOT / "docs" / "dashboard"

# ABADE identity
CARBON, IVORY, COBALT = "#050505", "#F6F5F0", "#5B6CFF"
INK_2, LINE, MUTED = "#5C646D", "#E2E0D8", "#B9BEC6"
LOSS, GAIN = "#C8384F", "#1F8F6A"
SYMBOL_VIEWBOX = "0 0 127.566 100"

PAID_ORDER = list(CHANNELS.paid)
NO_MEDIA = '<span class="na">sem mídia</span>'
UNDEFINED = '<span class="na">indefinido</span>'


# --- formatting (pt-BR) -------------------------------------------------------

def _num(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def brl(value, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"R$ {_num(value, digits)}"


def brl_short(value: float) -> str:
    if abs(value) >= 1e6:
        return f"R$ {_num(value / 1e6, 2)} mi"
    if abs(value) >= 1e3:
        return f"R$ {_num(value / 1e3, 0)} mil"
    return brl(value)


def pct(value, digits: int = 0, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "—"
    text = _num(value * 100, digits) + "%"
    return ("+" + text) if signed and value > 0 else text


def times(value, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return _num(value, digits) + "x"


def months(value) -> str:
    if value is None or pd.isna(value):
        return "não pagou no período"
    n = int(value)
    return "no mês da compra" if n == 1 else f"{n} meses"


# --- figures --------------------------------------------------------------------

def _layout(fig: go.Figure, height: int = 380, **kw) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=12, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Lato, Helvetica, Arial, sans-serif", color=CARBON, size=13),
        hoverlabel=dict(font=dict(family="Lato, sans-serif")),
        legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=12)),
        separators=",.",
        **kw,
    )
    fig.update_xaxes(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE, automargin=True)
    fig.update_yaxes(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE, automargin=True)
    return fig


def fig_monthly(monthly: pd.DataFrame, events: pd.DataFrame) -> go.Figure:
    paid = monthly[monthly["channel"] == "paid_total"].sort_values("month")
    store = monthly[monthly["channel"] == "all"].sort_values("month").set_index("month")
    ev = events.set_index("month")["events"]
    hover_events = [ev.get(m, "") for m in paid["month"]]
    fig = go.Figure()
    fig.add_bar(x=paid["month"], y=paid["spend"], name="Investimento em mídia", marker_color=MUTED,
                customdata=hover_events,
                hovertemplate="%{x}<br>Investimento: R$ %{y:,.0f}<br>%{customdata}<extra></extra>")
    fig.add_scatter(x=paid["month"], y=paid["new_customers"], name="Novos clientes via mídia paga",
                    yaxis="y2", mode="lines+markers", line=dict(color=COBALT, width=3),
                    hovertemplate="%{x}<br>Novos clientes pagos: %{y:,.0f}<extra></extra>")
    fig.add_scatter(x=store.index, y=store["new_customers"], name="Novos clientes, todos os canais",
                    yaxis="y2", mode="lines", line=dict(color=CARBON, width=1.5, dash="dot"),
                    hovertemplate="%{x}<br>Novos clientes (loja): %{y:,.0f}<extra></extra>")
    seasonal = paid[paid["month"].isin(ev.index)]
    fig.add_scatter(x=seasonal["month"], y=[0] * len(seasonal), mode="markers", name="Mês com campanha sazonal",
                    marker=dict(symbol="triangle-up", size=11, color=COBALT),
                    customdata=[ev[m] for m in seasonal["month"]],
                    hovertemplate="%{x}: %{customdata}<extra></extra>")
    _layout(fig, 400, barmode="overlay",
            yaxis=dict(title="Investimento (R$)", tickprefix="R$ ", tickformat=",.0f"),
            yaxis2=dict(title="Novos clientes", overlaying="y", side="right", showgrid=False,
                        range=[0, store["new_customers"].max() * 1.12], tickformat=",.0f"),
            hovermode="x unified")
    return fig


def fig_cac_by_channel(monthly: pd.DataFrame) -> go.Figure:
    """Monthly CAC per paid channel, one selectable line each."""
    fig = go.Figure()
    shown = ["paid_total", "paid_social", "paid_search_generic", "performance_max", "paid_search_brand"]
    colors = {"paid_total": COBALT, "paid_social": LOSS, "paid_search_generic": "#B07A12",
              "performance_max": GAIN, "paid_search_brand": INK_2}
    for channel in shown:
        part = monthly[(monthly["channel"] == channel) & monthly["cac"].notna()].sort_values("month")
        small = part["small_sample"].astype(bool)
        fig.add_scatter(
            x=part["month"], y=part["cac"], name=_label(channel), mode="lines+markers",
            line=dict(color=colors[channel], width=3 if channel == "paid_total" else 1.8),
            marker=dict(size=[9 if s else 5 for s in small], symbol=["circle-open" if s else "circle" for s in small]),
            customdata=part[["new_customers", "spend"]].values,
            hovertemplate="%{x}<br>CAC: R$ %{y:,.0f}<br>%{customdata[0]:,.0f} clientes · R$ %{customdata[1]:,.0f}"
                          f"<extra>{_label(channel)}</extra>",
            visible=True if channel in ("paid_total", "paid_social", "paid_search_generic") else "legendonly",
        )
    _layout(fig, 380, yaxis=dict(title="CAC (R$)", tickprefix="R$ ", tickformat=",.0f", rangemode="tozero"))
    return fig


def fig_channels(summary: pd.DataFrame) -> go.Figure:
    paid = summary[summary["channel"].isin(PAID_ORDER) & ~summary["small_sample"].astype(bool)]
    paid = paid.sort_values("ltv_cac_ratio")
    total_spend = summary.set_index("channel").loc["paid_total", "spend"]
    colors = [LOSS if r < 1.2 else COBALT if r >= 3 else INK_2 for r in paid["ltv_cac_ratio"]]
    fig = go.Figure(go.Bar(
        x=paid["ltv_cac_ratio"], y=paid["label"], orientation="h", marker_color=colors,
        text=[f"{times(r)} · {pct(s / total_spend)} da verba" for r, s in zip(paid["ltv_cac_ratio"], paid["spend"])],
        customdata=paid[["cac", "ltv"]].values,
        textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br>LTV/CAC 12 meses: %{x:.2f}x<br>CAC R$ %{customdata[0]:,.0f} · LTV R$ %{customdata[1]:,.0f}<extra></extra>",
    ))
    for value, name in ((1, "empata"), (3, "3x")):
        fig.add_vline(x=value, line=dict(color=INK_2, dash="dash", width=1),
                      annotation_text=name, annotation_position="top", annotation_font_size=11)
    _layout(fig, 340, xaxis=dict(title="Margem de 12 meses ÷ CAC", ticksuffix="x",
                                 range=[0, paid["ltv_cac_ratio"].max() * 1.75]))
    return fig


def fig_retention(retention: pd.DataFrame, summary: pd.DataFrame) -> go.Figure:
    small = set(summary.loc[summary["small_sample"].astype(bool), "channel"])
    part = retention[~retention["channel"].isin(small | {"paid_total"})].copy()
    part = part.sort_values("repeat_rate_in_horizon")
    colors = [CARBON if c == "all" else COBALT if c in PAID_ORDER else MUTED for c in part["channel"]]
    fig = go.Figure(go.Bar(
        x=part["repeat_rate_in_horizon"], y=part["label"], orientation="h", marker_color=colors,
        text=[pct(v) for v in part["repeat_rate_in_horizon"]], textposition="outside", cliponaxis=False,
        customdata=part[["repeat_rate_90d", "orders_per_customer_in_horizon", "mature_customers"]].values,
        hovertemplate="%{y}<br>Voltou em 12 meses: %{x:.0%}<br>Voltou em 90 dias: %{customdata[0]:.0%}"
                      "<br>Pedidos por cliente em 12 meses: %{customdata[1]:.2f}"
                      "<br>Base: %{customdata[2]:,.0f} clientes<extra></extra>",
    ))
    _layout(fig, 420, xaxis=dict(title="Clientes que compraram de novo em 12 meses", tickformat=".0%",
                                 range=[0, 0.8]))
    return fig


def fig_ceiling(summary: pd.DataFrame) -> go.Figure:
    paid = summary[summary["channel"].isin(PAID_ORDER) & ~summary["small_sample"].astype(bool)]
    paid = paid.sort_values("cac")
    fig = go.Figure()
    fig.add_bar(y=paid["label"], x=paid["cac"], name="CAC atual", orientation="h", marker_color=CARBON,
                hovertemplate="%{y}<br>CAC: R$ %{x:,.0f}<extra></extra>")
    fig.add_bar(y=paid["label"], x=paid["cac_ceiling_at_3x"], name="Teto para 3x (LTV ÷ 3)", orientation="h",
                marker_color=COBALT, hovertemplate="%{y}<br>Teto 3x: R$ %{x:,.0f}<extra></extra>")
    fig.add_bar(y=paid["label"], x=paid["break_even_cac"], name="Teto para empatar (LTV de 12 meses)",
                orientation="h", marker_color=MUTED,
                hovertemplate="%{y}<br>Teto para empatar: R$ %{x:,.0f}<extra></extra>")
    _layout(fig, 400, barmode="group", xaxis=dict(title="R$ por cliente", tickprefix="R$ ", tickformat=",.0f"))
    return fig


def fig_waterfall(pnl: pd.DataFrame) -> go.Figure:
    t = pnl.sum(numeric_only=True)
    per100 = 100 / t["revenue"]
    steps = [
        ("Venda", t["revenue"], "absolute"),
        ("Produto", -t["product_cost"], "relative"),
        ("Frete", -t["freight_cost"], "relative"),
        ("Devoluções", -(t["refunds"] - t["restocked_cost"]), "relative"),
        ("Taxa pgto.*", -t["payment_fee"], "relative"),
        ("Embalagem*", -t["variable_order_cost"], "relative"),
        ("Margem", None, "total"),
        ("Mídia", -t["spend"], "relative"),
        ("Sobra", None, "total"),
    ]
    values = [0 if v is None else v * per100 for _, v, _ in steps]
    fig = go.Figure(go.Waterfall(
        x=[s[0] for s in steps], y=values, measure=[s[2] for s in steps],
        text=[f"{_num(abs(v), 1)}" if v else "" for v in values], textposition="outside",
        connector=dict(line=dict(color=LINE)),
        increasing=dict(marker=dict(color=COBALT)), decreasing=dict(marker=dict(color=MUTED)),
        totals=dict(marker=dict(color=CARBON)),
        hovertemplate="%{x}: R$ %{y:.1f} de cada R$ 100<extra></extra>",
    ))
    _layout(fig, 400, yaxis=dict(title="R$ de cada R$ 100 vendidos", range=[0, 112]), showlegend=False)
    fig.update_xaxes(tickangle=0, tickfont=dict(size=11))
    return fig


def fig_horizon(curve: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    series = [("paid_total", COBALT, 3.5), ("paid_social", LOSS, 2), ("paid_search_generic", "#B07A12", 2),
              ("performance_max", GAIN, 2), ("paid_search_brand", INK_2, 1.5)]
    for channel, color, width in series:
        part = curve[curve["channel"] == channel].sort_values("months")
        fig.add_scatter(x=part["months"], y=part["ltv_cac"], name=_label(channel), mode="lines",
                        line=dict(color=color, width=width),
                        visible=True if channel != "paid_search_brand" else "legendonly",
                        customdata=part[["margin_per_customer", "cac", "cohorts"]].values,
                        hovertemplate="Mês %{x}: %{y:.2f}x<br>Margem acumulada: R$ %{customdata[0]:,.0f}"
                                      "<br>CAC das mesmas coortes: R$ %{customdata[1]:,.0f}"
                                      f"<br>%{{customdata[2]}} coortes<extra>{_label(channel)}</extra>")
    for value, name in ((1, "empata"), (3, "meta de 3x")):
        fig.add_hline(y=value, line=dict(color=INK_2, dash="dash", width=1),
                      annotation_text=name, annotation_position="top left", annotation_font_size=11)
    _layout(fig, 400, xaxis=dict(title="Meses desde a aquisição (o mês da compra é o mês 1)", dtick=3),
            yaxis=dict(title="LTV ÷ CAC", ticksuffix="x", range=[0, 3.4]))
    return fig


def fig_tornado(sensitivity: pd.DataFrame) -> go.Figure:
    frame = sensitivity.sort_values("swing")
    base = frame["base"].iloc[0]
    labels = {"6 meses": "6 meses", "24 meses": "24 meses", "data_driven": "data-driven",
              "last_click": "último clique", "first_click": "primeiro clique", "linear": "linear"}
    names = [f"{lab}<br><span style='font-size:11px;color:{INK_2}'>{labels.get(ls, ls)} → {labels.get(hs, hs)}</span>"
             for lab, ls, hs in zip(frame["label"], frame["low_setting"], frame["high_setting"])]
    fig = go.Figure(go.Bar(
        y=names, x=frame["high"] - frame["low"], base=frame["low"], orientation="h",
        marker_color=[COBALT if i == len(frame) - 1 else MUTED for i in range(len(frame))],
        text=[f"{times(l)} a {times(h)}" for l, h in zip(frame["low"], frame["high"])],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{text}<extra></extra>",
    ))
    fig.add_vline(x=base, line=dict(color=CARBON, width=2),
                  annotation_text=f"como modelado: {times(base)}", annotation_position="bottom right",
                  annotation_font_size=11)
    _layout(fig, 400, xaxis=dict(title="LTV/CAC dos canais pagos", ticksuffix="x", range=[0.8, 2.7]),
            showlegend=False)
    return fig


def _label(channel: str) -> str:
    from .summary import label
    return label(channel)


# --- page -------------------------------------------------------------------------

def _chart(div_id: str, fig: go.Figure) -> str:
    return f'<div class="chart" id="{div_id}"></div>', (div_id, fig.to_plotly_json())


def _symbol() -> str:
    # The ABADE "A", as the brand kit stores it (normalised to height 100).
    d = (ROOT / "assets" / "brand" / "symbol_path.txt").read_text().split("\n", 1)[1].strip()
    return f'<svg class="mark" viewBox="{SYMBOL_VIEWBOX}" aria-hidden="true"><path d="{d}" fill-rule="evenodd"/></svg>'


def channel_table(summary: pd.DataFrame, retention: pd.DataFrame) -> str:
    r = retention.set_index("channel")
    rows = []
    for row in summary.itertuples():
        if row.channel in ("paid_total", "all"):
            cls = ' class="total"'
        else:
            cls = ""
        flag = ' <span class="tag">amostra pequena</span>' if row.small_sample else ""
        repeat = r["repeat_rate_in_horizon"].get(row.channel)
        rows.append(
            f"<tr{cls}><th scope='row'>{html.escape(row.label)}{flag}</th>"
            f"<td>{brl(row.spend) if row.paid or row.channel == 'all' else NO_MEDIA}</td>"
            f"<td>{_num(row.new_customers)}</td><td>{_num(row.orders)}</td>"
            f"<td>{brl_short(row.revenue)}</td><td>{brl_short(row.contribution_margin)}</td>"
            f"<td>{brl(row.cac) if pd.notna(row.cac) else UNDEFINED}</td>"
            f"<td>{pct(row.cac_share_of_first_margin)}</td>"
            f"<td>{brl(row.ltv)}</td><td>{times(row.ltv_cac_ratio)}</td>"
            f"<td>{_payback_cell(row)}</td>"
            f"<td>{pct(repeat)}</td></tr>"
        )
    head = ("<tr><th scope='col'>Canal</th><th>Investimento</th><th>Novos clientes</th><th>Pedidos atribuídos</th>"
            "<th>Receita atribuída</th><th>Margem atribuída</th><th>CAC</th><th>CAC ÷ margem do 1º pedido</th>"
            "<th>LTV 12 meses</th><th>LTV/CAC</th><th>Payback</th><th>Recompra em 12 meses</th></tr>")
    return f'<div class="table-wrap"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def _payback_cell(row) -> str:
    if row.channel == "all" or pd.isna(row.cac):
        return "—"
    if pd.isna(row.payback_months):
        return "não pagou"
    return "1 mês" if int(row.payback_months) == 1 else f"{int(row.payback_months)} meses"


def month_table(monthly: pd.DataFrame, month: str) -> str:
    part = monthly[monthly["month"] == month]
    order = ["all", "paid_total", *PAID_ORDER, "organic_search", "direct", "organic_social", "email",
             "referral", "whatsapp", "untracked"]
    part = part.set_index("channel").reindex([c for c in order if c in set(part["channel"])])
    rows = []
    for channel, row in part.iterrows():
        cls = ' class="total"' if channel in ("all", "paid_total") else ""
        flag = ' <span class="tag">amostra pequena</span>' if row["small_sample"] and channel not in ("all", "paid_total") else ""
        cac = brl(row["cac"]) if pd.notna(row["cac"]) else UNDEFINED
        rows.append(
            f"<tr{cls}><th scope='row'>{html.escape(_label(channel))}{flag}</th>"
            f"<td>{brl(row['spend']) if pd.notna(row['spend']) else NO_MEDIA}</td>"
            f"<td>{pct(row['spend_mom'], signed=True)}</td><td>{pct(row['spend_yoy'], signed=True)}</td>"
            f"<td>{_num(row['new_customers'])}</td><td>{pct(row['new_customers_mom'], signed=True)}</td>"
            f"<td>{pct(row['new_customers_yoy'], signed=True)}</td>"
            f"<td>{brl_short(row['contribution_margin'])}</td><td>{pct(row['margin_yoy'], signed=True)}</td>"
            f"<td>{cac}</td><td>{pct(row['cac_yoy'], signed=True)}</td></tr>"
        )
    ly = f"vs {_month_name(f'{int(month[:4]) - 1}{month[4:]}')}"
    head = ("<tr><th scope='col'>Canal</th><th>Investimento</th><th>vs mês anterior</th>"
            f"<th>{ly}</th><th>Novos clientes</th><th>vs mês anterior</th><th>{ly}</th><th>Margem atribuída</th>"
            f"<th>{ly}</th><th>CAC</th><th>{ly}</th></tr>")
    return f'<div class="table-wrap"><table><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def render_page() -> str:
    t = reports.read()
    h = reports.headline_values(t)
    summary, monthly = t["channel_summary"], t["channel_monthly"]
    s = summary.set_index("channel")
    last_month = h["window_end"]
    per100 = 100 / h["revenue"]

    charts = []

    def chart(div_id, fig):
        div, spec = _chart(div_id, fig)
        charts.append(spec)
        return div

    pause_meta, pause_others = -h["pause_meta_drop"], -h["pause_others_drop"]
    kpis = [
        (times(h["paid_ltv_cac"]), f"de margem em {h['ltv_horizon_months']:.0f} meses para cada R$ 1 em mídia paga",
         "accent"),
        (brl(h["paid_cac"]), f"para trazer um cliente pela mídia paga (loja inteira: {brl(h['blended_cac'])})", ""),
        (months(h["paid_payback_months"]), "para a margem do cliente pago cobrir o que custou trazê-lo", ""),
        (pct(h["meta_spend_share"]), f"da verba vai para a Meta, que só empata em {h['ltv_horizon_months']:.0f} meses "
                                     f"({times(h['meta_ltv_cac'])})", "warn"),
        (pct(h["repeat_rate_horizon"]), "dos clientes novos compram de novo em até 12 meses", ""),
    ]
    kpi_html = "".join(
        f'<div class="kpi {cls}"><div class="kpi-value">{html.escape(v)}</div><div class="kpi-text">{html.escape(c)}</div></div>'
        for v, c, cls in kpis
    )

    page = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unit economics por canal · Tecelã Tecidos</title>
<meta name="description" content="CAC, LTV, payback e margem de contribuição por canal de aquisição. Dados simulados.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&display=swap" rel="stylesheet">
<style>
:root {{ --carbon: {CARBON}; --ivory: {IVORY}; --cobalt: {COBALT}; --ink2: {INK_2}; --line: {LINE}; --loss: {LOSS}; }}
* {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{ margin: 0; background: var(--ivory); color: var(--carbon); font-family: Lato, "Helvetica Neue", Arial, sans-serif;
       font-size: 16px; line-height: 1.55; }}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: 0 16px; }}
header.top {{ background: var(--carbon); color: var(--ivory); padding: 28px 0 24px; }}
.brand {{ display: flex; gap: 16px; align-items: center; }}
.mark {{ width: 46px; height: 36px; fill: var(--ivory); flex: none; }}
.eyebrow {{ color: var(--cobalt); font-weight: 700; letter-spacing: .16em; text-transform: uppercase; font-size: 12px; }}
h1 {{ font-weight: 900; font-size: clamp(26px, 5vw, 40px); line-height: 1.1; margin: 4px 0 6px; letter-spacing: -.01em; }}
.lede {{ color: #C9CDD3; margin: 0; max-width: 760px; }}
.notice {{ color: var(--carbon); background: #FFF4D6; border-left: 5px solid #C8B680; padding: 12px 16px; margin: 20px 0 0; border-radius: 6px;
          font-size: 15px; }}
section {{ padding: 28px 0 8px; border-bottom: 1px solid var(--line); }}
h2 {{ font-size: 13px; letter-spacing: .14em; text-transform: uppercase; color: var(--cobalt); margin: 0 0 4px; }}
h3 {{ font-size: clamp(19px, 3vw, 24px); font-weight: 900; line-height: 1.25; margin: 4px 0 6px; }}
p.sub {{ color: var(--ink2); margin: 0 0 10px; font-size: 15px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 14px 0 8px; }}
@media (max-width: 600px) {{ .kpis {{ grid-template-columns: 1fr 1fr; }} .kpi-value {{ font-size: 24px; }} .kpi {{ padding: 12px; }} }}
.kpi {{ background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 16px; }}
.kpi-value {{ font-size: 30px; font-weight: 900; line-height: 1.1; }}
.kpi.accent .kpi-value {{ color: var(--cobalt); }}
.kpi.warn .kpi-value {{ color: var(--loss); }}
.kpi-text {{ color: var(--ink2); font-size: 14px; margin-top: 6px; }}
.card {{ background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 16px 16px 8px; margin: 14px 0; }}
.chart {{ width: 100%; min-height: 340px; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
@media (max-width: 820px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
ul.points {{ padding-left: 20px; margin: 8px 0; }}
ul.points li {{ margin: 6px 0; }}
.table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 8px 0; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; min-width: 860px; }}
th, td {{ padding: 7px 7px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }}
thead th {{ font-size: 12px; color: var(--ink2); font-weight: 700; text-align: right; vertical-align: bottom; white-space: normal; }}
th[scope=row], thead th:first-child {{ text-align: left; position: sticky; left: 0; background: #fff; }}
tr.total th, tr.total td {{ font-weight: 700; background: #F1F2FF; }}
tr.total th[scope=row] {{ background: #F1F2FF; }}
.na {{ color: var(--ink2); font-style: italic; }}
.tag {{ display: inline-block; font-size: 11px; font-weight: 700; color: #7A5B00; background: #FFF4D6; border-radius: 10px;
        padding: 0 7px; margin-left: 4px; }}
.reco {{ counter-reset: r; list-style: none; padding: 0; }}
.reco li {{ counter-increment: r; background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 14px 16px 14px 60px;
           margin: 10px 0; position: relative; }}
.reco li::before {{ content: counter(r); position: absolute; left: 16px; top: 14px; width: 30px; height: 30px; border-radius: 50%;
                   background: var(--cobalt); color: #fff; font-weight: 900; display: grid; place-items: center; }}
.reco b {{ display: block; margin-bottom: 2px; }}
details {{ background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 12px 16px; margin: 14px 0 28px; }}
summary {{ cursor: pointer; font-weight: 700; }}
details h4 {{ margin: 16px 0 4px; }}
details p, details li {{ font-size: 14px; color: #2B2F35; }}
footer {{ padding: 24px 0 40px; color: var(--ink2); font-size: 13px; }}
a {{ color: var(--cobalt); }}
</style>
</head>
<body>
<header class="top"><div class="wrap">
  <div class="brand">{_symbol()}<div>
    <div class="eyebrow">ABADE · Unit economics por canal</div>
    <h1>A mídia paga se paga, mas devagar, e a Meta só empata</h1>
  </div></div>
  <p class="lede">Tecelã Tecidos, loja online de tecidos. {_month_name(h['window_start'])} a {_month_name(h['window_end'])}:
  {brl_short(h['revenue'])} de vendas, {brl_short(h['spend'])} investidos em Meta e Google, {_num(h['new_customers'])} clientes novos.</p>
  <div class="notice" role="note"><b>Dados simulados.</b> A Tecelã Tecidos é uma loja fictícia; os dados foram gerados
  a partir do funcionamento de um e-commerce real e não descrevem nenhuma empresa.</div>
</div></header>

<main class="wrap">
<section id="resumo">
  <h2>Resumo executivo</h2>
  <h3>Cada R$ 1 em mídia paga volta como R$ {_num(h['paid_ltv_cac'], 2)} de margem em um ano; o que paga a aquisição é a recompra</h3>
  <div class="kpis">{kpi_html}</div>
  <ul class="points">
    <li>O primeiro pedido de um cliente pago deixa {brl(h['paid_first_order_margin'])} de margem; trazê-lo custa {brl(h['paid_cac'])}.
    Ele só se paga porque {pct(h['repeat_rate_horizon'])} voltam a comprar em até um ano.</li>
    <li>O custo para trazer um cliente pela mídia paga subiu de {brl(h['paid_cac_year1'])} no 1º ano para {brl(h['paid_cac_year3'])} no 3º:
    a verba cresceu {pct(h['spend_growth_y1_y3'])} e os clientes pagos, {pct(h['paid_customers_growth_y1_y3'])}.</li>
    <li>A Meta recebe {pct(h['meta_spend_share'])} da verba e, pelo último clique, devolve {times(h['meta_ltv_cac'])} em 12 meses.
    Mas na pausa de agosto/2025 os outros canais perderam {_num(pause_others)} clientes novos, mais que a própria Meta ({_num(pause_meta)}).</li>
  </ul>
</section>

<section id="meses">
  <h2>Evolução por mês</h2>
  <h3>O investimento subiu {pct(h['spend_growth_y1_y3'])} do 1º ao 3º ano; os clientes trazidos pela mídia paga, só {pct(h['paid_customers_growth_y1_y3'])}</h3>
  <p class="sub">Investimento mensal ao lado dos clientes novos que ele trouxe. Os triângulos marcam meses com campanhas sazonais da loja
  (Black Friday, Natal, Festa Junina, Dia das Mães, Volta às Aulas). Passe o mouse ou toque para ver o mês.</p>
  <div class="card">{chart('c-monthly', fig_monthly(monthly, t['events']))}</div>
  <h3>A Meta é o canal pago mais caro em quase todos os meses</h3>
  <p class="sub">Custo por cliente novo, por canal e mês. Círculos vazados são meses com menos de {h['small_sample_customers']:.0f}
  clientes novos no canal: amostra pequena, não leia como tendência. Clique na legenda para ligar e desligar canais.</p>
  <div class="card">{chart('c-cac', fig_cac_by_channel(monthly))}</div>
  <h3>Último mês completo ({_month_name(last_month)}): comparação com o mês anterior e com o mesmo mês do ano passado</h3>
  <p class="sub">Canais sem investimento registrado têm CAC indefinido, nunca zero.</p>
  {month_table(monthly, last_month)}
  <div class="card"><b>Teste de pausa da Meta (agosto/2025).</b> Com a prospecção da Meta pausada de 4 a 24/08, os clientes novos
  da loja caíram {pct(-h['pause_store_change'])} de julho para agosto (no mesmo período de 2024, {pct(-h['baseline_store_change'])}).
  Os clientes creditados à Meta caíram {_num(pause_meta)}; os dos outros canais, {_num(pause_others)}, sobretudo busca de marca,
  busca orgânica e pedidos sem rastreio. É um sinal de que a Meta gera demanda que outros canais recolhem. É um mês só: sinal, não prova.</div>
</section>

<section id="canais">
  <h2>Comparação entre canais</h2>
  <div class="grid2">
    <div><h3>Só a busca pela marca passa de 3x, e ela recolhe quem já procurava a loja</h3>
    <p class="sub">Margem de 12 meses de cada cliente ÷ custo para trazê-lo. O Demand Gen fica de fora:
    {brl(h['video_spend'])} trouxeram {_num(h['video_new_customers'])} clientes.</p>
    <div class="card">{chart('c-channels', fig_channels(summary))}</div></div>
    <div><h3>O cliente volta na mesma proporção venha de onde vier: a diferença entre canais está no custo</h3>
    <p class="sub">Clientes que compraram de novo em até 12 meses, por canal de aquisição (coortes com 12 meses completos).</p>
    <div class="card">{chart('c-retention', fig_retention(t['retention'], summary))}</div></div>
  </div>
  <h3>Todos os canais, no período inteiro</h3>
  <p class="sub">Investimento sempre ao lado de clientes, pedidos e margem. Pedidos, receita e margem são os atribuídos ao canal pelo último clique.
  E-mail traz poucos clientes novos ({_num(h['email_new_customers'])}) mas fecha {_num(h['email_orders'])} pedidos: é canal de recompra, não de aquisição.</p>
  {channel_table(summary, t['retention'])}
</section>

<section id="unit-economics">
  <h2>Unit economics e teto de CAC</h2>
  <div class="grid2">
    <div><h3>De cada R$ 100 vendidos, R$ {_num(h['contribution_margin'] * per100, 0)} sobram antes da mídia e R$ {_num(h['margin_after_media'] * per100, 0)} depois</h3>
    <p class="sub">O frete grátis custa: a loja pagou {brl_short(h['freight_subsidy'])} a mais às transportadoras do que cobrou dos clientes.
    * premissa (o dataset não registra esse custo).</p>
    <div class="card">{chart('c-waterfall', fig_waterfall(t['monthly_pnl']))}</div></div>
    <div><h3>Fora a busca de marca, todo canal pago está acima do teto de 3x</h3>
    <p class="sub">Teto de CAC = quanto um cliente do canal gera de margem em 12 meses (empatar) ou um terço disso (meta de 3x).</p>
    <div class="card">{chart('c-ceiling', fig_ceiling(summary))}</div></div>
  </div>
</section>

<section id="sensibilidade">
  <h2>Sensibilidade</h2>
  <div class="grid2">
    <div><h3>A conclusão depende de quanto tempo de recompra você conta, não dos custos estimados</h3>
    <p class="sub">LTV/CAC dos canais pagos com uma premissa alterada por vez. Custos estimados (taxas, embalagem) mexem no máximo
    {_num(h['costs_max_swing'], 2)}.</p>
    <div class="card">{chart('c-tornado', fig_tornado(t['sensitivity']))}</div></div>
    <div><h3>A mídia paga empata no {months(h['paid_payback_months']).replace(' meses', 'º mês')} e não chega a 3x nem em dois anos</h3>
    <p class="sub">Margem acumulada ÷ CAC, mês a mês depois da aquisição. Cada ponto usa só as coortes observadas por aquele tempo.</p>
    <div class="card">{chart('c-horizon', fig_horizon(t['ltv_curve']))}</div></div>
  </div>
</section>

<section id="recomendacao">
  <h2>Recomendação</h2>
  <h3>Decidir o prazo de retorno aceitável, testar a Meta de verdade e investir na recompra</h3>
  <ol class="reco">
    <li><b>Definir o payback aceitável antes de mexer na verba.</b> Com 6 meses de recompra a mídia paga empata ({times(h['top_premise_low'])});
    com 24, rende {times(h['top_premise_high'])}. Se o caixa aguenta esperar um ano, a mídia paga se justifica; se não, precisa encolher.</li>
    <li><b>Não cortar a Meta pelo último clique: medir o efeito real.</b> Ela é {pct(h['meta_spend_share'])} da verba e empata em 12 meses,
    mas a pausa de agosto/2025 sugere que alimenta busca de marca e orgânico. Repetir a pausa com grupo de controle por região e usar
    o CAC incremental como teto.</li>
    <li><b>Conter o CAC pago, que subiu {pct(h['paid_cac_year3'] / h['paid_cac_year1'] - 1)} e não voltou.</b> Mais verba está trazendo cada vez menos clientes
    por real. Desligar o que não traz cliente (o Demand Gen gastou {brl(h['video_spend'])} por {_num(h['video_new_customers'])} clientes) e travar o
    teto de CAC por canal no valor da tabela acima.</li>
    <li><b>Puxar a recompra e o frete.</b> {pct(h['repeat_rate_90d'])} voltam em 90 dias e {pct(h['repeat_rate_horizon'])} em um ano: é isso que paga a aquisição.
    E-mail já fecha {_num(h['email_orders'])} pedidos. Rever a política de frete grátis, que custou {brl_short(h['freight_subsidy'])} no período.</li>
  </ol>
</section>

<details>
  <summary>Como os números foram calculados</summary>
  <h4>Fonte</h4>
  <p>Banco do repositório <code>ecommerce</code> (Tecelã Tecidos, dados simulados, seed 20231001), lido sem alterações e conferido por contagem
  de linhas e somas de controle. Período analisado: {h['window_start']} a {h['window_end']}; outubro/2026 tem 13 dias e fica fora.</p>
  <h4>Definições</h4>
  <ul>
    <li><b>Margem de contribuição</b> por pedido = venda − custo do produto − frete pago à transportadora − reembolsos + custo de itens que voltaram
    ao estoque − taxa de pagamento − embalagem e atendimento. A loja é varejo próprio: a margem é sobre a venda, não sobre comissão.
    É antes de impostos sobre a venda, que o dataset não registra.</li>
    <li><b>Cliente novo</b>: primeiro pedido pago da pessoa (contas com o mesmo CPF são unidas). Clientes importados da plataforma anterior não contam.</li>
    <li><b>Canal de aquisição</b>: canal do primeiro pedido pago, pelo modelo de último clique da tabela de atribuição. Busca no Google separada em marca e genérica.
    Pedidos sem sessão rastreada ({pct(h['untracked_share_of_new_customers'])} dos clientes novos) ficam como "sem rastreio"; por isso o CAC por canal pago tende a sair acima do real,
    e o CAC da loja inteira ({brl(h['blended_cac'])}) não depende disso.</li>
    <li><b>CAC</b> = investimento do canal ÷ clientes novos do canal. Canal sem investimento registrado tem CAC indefinido, nunca zero.
    Todas as taxas são razão de somas (total ÷ total), não média de taxas mensais.</li>
    <li><b>LTV</b> = margem gerada pelo cliente nos primeiros {h['ltv_horizon_months']:.0f} meses, só para coortes observadas pelos 12 meses inteiros.
    LTV/CAC usa o investimento dessas mesmas coortes.</li>
    <li><b>Payback</b> = meses de margem acumulada até cobrir o CAC, contando o mês da compra.</li>
    <li><b>Amostra pequena</b>: canal-mês com menos de {h['small_sample_customers']:.0f} clientes novos, ou canal com menos de 100 no período.</li>
  </ul>
  <h4>Premissas (o dataset não registra)</h4>
  <p>Taxa de pagamento: Pix {pct(h['fee_pix'], 1)}, cartão {pct(h['fee_card'], 1)}, boleto {brl(h['fee_boleto'], 2)}. Embalagem e atendimento:
  {brl(h['variable_order_cost'], 2)} por pedido. Nada sobre canal ou investimento é simulado: os dois vêm do dataset.</p>
  <h4>Limites</h4>
  <p>CAC aqui é custo médio por cliente atribuído, não custo incremental. Custos de influenciadores, CRM, agência e conteúdo não estão no dataset.
  Os primeiros meses da base têm mais clientes "novos" do que um mês típico, o que deixa o CAC do 1º ano mais baixo.</p>
  <p>Código, SQL e testes: <a href="https://github.com/arielabade/unit-economics-olist">github.com/arielabade/unit-economics-olist</a>.</p>
</details>
</main>
<footer><div class="wrap">ABADE · Strategy · Data · Growth — gerado por <code>python -m unit_economics.dashboard</code> a partir de <code>reports/</code>.</div></footer>
<script src="plotly-{get_plotlyjs_version()}.min.js"></script>
<script>
const CHARTS = {json.dumps(dict(charts), cls=PlotlyJSONEncoder, separators=(",", ":"))};
const CONFIG = {{responsive: true, displayModeBar: false, locale: "pt-BR"}};
for (const [id, spec] of Object.entries(CHARTS)) {{
  const narrow = window.innerWidth < 600;
  if (narrow && spec.layout.legend) {{ spec.layout.legend.y = -0.32; }}
  // Bar labels sit outside the bars: give them room on a phone.
  if (narrow && ["c-channels", "c-retention", "c-tornado"].includes(id) && spec.layout.xaxis.range) {{
    const r = spec.layout.xaxis.range; spec.layout.xaxis.range = [r[0], r[0] + (r[1] - r[0]) * 1.35];
  }}
  Plotly.newPlot(id, spec.data, spec.layout, CONFIG);
}}
</script>
</body>
</html>
"""
    return page


def build() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(render_page(), encoding="utf-8")
    _ship_plotly()
    (ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")
    return OUT / "index.html"


def _month_name(month: str) -> str:
    names = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    year, m = month.split("-")
    return f"{names[int(m) - 1]}/{year}"


def _ship_plotly() -> None:
    """plotly.js next to the page, pinned to the version the figures were built with."""
    import plotly

    name = f"plotly-{get_plotlyjs_version()}.min.js"
    target = OUT / name
    if not target.exists():
        source = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
        shutil.copyfile(source, target)
    for old in OUT.glob("plotly-*.min.js"):
        if old.name != name:
            old.unlink()


if __name__ == "__main__":
    print(build().relative_to(ROOT))
