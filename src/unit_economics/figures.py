"""Figures for the README, drawn from the committed tables in ``reports/``.

Every figure reads ``reports/*.csv`` (written by ``reports.py``) and nothing
else, so a reader can rebuild every chart from the repository alone, and the
numbers in a chart are the numbers in the README and on the dashboard.

Titles state the finding, not the metric. Run with
``python -m unit_economics.figures``; ``--refresh`` rewrites ``reports/``
from ``data/processed`` first.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import brandviz as bv
from . import reports
from .config import CHANNELS, ROOT

FIGURES = ROOT / "assets" / "figures"
BRAND = ROOT / "assets" / "brand"

#: Paid channels drawn as lines in the horizon chart, with their colours.
HORIZON_SERIES = (
    ("paid_total", "All paid channels", bv.COBALT),
    ("paid_social", "Meta Ads", bv.CRIMSON),
    ("paid_search_generic", "Google Search (generic)", bv.AMBER),
    ("performance_max", "Google Performance Max", bv.TEAL),
)

ENGLISH = {
    "paid_social": "Meta Ads",
    "paid_search_generic": "Google Search, generic",
    "paid_search_brand": "Google Search, brand",
    "performance_max": "Google Performance Max",
    "paid_shopping": "Google Shopping",
    "paid_video": "Google Demand Gen",
    "paid_total": "All paid channels",
}

PREMISES = {
    "ltv_horizon_months": "Months of repeat purchase counted",
    "attribution_model": "Attribution model of the first order",
    "payment_fee_card": "Card fee",
    "variable_order_cost": "Handling cost per order",
    "payment_fee_pix": "Pix fee",
    "payment_fee_boleto": "Boleto fee",
}


def headline(h: dict) -> Path:
    """The three numbers the README leads with."""
    fig, _ = bv.kpi_strip([
        (f"{h['paid_ltv_cac']:.2f}x",
         f"Margin returned per R$ 1 of paid media\nwithin {h['ltv_horizon_months']:.0f} months, all paid channels"),
        (f"{h['meta_spend_share']:.0%}",
         f"Of the paid budget goes to Meta, which\nonly breaks even in {h['ltv_horizon_months']:.0f} months "
         f"({h['meta_ltv_cac']:.2f}x)"),
        (f"+{h['paid_cac_year3'] / h['paid_cac_year1'] - 1:.0%}",
         f"Paid CAC from year 1 to year 3 (R$ {h['paid_cac_year1']:.0f} to\n"
         f"R$ {h['paid_cac_year3']:.0f}): budget +{h['spend_growth_y1_y3']:.0%}, "
         f"paid customers +{h['paid_customers_growth_y1_y3']:.0%}"),
    ])
    return bv.save(fig, FIGURES / "headline.svg")


def channel_ltv_cac(summary: pd.DataFrame, h: dict) -> Path:
    """LTV/CAC by paid channel against break-even and the 3x planning target.

    Unpaid channels are absent rather than shown at zero: they have no media
    cost, so the ratio is undefined. A channel with too few customers to
    read is named in the subtitle instead of drawn as a bar.
    """
    paid = summary[summary["paid"] & ~summary["channel"].isin(["paid_total"])]
    small = paid[paid["small_sample"]]
    paid = paid[~paid["small_sample"]].sort_values("ltv_cac_ratio").reset_index(drop=True)
    meta = paid.set_index("channel").loc["paid_social"]

    note = ""
    if not small.empty:
        row = small.iloc[0]
        note = (f" {ENGLISH[row['channel']]} is left out: R$ {row['spend']:,.0f} bought "
                f"{row['new_customers']:.0f} customers.")
    fig, ax = bv.panel(
        12.4, 5.6,
        title="Only brand search clears 3x; Meta, the largest budget, only breaks even",
        subtitle=(f"{h['ltv_horizon_months']:.0f}-month contribution margin per customer over CAC, "
                  f"first order credited by last click.{note}"),
    )
    positions = np.arange(len(paid), dtype=float)
    top = paid["ltv_cac_ratio"].max()
    ax.set_xlim(0, top * 1.22)
    ax.set_ylim(-0.6, len(paid) - 0.4)
    fig.canvas.draw()
    colors = [bv.CRIMSON if c == "paid_social" else bv.COBALT if r >= 3 else bv.SLATE
              for c, r in zip(paid["channel"], paid["ltv_cac_ratio"])]
    bv.bars(ax, positions, paid["ltv_cac_ratio"], colors, horizontal=True, width=0.58,
            labels=[f"{v:.2f}x" for v in paid["ltv_cac_ratio"]])
    ax.set_yticks(positions, [ENGLISH[c] for c in paid["channel"]])
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:.0f}x")
    for value, text in ((1.0, "break-even"), (3.0, "3x target")):
        ax.axvline(value, color=bv.STEEL, linewidth=1.1, linestyle=(0, (4, 3)), alpha=0.75, zorder=2)
        ax.text(value, len(paid) - 0.45, f" {text}", color=bv.STEEL, fontsize=9, va="bottom")
    bv.annotate(
        ax,
        f"Meta: CAC R$ {meta['cac']:.0f} against R$ {meta['first_order_margin_per_customer']:.0f} of "
        f"first-order margin.\n{meta['spend'] / summary.set_index('channel').loc['paid_total', 'spend']:.0%} "
        f"of paid spend, {meta['payback_months']:.0f} months to pay back.",
        xy=(meta["ltv_cac_ratio"] + top * 0.04, float(paid.index[paid["channel"] == "paid_social"][0])),
        xytext=(top * 0.42, float(paid.index[paid["channel"] == "paid_social"][0]) + 1.1),
    )
    bv.clean(ax, axis="x", spines=("top", "right", "bottom"))
    return bv.save(fig, FIGURES / "channel_ltv_cac.svg")


def paid_cac_trend(monthly: pd.DataFrame, yearly: pd.DataFrame) -> Path:
    """Paid CAC per month, with each year's pooled level."""
    paid = monthly[monthly["channel"] == "paid_total"].copy()
    paid["date"] = pd.to_datetime(paid["month"])
    years = yearly[yearly["channel"] == "paid_total"]

    fig, ax = bv.panel(
        12.4, 5.4,
        title="Paid CAC rose by a third after the first year and has not come back",
        subtitle="Paid media spend over customers acquired by paid channels, per month. "
                 "Dashed: each year's level (total spend over total customers).",
    )
    ax.plot(paid["date"], paid["cac"], color=bv.COBALT, linewidth=2.2, marker="o", markersize=4.5,
            markeredgecolor=bv.CARBON, markeredgewidth=1.0, zorder=5)
    for row in years.itertuples():
        start = pd.Timestamp(row.start + "-01")
        end = pd.Timestamp(row.end + "-01") + pd.offsets.MonthEnd(0)
        ax.plot([start, end], [row.cac, row.cac], color=bv.IVORY, linewidth=1.4,
                linestyle=(0, (5, 3)), zorder=4)
        ax.text(start + (end - start) / 2, paid["cac"].max() * 1.13, f"{row.year.replace('ano', 'year')}: R$ {row.cac:.0f}",
                ha="center", va="center", fontsize=10, color=bv.IVORY, fontweight="bold",
                bbox=dict(facecolor=bv.CARBON, edgecolor="none", pad=2.0), zorder=6)
    ax.set_ylim(0, paid["cac"].max() * 1.22)
    ax.yaxis.set_major_formatter(lambda value, _: f"R$ {value:.0f}")
    ax.set_ylabel("Paid CAC")
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    bv.clean(ax)
    return bv.save(fig, FIGURES / "paid_cac_trend.svg")


def ltv_cac_horizon(curve: pd.DataFrame, h: dict) -> Path:
    """The premise that moves the result most: how many months are counted."""
    fig, ax = bv.panel(
        12.4, 5.6,
        title=f"Paid media pays back in {h['paid_payback_months']:.0f} months and does not reach 3x within two years",
        subtitle="Cumulative contribution margin over CAC, by months since acquisition. "
                 "Each point uses only cohorts observed that long, over their own spend.",
    )
    ends = []
    for channel, name, color in HORIZON_SERIES:
        part = curve[curve["channel"] == channel].sort_values("months")
        width = 2.8 if channel == "paid_total" else 1.8
        ax.plot(part["months"], part["ltv_cac"], color=color, linewidth=width, zorder=5 if channel == "paid_total" else 4)
        ends.append((part.iloc[-1], name, color, channel))
    # End labels are spread apart when two lines finish at the same height.
    placed = []
    for last, name, color, channel in sorted(ends, key=lambda e: -e[0]["ltv_cac"]):
        y = last["ltv_cac"]
        if placed and placed[-1] - y < 0.13:
            y = placed[-1] - 0.13
        placed.append(y)
        ax.text(last["months"] + 0.4, y, f"{name} {last['ltv_cac']:.2f}x",
                color=color, fontsize=9.5, va="center", fontweight="bold" if channel == "paid_total" else "normal")
    for value, text in ((1.0, "break-even"), (3.0, "3x target")):
        ax.axhline(value, color=bv.STEEL, linewidth=1.1, linestyle=(0, (4, 3)), alpha=0.75, zorder=2)
        ax.text(0.7, value + 0.05, text, color=bv.STEEL, fontsize=9, va="bottom")
    horizon = h["ltv_horizon_months"]
    ax.axvline(horizon, color=bv.GRID, linewidth=1.2, zorder=1)
    ax.text(horizon + 0.2, 3.25, f"LTV used: {horizon:.0f} months", color=bv.STEEL, fontsize=9)
    ax.set_xlim(0.5, curve["months"].max() + 6.5)
    ax.set_ylim(0, 3.5)
    ax.set_xlabel("Months since acquisition (the acquisition month is month 1)")
    ax.set_ylabel("LTV / CAC")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.1f}x")
    bv.clean(ax)
    return bv.save(fig, FIGURES / "ltv_cac_horizon.svg")


def sensitivity(frame: pd.DataFrame, h: dict) -> Path:
    """Tornado: the range of the paid LTV/CAC as each premise moves."""
    frame = frame.sort_values("swing").reset_index(drop=True)
    fig, ax = bv.panel(
        12.4, 5.8,
        title="The answer depends on how long you wait for repeat purchase, not on the assumed costs",
        subtitle=f"All paid channels' LTV/CAC ({h['paid_ltv_cac']:.2f}x as modelled) with one premise moved at a time.",
    )
    base = frame["base"].iloc[0]
    positions = np.arange(len(frame), dtype=float)
    for y, row in zip(positions, frame.itertuples()):
        color = bv.COBALT if y == positions[-1] else bv.SLATE
        ax.barh(y, row.high - row.low, left=row.low, height=0.5, color=color, zorder=3)
        ax.text(row.low - 0.03, y, f"{row.low:.2f}  {_setting(row.low_setting)}", ha="right", va="center",
                fontsize=9, color=bv.STEEL)
        ax.text(row.high + 0.03, y, f"{_setting(row.high_setting)}  {row.high:.2f}", ha="left", va="center",
                fontsize=9, color=bv.STEEL)
    ax.axvline(base, color=bv.IVORY, linewidth=1.2, zorder=4)
    ax.set_yticks(positions, [PREMISES[p] for p in frame["premise"]])
    ax.set_xlim(frame["low"].min() - 0.55, frame["high"].max() + 0.55)
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:.1f}x")
    fig.subplots_adjust(left=0.27, right=0.97)
    bv.clean(ax, axis="x", spines=("top", "right", "left"))
    return bv.save(fig, FIGURES / "sensitivity.svg")


def _setting(text: str) -> str:
    return (str(text).replace("as mesmas", "same").replace("coortes", "cohorts").replace("meses", "months")
            .replace("_", " ").replace(",", "."))


def brand_panels(h: dict) -> list[Path]:
    """Header and case arc, through the portfolio's brand kit when it is present.

    The kit lives in the profile repository (``arielabade/brand``), next to
    this one. Without it the committed panels are kept. Neither panel quotes
    a number, so they cannot drift from reports/.
    """
    kit = Path(os.environ.get("ABADE_BRANDKIT", ROOT.parent / "arielabade" / "brand" / "brandkit.py"))
    if not kit.exists():
        return []
    spec = importlib.util.spec_from_file_location("brandkit", kit)
    brandkit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(brandkit)
    brandkit.emit(BRAND, "header", brandkit.header,
                  "Scale · Unit economics · DuckDB SQL", "Unit Economics by Channel",
                  "CAC, LTV, payback and contribution margin by acquisition channel for an online "
                  "fabric store. Simulated data.")
    brandkit.emit(BRAND, "arc", brandkit.arc, [
        "An online fabric store spends on Meta and Google to acquire customers.",
        "Which channels bring customers worth more than they cost, and how fast do they pay back?",
        "Retail margin from the real order costs, channel from the attribution table, every premise tested.",
        "Paid media pays back slowly and Meta only breaks even. Repeat purchase is what pays for acquisition.",
    ])
    return [BRAND / "header.svg", BRAND / "arc.svg"]


def build_all(refresh: bool = False) -> list[Path]:
    if refresh:
        reports.refresh()
    tables = reports.read()
    h = reports.headline_values(tables)
    return [
        headline(h),
        channel_ltv_cac(tables["channel_summary"], h),
        paid_cac_trend(tables["channel_monthly"], tables["yearly"]),
        ltv_cac_horizon(tables["ltv_curve"], h),
        sensitivity(tables["sensitivity"], h),
        *brand_panels(h),
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Draw the README figures from reports/.")
    parser.add_argument("--refresh", action="store_true", help="rewrite reports/ from data/processed first")
    args = parser.parse_args()
    for path in build_all(refresh=args.refresh):
        print(path.relative_to(ROOT))
