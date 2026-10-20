"""README.md, rendered from a template and the committed tables in reports/.

Every number in the README is a placeholder filled from ``reports/``, the
same tables the figures and the dashboard read, so the three cannot
disagree. ``tests/test_readme.py`` fails if the committed README differs
from what this module renders.

Run with ``python -m unit_economics.readme``.
"""

from __future__ import annotations

import re

import pandas as pd

from . import reports
from .config import ROOT

README = ROOT / "README.md"
TEMPLATE = ROOT / "templates" / "README.template.md"
DASHBOARD_URL = "https://arielabade.github.io/unit-economics-olist/dashboard/"

ENGLISH = {
    "paid_social": "Meta Ads", "paid_search_generic": "Google Search, generic",
    "paid_search_brand": "Google Search, brand", "performance_max": "Google Performance Max",
    "paid_shopping": "Google Shopping", "paid_video": "Google Demand Gen",
    "organic_search": "Organic search", "direct": "Direct", "organic_social": "Organic social",
    "email": "E-mail", "referral": "Referral", "whatsapp": "WhatsApp", "untracked": "Untracked",
    "paid_total": "**All paid channels**", "all": "**Whole store**",
}
PREMISES = {
    "ltv_horizon_months": "Months of repeat purchase counted in LTV",
    "attribution_model": "Attribution model of the first order",
    "payment_fee_card": "Card fee", "variable_order_cost": "Handling cost per order",
    "payment_fee_pix": "Pix fee", "payment_fee_boleto": "Boleto fee",
}


def money(value, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"R$ {value:,.{digits}f}"


def money_short(value: float) -> str:
    if abs(value) >= 1e6:
        return f"R$ {value / 1e6:.2f}M"
    return f"R$ {value / 1e3:,.0f}k"


def pct(value, digits: int = 0) -> str:
    return "—" if value is None or pd.isna(value) else f"{value * 100:.{digits}f}%"


def times(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:.2f}x"


def payback(row) -> str:
    if row["channel"] == "all" or pd.isna(row["cac"]):
        return "—"
    if pd.isna(row["payback_months"]):
        return "not within the window"
    n = int(row["payback_months"])
    return "1 month" if n == 1 else f"{n} months"


def channel_table(summary: pd.DataFrame, retention: pd.DataFrame) -> str:
    r = retention.set_index("channel")["repeat_rate_in_horizon"]
    lines = ["| Channel | Spend | New customers | CAC | CAC / first-order margin | LTV (12 m) | LTV/CAC | Payback | Bought again in 12 m |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |"]
    for _, row in summary.iterrows():
        name = ENGLISH[row["channel"]] + (" *(small sample)*" if row["small_sample"] else "")
        spend = money(row["spend"]) if pd.notna(row["spend"]) else "no media line"
        cac = money(row["cac"]) if pd.notna(row["cac"]) else "undefined"
        lines.append(f"| {name} | {spend} | {row['new_customers']:,.0f} | {cac} | "
                     f"{pct(row['cac_share_of_first_margin'])} | {money(row['ltv'])} | "
                     f"{times(row['ltv_cac_ratio'])} | {payback(row)} | {pct(r.get(row['channel']))} |")
    return "\n".join(lines)


def ceiling_table(summary: pd.DataFrame) -> str:
    paid = summary[summary["paid"] & (summary["channel"] != "paid_total") & ~summary["small_sample"]]
    lines = ["| Paid channel | CAC | Ceiling to break even (12-month LTV) | Ceiling at 3x | Clears 3x? |",
             "| --- | ---: | ---: | ---: | --- |"]
    for _, row in paid.sort_values("cac").iterrows():
        ok = "yes" if row["cac"] <= row["cac_ceiling_at_3x"] else "no"
        lines.append(f"| {ENGLISH[row['channel']]} | {money(row['cac'])} | {money(row['break_even_cac'])} | "
                     f"{money(row['cac_ceiling_at_3x'])} | {ok} |")
    return "\n".join(lines)


def yearly_table(yearly: pd.DataFrame) -> str:
    lines = ["| | Paid spend | Customers from paid media | Paid CAC | Store revenue |",
             "| --- | ---: | ---: | ---: | ---: |"]
    paid = yearly[yearly["channel"] == "paid_total"].set_index("year")
    store = yearly[yearly["channel"] == "all"].set_index("year")
    for year in paid.index:
        row = paid.loc[year]
        lines.append(f"| {year.replace('ano', 'Year')} ({row['start']} to {row['end']}) | {money_short(row['spend'])} | "
                     f"{row['new_customers']:,.0f} | {money(row['cac'])} | {money_short(store.loc[year, 'revenue'])} |")
    return "\n".join(lines)


def sensitivity_table(sensitivity: pd.DataFrame) -> str:
    def words(text: str) -> str:
        return (str(text).replace("as mesmas", "the same").replace("meses", "months")
                .replace("coortes", "cohorts").replace("_", " "))
    lines = ["| Premise | Low | High | All paid channels' LTV/CAC | Swing |", "| --- | --- | --- | --- | ---: |"]
    for _, row in sensitivity.iterrows():
        low, high = words(row["low_setting"]), words(row["high_setting"])
        lines.append(f"| {PREMISES[row['premise']]} | {low} | {high} | {row['low']:.2f}x to {row['high']:.2f}x | "
                     f"{row['swing']:.2f} |")
    return "\n".join(lines)


def count_tests() -> int:
    return sum(len(re.findall(r"^def test_", p.read_text(encoding="utf-8"), re.M))
               for p in (ROOT / "tests").glob("test_*.py"))


def values() -> dict[str, str]:
    t = reports.read()
    h = reports.headline_values(t)
    s = t["channel_summary"].set_index("channel")
    return {
        "tests": str(count_tests()),
        "dashboard_url": DASHBOARD_URL,
        "window": f"{h['window_start']} to {h['window_end']}",
        "months": f"{h['months']:.0f}",
        "revenue": money_short(h["revenue"]),
        "orders": f"{h['orders']:,.0f}",
        "margin": money_short(h["contribution_margin"]),
        "margin_rate": pct(h["margin_rate"], 1),
        "spend": money_short(h["spend"]),
        "after_media": money_short(h["margin_after_media"]),
        "new_customers": f"{h['new_customers']:,.0f}",
        "blended_cac": money(h["blended_cac"], 2),
        "paid_new_customers": f"{h['paid_new_customers']:,.0f}",
        "paid_share": pct(h["paid_share_of_new_customers"]),
        "untracked_share": pct(h["untracked_share_of_new_customers"]),
        "paid_cac": money(h["paid_cac"], 2),
        "paid_first_margin": money(h["paid_first_order_margin"], 2),
        "paid_cac_share": pct(h["paid_cac_share_of_first_margin"]),
        "paid_ltv": money(h["paid_ltv"], 2),
        "paid_ltv_cac": times(h["paid_ltv_cac"]),
        "paid_payback": f"{h['paid_payback_months']:.0f}",
        "cac_y1": money(h["paid_cac_year1"]),
        "cac_y2": money(h["paid_cac_year2"]),
        "cac_y3": money(h["paid_cac_year3"]),
        "cac_growth": pct(h["paid_cac_year3"] / h["paid_cac_year1"] - 1),
        "spend_growth": pct(h["spend_growth_y1_y3"]),
        "paid_customers_growth": pct(h["paid_customers_growth_y1_y3"]),
        "revenue_growth": pct(h["revenue_growth_y1_y3"]),
        "repeat_12": pct(h["repeat_rate_horizon"]),
        "repeat_90": pct(h["repeat_rate_90d"]),
        "repeat_min": pct(h["repeat_rate_horizon_min"]),
        "repeat_max": pct(h["repeat_rate_horizon_max"]),
        "meta_share": pct(h["meta_spend_share"]),
        "meta_spend": money_short(h["meta_spend"]),
        "meta_cac": money(h["meta_cac"], 2),
        "meta_first_margin": money(h["meta_first_order_margin"], 2),
        "meta_cac_share": pct(h["meta_cac_share_of_first_margin"]),
        "meta_ltv_cac": times(h["meta_ltv_cac"]),
        "meta_payback": f"{h['meta_payback_months']:.0f}",
        "meta_after_media": money_short(h["meta_margin_after_media"]),
        "brand_cac": money(h["brand_cac"], 2),
        "brand_ltv_cac": times(h["brand_ltv_cac"]),
        "generic_ltv_cac": times(h["generic_ltv_cac"]),
        "pmax_ltv_cac": times(h["pmax_ltv_cac"]),
        "shopping_ltv_cac": times(h["shopping_ltv_cac"]),
        "video_spend": money(h["video_spend"]),
        "video_customers": f"{h['video_new_customers']:.0f}",
        "email_customers": f"{h['email_new_customers']:,.0f}",
        "email_orders": f"{h['email_orders']:,.0f}",
        "freight_subsidy": money_short(h["freight_subsidy"]),
        "freight_rate": pct(h["freight_subsidy_rate"], 1),
        "pause_meta": f"{-h['pause_meta_drop']:,.0f}",
        "pause_others": f"{-h['pause_others_drop']:,.0f}",
        "pause_store": pct(-h["pause_store_change"]),
        "baseline_store": pct(-h["baseline_store_change"]),
        "baseline_others": f"{-h['baseline_others_drop']:,.0f}",
        "horizon_low": times(h["top_premise_low"]),
        "horizon_high": times(h["top_premise_high"]),
        "attribution_low": times(h["second_premise_low"]),
        "attribution_high": times(h["second_premise_high"]),
        "same_12": times(h["same_cohorts_12"]),
        "same_24": times(h["same_cohorts_24"]),
        "same_count": f"{h['same_cohorts_count']:.0f}",
        "costs_swing": f"{h['costs_max_swing']:.2f}",
        "fee_pix": pct(h["fee_pix"], 1),
        "fee_card": pct(h["fee_card"], 1),
        "fee_boleto": money(h["fee_boleto"], 2),
        "order_cost": money(h["variable_order_cost"], 2),
        "small_sample": f"{h['small_sample_customers']:.0f}",
        "channel_table": channel_table(t["channel_summary"], t["retention"]),
        "ceiling_table": ceiling_table(t["channel_summary"]),
        "yearly_table": yearly_table(t["yearly"]),
        "sensitivity_table": sensitivity_table(t["sensitivity"]),
        "brand_customers": f"{s.loc['paid_search_brand', 'new_customers']:,.0f}",
    }


def render() -> str:
    filled = values()
    text = TEMPLATE.read_text(encoding="utf-8")

    def fill(match: re.Match) -> str:
        key = match.group(1)
        if key not in filled:
            raise KeyError(f"README template asks for [[{key}]], which reports/ does not provide")
        return filled[key]

    return re.sub(r"\[\[(\w+)\]\]", fill, text)


def write() -> None:
    README.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    write()
    print(README.relative_to(ROOT))
