"""Static client dashboard: ``docs/dashboard/``, served by GitHub Pages.

Built from the same committed tables as the README (``reports/``). The split
follows the usual front-end contract:

* **Python (this module)** decides *what is said*: it reads reports/, writes
  every sentence and number of the page, renders the tables (so the page is
  complete and accessible without JavaScript), and embeds the chart data as
  one JSON block.
* **templates/dashboard/** holds *how it looks and behaves*: ``index.html``
  (structure, with ``[[slot]]`` placeholders), ``styles.css`` (ABADE tokens,
  light and dark themes, print) and ``app.js`` (charts drawn from the JSON,
  lazily, in the active theme; month selector; sortable, filterable tables).
* **vendor/** ships plotly.js (cartesian bundle, pinned), so the page needs no
  server and no CDN.

Run with ``python -m unit_economics.dashboard`` after ``unit_economics.reports``.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
from pathlib import Path

import pandas as pd

from . import reports
from .config import CHANNELS, ROOT
from .summary import label

OUT = ROOT / "docs" / "dashboard"
TEMPLATES = ROOT / "templates" / "dashboard"
PLOTLY = ROOT / "vendor" / "plotly-cartesian-4.1.1.min.js"
SYMBOL_VIEWBOX = "0 0 127.566 100"

#: Channels drawn as series, in the fixed categorical order the palette was
#: validated in (styles.css: --c-*). Demand Gen is left out of the charts:
#: too few customers to read (it stays in the tables, flagged).
SERIES = ["paid_total", "paid_social", "paid_search_generic", "performance_max",
          "paid_search_brand", "paid_shopping"]
PAID = list(CHANNELS.paid)
MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MONTHS_PT_LONG = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
                  "setembro", "outubro", "novembro", "dezembro"]


# --- formatting (pt-BR) -------------------------------------------------------

def _num(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def _na(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


NBSP, MINUS = "\u00a0", "\u2212"


def brl(value, digits: int = 0) -> str:
    if _na(value):
        return "—"
    sign = MINUS if value < 0 else ""
    return f"{sign}R${NBSP}{_num(abs(value), digits)}"


def brl_short(value: float) -> str:
    sign = MINUS if value < 0 else ""
    a = abs(value)
    if a >= 1e6:
        return f"{sign}R${NBSP}{_num(a / 1e6, 2)}{NBSP}mi"
    if a >= 1e3:
        return f"{sign}R${NBSP}{_num(a / 1e3, 0)}{NBSP}mil"
    return brl(value)


def pct(value, digits: int = 0, signed: bool = False) -> str:
    if _na(value):
        return "—"
    shown = round(value * 100, digits)
    if shown == 0:
        return "0%"                       # never "−0%"
    text = _num(abs(shown), digits) + "%"
    return (MINUS + text) if shown < 0 else ("+" + text) if signed else text


def times(value, digits: int = 2) -> str:
    return "—" if _na(value) else _num(value, digits) + "x"


def nbsp(text: str) -> str:
    """Keep "R$" and "mi"/"mil" on the same line as their number."""
    text = re.sub(r"R\$ (?=[−\d])", "R$" + NBSP, text)
    return re.sub(r"(?<=\d) (mi|mil)\b", NBSP + r"\1", text)


def months(value) -> str:
    if _na(value):
        return "não pagou no período"
    n = int(value)
    return "no mês da compra" if n == 1 else f"{n} meses"


def month_name(month: str, long: bool = False) -> str:
    year, m = month.split("-")
    names = MONTHS_PT_LONG if long else MONTHS_PT
    return f"{names[int(m) - 1]}/{year}" if not long else f"{names[int(m) - 1]} de {year}"


def esc(text) -> str:
    return html.escape(str(text))


# --- server-rendered pieces -----------------------------------------------------

NA_MEDIA = '<span class="na">sem mídia</span>'
NA_CAC = '<span class="na" title="Canal sem investimento registrado: não existe custo por cliente">indefinido</span>'
SMALL = '<span class="tag" title="Poucos clientes: não leia como tendência">amostra pequena</span>'


def _swatch(channel: str) -> str:
    key = channel if channel in SERIES else ("all" if channel == "all" else "unpaid")
    return f'<span class="swatch" style="--sw: var(--c-{key})" aria-hidden="true"></span>'


def _delta(value, good_when_up: bool | None, small: bool = False) -> str:
    """A signed change with an arrow. Colour, and a word for screen readers, only
    where the direction means good or bad, and never on a small sample."""
    if _na(value):
        return '<td class="num">—</td>'
    shown = round(value * 100)
    arrow = "▲" if shown > 0 else "▼" if shown < 0 else "■"
    tone, word = "", ""
    if good_when_up is not None and shown != 0 and not small:
        better = (shown > 0) == good_when_up
        tone = " up-good" if better else " up-bad"
        word = f'<span class="sr-only"> ({"melhor" if better else "pior"})</span>'
    return f'<td class="num delta{tone}"><span aria-hidden="true">{arrow}</span> {pct(value, signed=True)}{word}</td>'


def channel_table(summary: pd.DataFrame, retention: pd.DataFrame) -> str:
    r = retention.set_index("channel")
    rows = []
    for row in summary.itertuples():
        group = "total" if row.channel in ("paid_total", "all") else ("paid" if row.paid else "unpaid")
        flag = f" {SMALL}" if row.small_sample else ""
        repeat = r["repeat_rate_in_horizon"].get(row.channel)
        payback = ("—" if row.channel == "all" or _na(row.cac)
                   else "não pagou" if _na(row.payback_months)
                   else "1 mês" if int(row.payback_months) == 1 else f"{int(row.payback_months)} meses")
        cells = [
            (row.spend if row.paid or row.channel == "all" else None,
             brl(row.spend) if row.paid or row.channel == "all" else NA_MEDIA),
            (row.new_customers, _num(row.new_customers)),
            (row.orders, _num(row.orders)),
            (row.revenue, brl_short(row.revenue)),
            (row.contribution_margin, brl_short(row.contribution_margin)),
            (row.cac, brl(row.cac) if not _na(row.cac) else NA_CAC),
            (row.cac_share_of_first_margin, times(row.cac_share_of_first_margin, 1)),
            (row.ltv, brl(row.ltv)),
            (row.ltv_cac_ratio, times(row.ltv_cac_ratio)),
            (row.payback_months if group != "total" or row.channel == "paid_total" else None, payback),
            (repeat, pct(repeat)),
        ]
        tds = "".join(
            f'<td class="num" data-sort="{"" if _na(v) else v}">{t}</td>' for v, t in cells
        )
        rows.append(f'<tr data-group="{group}"><th scope="row" data-sort="{esc(row.label)}">'
                    f'{_swatch(row.channel)}{esc(row.label)}{flag}</th>{tds}</tr>')
    head = "".join(
        f'<th scope="col" class="num"><button type="button" data-sort-col="{i + 1}">{h}</button></th>'
        for i, h in enumerate(["Investimento", "Clientes novos", "Pedidos", "Receita", "Margem", "CAC",
                               "CAC ÷ 1º pedido", "LTV 12 meses", "LTV/CAC¹", "Payback",
                               "Recompra 12 meses"])
    )
    return (
        '<table class="data sortable" id="channel-table" aria-describedby="channel-table-note">'
        f'<thead><tr><th scope="col"><button type="button" data-sort-col="0">Canal</button></th>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def month_table(monthly: pd.DataFrame, month: str) -> str:
    """The comparison table for one month; app.js re-renders it for another."""
    part = monthly[monthly["month"] == month].set_index("channel")
    order = ["all", "paid_total", *PAID, "organic_search", "direct", "organic_social", "email",
             "referral", "whatsapp", "untracked"]
    rows = []
    for channel in [c for c in order if c in part.index]:
        row = part.loc[channel]
        small = bool(row["small_sample"]) and channel not in ("all", "paid_total")
        flag = f" {SMALL}" if small else ""
        total = ' class="total"' if channel in ("all", "paid_total") else ""
        spend = brl(row["spend"]) if not _na(row["spend"]) else NA_MEDIA
        cac = brl(row["cac"]) if not _na(row["cac"]) else NA_CAC
        rows.append(
            f'<tr{total}><th scope="row">{_swatch(channel)}{esc(label(channel))}{flag}</th>'
            f'<td class="num">{spend}</td>{_delta(row["spend_mom"], None)}{_delta(row["spend_yoy"], None)}'
            f'<td class="num">{_num(row["new_customers"])}</td>{_delta(row["new_customers_mom"], True, small)}'
            f'{_delta(row["new_customers_yoy"], True, small)}'
            f'<td class="num">{brl_short(row["contribution_margin"])}</td>{_delta(row["margin_yoy"], True, small)}'
            f'<td class="num">{cac}</td>{_delta(row["cac_yoy"], False, small)}</tr>'
        )
    return (f'<table class="data" id="month-table">{month_head(month)}<tbody>{"".join(rows)}</tbody></table>')


def month_head(month: str) -> str:
    """Two header rows: the measure, then value / vs previous month / vs a year earlier."""
    y, m = int(month[:4]), int(month[5:])
    prev = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    before, ly = month_name(prev), month_name(f"{y - 1}-{m:02d}")
    group = lambda name, n: f'<th scope="colgroup" colspan="{n}" class="num group">{name}</th>'
    sub = lambda cols: "".join(f'<th scope="col" class="num">{c}</th>' for c in cols)
    return ("<thead><tr><th scope=\"col\" rowspan=\"2\">Canal</th>"
            + group("Investimento", 3) + group("Clientes novos", 3) + group("Margem", 2) + group("CAC", 2)
            + "</tr><tr>" + sub(["valor", f"vs {before}", f"vs {ly}"]) + sub(["número", f"vs {before}", f"vs {ly}"])
            + sub(["valor", f"vs {ly}"]) + sub(["valor", f"vs {ly}"]) + "</tr></thead>")


def simple_table(caption: str, columns: list[str], rows: list[list[str]], first_is_header: bool = True) -> str:
    head = "".join(f'<th scope="col"{" class=num" if i else ""}>{esc(c)}</th>' for i, c in enumerate(columns))
    body = []
    for r in rows:
        cells = [f'<th scope="row">{r[0]}</th>' if first_is_header else f"<td>{r[0]}</td>"]
        cells += [f'<td class="num">{c}</td>' for c in r[1:]]
        body.append(f"<tr>{''.join(cells)}</tr>")
    return (f'<table class="data compact"><caption>{esc(caption)}</caption><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table>")


def data_tables(t: dict[str, pd.DataFrame], h: dict) -> dict[str, str]:
    """A table twin for every chart: every value readable without hover or colour."""
    monthly = t["channel_monthly"]
    paid = monthly[monthly["channel"] == "paid_total"].set_index("month")
    store = monthly[monthly["channel"] == "all"].set_index("month")
    ev = t["events"].set_index("month")["events"]
    months_ = list(paid.index)
    spend_rows = [[month_name(m), brl(paid.loc[m, "spend"]), _num(paid.loc[m, "new_customers"]),
                   _num(store.loc[m, "new_customers"]), brl(paid.loc[m, "cac"]), esc(ev.get(m, ""))]
                  for m in months_]
    cac_cols = [c for c in SERIES]
    cac_rows = []
    for m in months_:
        r = [month_name(m)]
        for c in cac_cols:
            v = monthly[(monthly["channel"] == c) & (monthly["month"] == m)]["cac"]
            r.append(brl(v.iloc[0]) if len(v) and not _na(v.iloc[0]) else "—")
        cac_rows.append(r)
    summary = t["channel_summary"]
    pv = summary[summary["channel"].isin(PAID)].sort_values("ltv_cac_ratio", ascending=False)
    ret = t["retention"].sort_values("repeat_rate_in_horizon", ascending=False)
    curve = t["ltv_curve"]
    horizon_rows = []
    for k in (1, 3, 6, 9, 12, 18, 24):
        r = [f"{k}º mês"]
        for c in ["paid_total", "paid_social", "paid_search_generic", "performance_max", "paid_search_brand"]:
            v = curve[(curve["channel"] == c) & (curve["months"] == k)]["ltv_cac"]
            r.append(times(v.iloc[0]) if len(v) else "—")
        horizon_rows.append(r)
    pnl = t["monthly_pnl"].sum(numeric_only=True)
    per100 = 100 / pnl["revenue"]
    return {
        "table_spend": simple_table(
            "Investimento e clientes novos por mês", ["Mês", "Investimento", "Clientes via mídia paga",
                                                       "Clientes, todos os canais", "CAC pago", "Campanha sazonal"],
            spend_rows),
        "table_cac": simple_table("CAC por canal e mês", ["Mês"] + [label(c) for c in cac_cols], cac_rows),
        "table_ltv_cac": simple_table(
            "LTV/CAC por canal pago", ["Canal", "Investimento", "Clientes novos", "CAC", "LTV 12 meses", "LTV/CAC"],
            [[esc(r.label), brl(r.spend), _num(r.new_customers), brl(r.cac), brl(r.ltv), times(r.ltv_cac_ratio)]
             for r in pv.itertuples()]),
        "table_retention": simple_table(
            "Recompra por canal de aquisição (coortes com 12 meses completos)",
            ["Canal", "Clientes", "Voltou em 90 dias", "Voltou em 12 meses", "Pedidos por cliente em 12 meses"],
            [[esc(r.label), _num(r.mature_customers), pct(r.repeat_rate_90d), pct(r.repeat_rate_in_horizon),
              _num(r.orders_per_customer_in_horizon, 2)] for r in ret.itertuples()]),
        "table_waterfall": simple_table(
            "De cada R$ 100 vendidos", ["Linha", "R$ por R$ 100", "Total no período"],
            [[n, (MINUS if v < 0 else "") + _num(abs(v) * per100, 1), brl_short(v)] for n, v in [
                ("Venda (com frete cobrado)", pnl["revenue"]), ("Custo do produto", -pnl["product_cost"]),
                ("Frete pago à transportadora", -pnl["freight_cost"]),
                ("Devoluções, líquidas de reestoque", -(pnl["refunds"] - pnl["restocked_cost"])),
                ("Taxa de pagamento (premissa)", -pnl["payment_fee"]),
                ("Embalagem e atendimento (premissa)", -pnl["variable_order_cost"]),
                ("Margem de contribuição", pnl["contribution_margin"]), ("Mídia paga", -pnl["spend"]),
                ("Sobra depois da mídia", pnl["margin_after_media"])]]),
        "table_ceiling": simple_table(
            "CAC contra o teto, por canal pago", ["Canal", "CAC", "Teto para 3x", "Teto para empatar", "Passa em 3x?"],
            [[esc(r.label), brl(r.cac), brl(r.cac_ceiling_at_3x), brl(r.break_even_cac),
              "sim" if r.cac <= r.cac_ceiling_at_3x else "não"]
             for r in summary[summary["channel"].isin(PAID) & ~summary["small_sample"]].sort_values("cac").itertuples()]),
        "table_tornado": simple_table(
            "LTV/CAC dos canais pagos com uma premissa alterada por vez",
            ["Premissa", "Valor baixo", "Valor alto", "LTV/CAC (baixo a alto)", "Variação"],
            [[esc(r.label), esc(_setting(r.low_setting)), esc(_setting(r.high_setting)),
              f"{times(r.low)} a {times(r.high)}", _num(r.swing, 2)] for r in t["sensitivity"].itertuples()]),
        "table_horizon": simple_table(
            "LTV/CAC acumulado por meses desde a aquisição",
            ["Mês", "Canais pagos", "Meta Ads", "Google Busca (genérica)", "Google Performance Max", "Google Busca (marca)"],
            horizon_rows),
    }


def _setting(text: str) -> str:
    return {"data_driven": "atribuição por dados", "last_click": "último clique", "first_click": "primeiro clique",
            "linear": "linear"}.get(str(text), str(text).replace(".", ","))


# --- chart data -----------------------------------------------------------------

def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    """Rows for the page's JSON: missing values as null, floats rounded (smaller page)."""
    def clean(v):
        if _na(v):
            return None
        if isinstance(v, (bool,)) or type(v).__name__ == "bool_":
            return bool(v)
        if isinstance(v, float):
            return round(v, 4) if abs(v) < 10 else round(v, 2)
        return v
    return [{c: clean(v) for c, v in zip(columns, row)} for row in frame[columns].itertuples(index=False)]


def payload(t: dict[str, pd.DataFrame], h: dict) -> dict:
    monthly = t["channel_monthly"]
    keep = ["channel", "month", "spend", "new_customers", "cac", "small_sample", "spend_mom", "spend_yoy",
            "new_customers_mom", "new_customers_yoy", "contribution_margin", "margin_yoy", "cac_yoy"]
    pnl = t["monthly_pnl"].sum(numeric_only=True)
    return {
        "labels": {c: label(c) for c in sorted(set(monthly["channel"]))},
        "series": SERIES,
        "paid": PAID,
        "months": sorted(monthly["month"].unique().tolist()),
        "events": dict(zip(t["events"]["month"], t["events"]["events"])),
        "monthly": _records(monthly, keep),
        "summary": _records(t["channel_summary"], ["channel", "label", "paid", "spend", "new_customers", "cac",
                                                   "ltv", "ltv_cac_ratio", "break_even_cac", "cac_ceiling_at_3x",
                                                   "small_sample"]),
        "retention": _records(t["retention"], ["channel", "label", "mature_customers", "repeat_rate_90d",
                                               "repeat_rate_in_horizon", "orders_per_customer_in_horizon"]),
        "curve": _records(t["ltv_curve"], ["channel", "months", "ltv_cac", "margin_per_customer", "cac", "cohorts"]),
        "sensitivity": _records(t["sensitivity"], ["premise", "label", "low_setting", "high_setting", "low",
                                                   "base", "high", "swing"]),
        "pnl": {k: float(pnl[k]) for k in ("revenue", "product_cost", "freight_cost", "refunds", "restocked_cost",
                                            "payment_fee", "variable_order_cost", "contribution_margin", "spend",
                                            "margin_after_media")},
        "smallSample": h["small_sample_customers"],
        "settingNames": {"data_driven": "atribuição por dados", "last_click": "último clique",
                         "first_click": "primeiro clique", "linear": "linear"},
    }


# --- page -------------------------------------------------------------------------

def _symbol() -> str:
    """The ABADE "A", as the brand kit stores it (normalised to height 100)."""
    d = (ROOT / "assets" / "brand" / "symbol_path.txt").read_text().split("\n", 1)[1].strip()
    return f'<svg class="mark" viewBox="{SYMBOL_VIEWBOX}" aria-hidden="true" focusable="false"><path d="{d}" fill-rule="evenodd"/></svg>'


def _symbol_path() -> str:
    return (ROOT / "assets" / "brand" / "symbol_path.txt").read_text().split("\n", 1)[1].strip()


def _version(*paths: Path) -> str:
    digest = hashlib.sha256()
    for p in paths:
        digest.update(p.read_bytes())
    return digest.hexdigest()[:10]


def slots() -> dict[str, str]:
    t = reports.read()
    h = reports.headline_values(t)
    s = t["channel_summary"].set_index("channel")
    r = t["retention"].set_index("channel")
    per100 = 100 / h["revenue"]
    month_options = "".join(
        f'<option value="{m}"{" selected" if m == h["window_end"] else ""}>{month_name(m, long=True)}</option>'
        for m in sorted(t["channel_monthly"]["month"].unique(), reverse=True)
    )
    # "Black Friday 2024" -> "Black Friday": the dates the store itself campaigns on.
    events_list = sorted({re.sub(r" \d{4}$", "", e)
                          for es in t["events"]["events"] for e in es.split(" · ") if "Pausa" not in e})
    values = {
        "version_css": _version(TEMPLATES / "styles.css"),
        "version_js": _version(TEMPLATES / "app.js"),
        "plotly_file": PLOTLY.name,
        "symbol": _symbol(),
        "symbol_path": _symbol_path(),
        "period": f"{month_name(h['window_start'])} a {month_name(h['window_end'])}",
        "period_long": f"{month_name(h['window_start'], True)} a {month_name(h['window_end'], True)}",
        "months": f"{h['months']:.0f}",
        "revenue": brl_short(h["revenue"]),
        "orders": _num(h["orders"]),
        "spend": brl_short(h["spend"]),
        "new_customers": _num(h["new_customers"]),
        "margin": brl_short(h["contribution_margin"]),
        "margin_rate": pct(h["margin_rate"], 1),
        "margin_per100": _num(h["contribution_margin"] * per100, 0),
        "after_media_per100": _num(h["margin_after_media"] * per100, 0),
        "paid_ltv_cac": times(h["paid_ltv_cac"]),
        "paid_ltv_cac_brl": _num(h["paid_ltv_cac"], 2),
        "paid_cac": brl(h["paid_cac"]),
        "blended_cac": brl(h["blended_cac"]),
        "paid_ltv": brl(h["paid_ltv"]),
        "paid_first_margin": brl(h["paid_first_order_margin"]),
        "paid_payback": months(h["paid_payback_months"]),
        "paid_payback_n": f"{h['paid_payback_months']:.0f}",
        "paid_share": pct(h["paid_share_of_new_customers"]),
        "paid_new_customers": _num(h["paid_new_customers"]),
        "untracked_share": pct(h["untracked_share_of_new_customers"]),
        "meta_share": pct(h["meta_spend_share"]),
        "meta_ltv_cac": times(h["meta_ltv_cac"]),
        "meta_cac": brl(h["meta_cac"]),
        "meta_first_margin": brl(h["meta_first_order_margin"]),
        "meta_payback": f"{h['meta_payback_months']:.0f}",
        "cac_y1": brl(h["paid_cac_year1"]),
        "cac_y3": brl(h["paid_cac_year3"]),
        "cac_growth": pct(h["paid_cac_year3"] / h["paid_cac_year1"] - 1),
        "spend_growth": pct(h["spend_growth_y1_y3"]),
        "paid_customers_growth": pct(h["paid_customers_growth_y1_y3"]),
        "repeat_12": pct(h["repeat_rate_horizon"]),
        "repeat_90": pct(h["repeat_rate_90d"]),
        "repeat_min": pct(h["repeat_rate_horizon_min"]),
        "repeat_max": pct(h["repeat_rate_horizon_max"]),
        "brand_ltv_cac": times(h["brand_ltv_cac"]),
        "email_customers": _num(h["email_new_customers"]),
        "email_orders": _num(h["email_orders"]),
        "video_spend": brl(h["video_spend"]),
        "video_customers": _num(h["video_new_customers"]),
        "freight_subsidy": brl_short(h["freight_subsidy"]),
        "pause_meta": _num(-h["pause_meta_drop"]),
        "pause_others": _num(-h["pause_others_drop"]),
        "pause_store": pct(-h["pause_store_change"]),
        "baseline_store": pct(-h["baseline_store_change"]),
        "horizon_low": times(h["top_premise_low"]),
        "horizon_high": times(h["top_premise_high"]),
        "same_12": times(h["same_cohorts_12"]),
        "same_24": times(h["same_cohorts_24"]),
        "attribution_low": times(h["second_premise_low"]),
        "costs_swing": _num(h["costs_max_swing"], 2),
        "fee_pix": pct(h["fee_pix"], 1),
        "fee_card": pct(h["fee_card"], 1),
        "fee_boleto": brl(h["fee_boleto"], 2),
        "order_cost": brl(h["variable_order_cost"], 2),
        "small_sample": f"{h['small_sample_customers']:.0f}",
        "last_month": month_name(h["window_end"], long=True),
        "month_options": month_options,
        "seasonal_events": ", ".join(events_list),
        "channel_table": channel_table(t["channel_summary"], t["retention"]),
        "month_table": month_table(t["channel_monthly"], h["window_end"]),
        "payback_meta_text": months(s.loc["paid_social", "payback_months"]),
        "ex_cac": brl(h["paid_cac"]),
        "ex_ltv": brl(h["paid_ltv"]),
        "ex_ceiling3": brl(h["paid_ltv"] / 3),
        "data": json.dumps(payload(t, h), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"),
        **data_tables(t, h),
    }
    values["repeat_paid"] = pct(r.loc["paid_total", "repeat_rate_in_horizon"])
    paid = t["channel_monthly"][t["channel_monthly"]["channel"] == "paid_total"].sort_values("month")
    values["spend_first"] = brl_short(paid["spend"].iloc[0])
    values["spend_last"] = brl_short(paid["spend"].iloc[-1])
    values["same_count"] = f"{h['same_cohorts_count']:.0f}"
    values["meta_payback_text"] = months(s.loc["paid_social", "payback_months"])
    values = {k: (nbsp(v) if k not in ("data", "symbol", "symbol_path") and isinstance(v, str) else v)
              for k, v in values.items()}
    return values


def render_page() -> str:
    filled = slots()
    text = (TEMPLATES / "index.html").read_text(encoding="utf-8")

    def fill(match: re.Match) -> str:
        key = match.group(1)
        if key not in filled:
            raise KeyError(f"dashboard template asks for [[{key}]], which dashboard.slots() does not provide")
        return filled[key]

    return re.sub(r"\[\[(\w+)\]\]", fill, text)


def build() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(render_page(), encoding="utf-8")
    for name in ("styles.css", "app.js"):
        shutil.copyfile(TEMPLATES / name, OUT / name)
    target = OUT / PLOTLY.name
    if not target.exists() or target.read_bytes() != PLOTLY.read_bytes():
        shutil.copyfile(PLOTLY, target)
    for old in OUT.glob("plotly-*.min.js"):
        if old.name != PLOTLY.name:
            old.unlink()
    (OUT / "favicon.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-14 -14 156 128"><rect x="-14" y="-14" width="156" '
        f'height="128" rx="24" fill="#050505"/><path d="{_symbol_path()}" fill="#F6F5F0" fill-rule="evenodd"/></svg>',
        encoding="utf-8")
    (ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")
    return OUT / "index.html"


if __name__ == "__main__":
    print(build().relative_to(ROOT))
