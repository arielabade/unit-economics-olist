"""Figures for the README, and the small result tables they read.

The processed parquet files are git-ignored, because regenerating them means
downloading ~45MB from the dataset mirror. The *summaries* are not: running
``python -m unit_economics.figures`` writes them into ``reports/`` and then
draws from there, so a reader can rebuild every chart from the repository
alone, and the numbers quoted in the README have a committed source.

Run with ``python -m unit_economics.figures`` after ``unit_economics.pipeline``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import brandviz as bv
from .config import MARGIN
from .metrics import break_even_cac, contribution_margin
from .summary import channel_summary, repeat_purchase_rate

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
FIGURES = ROOT / "assets" / "figures"

#: Take rates to test the conclusion against. The modelled value sits in the
#: middle; the question is at which end the paid channels stop paying.
TAKE_RATES = (0.20, 0.175, 0.15, 0.125, 0.10, 0.08)


def refresh_reports() -> None:
    """Recompute the committed summary tables from the processed parquet files."""
    channel_monthly = pd.read_parquet(PROCESSED / "channel_monthly.parquet")
    customers = pd.read_parquet(PROCESSED / "customer_economics.parquet")
    retention = pd.read_parquet(PROCESSED / "retention.parquet")

    REPORTS.mkdir(exist_ok=True)
    summary = channel_summary(channel_monthly)
    summary.to_csv(REPORTS / "channel_summary.csv", index=False)
    retention.to_csv(REPORTS / "retention.csv", index=False)

    # Sensitivity is recomputed rather than stored from the pipeline: it is a
    # question about an assumption, so it belongs next to the assumption.
    gmv_per_customer = customers["gmv"].sum() / len(customers)
    orders_per_customer = customers["orders"].sum() / len(customers)
    rows = []
    for take_rate in TAKE_RATES:
        # Computed through the tested metric function rather than re-written
        # here, so a change to the margin definition cannot leave this chart
        # quietly describing the old one.
        margin = contribution_margin(
            gmv=gmv_per_customer,
            take_rate=take_rate,
            psp_fee_rate=MARGIN.psp_fee_rate,
            variable_support_cost=MARGIN.variable_support_cost,
            orders=orders_per_customer,
        )
        rows.append({
            "take_rate": take_rate,
            "margin_per_customer": round(margin, 2),
            "break_even_cac": round(break_even_cac(margin), 2),
            "cac_ceiling_at_3x": round(break_even_cac(margin, 3.0), 2),
            "modelled": take_rate == MARGIN.take_rate,
        })
    pd.DataFrame(rows).to_csv(REPORTS / "take_rate_sensitivity.csv", index=False)

    pd.DataFrame([{
        "customers": len(customers),
        "repeat_purchase_rate": round(repeat_purchase_rate(customers), 4),
        "gmv_per_customer": round(gmv_per_customer, 2),
    }]).to_csv(REPORTS / "headline.csv", index=False)


def repeat_purchase(retention: pd.DataFrame, headline_row: pd.Series) -> Path:
    """The fact the whole case rests on: almost nobody comes back.

    One bar carries 97% of the base, so a bar chart of counts would be one
    tall bar and nine invisible ones. The chart is therefore of the *tail*,
    with the single-purchase share stated rather than drawn.
    """
    tail = retention[retention["orders_per_customer"] <= 6].copy()
    once = tail[tail["orders_per_customer"] == 1]["pct_of_customers"].iloc[0]

    fig, ax = bv.panel(
        12.4, 5.2,
        title=f"{once:.1f}% of customers buy exactly once",
        subtitle="Share of customers by number of delivered orders. There is no second order to recover acquisition cost from.",
    )
    positions = np.arange(len(tail), dtype=float)
    ax.set_xlim(-0.6, len(tail) - 0.4)
    ax.set_ylim(0, 110)
    fig.canvas.draw()
    colors = [bv.CRIMSON if row.orders_per_customer == 1 else bv.COBALT
              for row in tail.itertuples()]
    bv.bars(ax, positions, tail["pct_of_customers"], colors,
            labels=[f"{value:.2f}%" for value in tail["pct_of_customers"]],
            label_pad=0.022)
    ax.set_xticks(positions, [str(int(value)) for value in tail["orders_per_customer"]])
    ax.set_xlabel("Delivered orders per customer")
    ax.set_ylabel("Share of customers")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0f}%")
    bv.annotate(
        ax,
        f"Everything to the right of the first bar\nadds up to {100 - once:.1f}% of customers",
        xy=(1.6, 8), xytext=(2.3, 52), color=bv.IVORY,
    )
    bv.clean(ax)
    return bv.save(fig, FIGURES / "repeat_purchase.svg")


def channel_economics(summary: pd.DataFrame) -> Path:
    """LTV/CAC by paid channel, against the planning target.

    Unpaid channels are absent rather than shown at zero: they have no media
    cost, so the ratio is undefined, and plotting them at zero would rank
    organic as the worst channel in the business.
    """
    paid = summary[summary["paid"]].sort_values("ltv_cac_ratio", ascending=False).reset_index(drop=True)

    fig, ax = bv.panel(
        12.4, 5.4,
        title="Only one paid channel pays for itself at the planning target",
        subtitle="Contribution margin per customer divided by the cost to acquire them. Channel membership and spend are SIMULATED.",
    )
    positions = np.arange(len(paid), dtype=float)
    ax.set_xlim(-0.6, len(paid) - 0.4)
    ax.set_ylim(0, paid["ltv_cac_ratio"].max() * 1.30)
    fig.canvas.draw()
    colors = [bv.COBALT if row.ltv_cac_ratio >= 3.0 else bv.SLATE for row in paid.itertuples()]
    bv.bars(ax, positions, paid["ltv_cac_ratio"], colors,
            labels=[f"{value:.2f}x" for value in paid["ltv_cac_ratio"]])
    ax.set_xticks(positions, paid["channel"])
    ax.set_ylabel("LTV / CAC")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0f}x")
    bv.reference_line(ax, 3.0, "3x planning target", where=0.985)
    bv.reference_line(ax, 1.0, "break-even", where=0.985)

    worst = paid.iloc[-1]
    bv.annotate(
        ax,
        f"{worst['channel']}: CAC of R$ {worst['cac']:.2f} against R$ "
        f"{worst['margin_per_customer']:.2f} of first-order margin\n"
        f"— {worst['acquisition_share_of_first_margin']:.0%} of the margin spent to acquire the customer",
        xy=(len(paid) - 1 - 0.3, worst["ltv_cac_ratio"] * 1.08),
        xytext=(0.45, paid["ltv_cac_ratio"].max() * 1.12), color=bv.IVORY,
    )
    bv.clean(ax)
    return bv.save(fig, FIGURES / "channel_economics.svg")


def take_rate_sensitivity(sensitivity: pd.DataFrame, summary: pd.DataFrame) -> Path:
    """Where the conclusion breaks, as a function of its most sensitive input.

    The take rate is assumed, not published. This chart is the honest answer
    to "how much does that assumption matter": each paid channel's CAC is a
    horizontal line, and the point where it crosses the break-even curve is
    the take rate below which that channel stops paying.
    """
    sensitivity = sensitivity.sort_values("take_rate").reset_index(drop=True)
    paid = summary[summary["paid"]].sort_values("cac")

    fig, ax = bv.panel(
        12.4, 5.6,
        title="How much the conclusion depends on the one number that is assumed",
        subtitle="Break-even CAC as a function of take rate, against what each paid channel actually costs",
    )
    rates = sensitivity["take_rate"] * 100
    ax.plot(rates, sensitivity["break_even_cac"], color=bv.COBALT, linewidth=2.4,
            marker="o", markersize=8, markeredgecolor=bv.CARBON, markeredgewidth=1.8,
            zorder=5, label="Break-even CAC")
    ax.plot(rates, sensitivity["cac_ceiling_at_3x"], color=bv.SLATE, linewidth=2.2,
            linestyle=(0, (5, 4)), zorder=4, label="CAC ceiling at the 3x target")

    # Two of the paid CACs are within R$ 0.40 of each other, so their labels
    # are staggered: the lines stay where the data is, the text does not overlap.
    span = paid["cac"].max() - paid["cac"].min()
    minimum_gap = max(span * 0.09, 0.9)
    last_label = None
    for row in paid.itertuples():
        ax.axhline(row.cac, color=bv.AMBER, linewidth=1.4, alpha=0.75, zorder=3)
        label_y = row.cac
        if last_label is not None and label_y - last_label < minimum_gap:
            label_y = last_label + minimum_gap
        last_label = label_y
        ax.plot([rates.max() + 0.08, rates.max() + 0.34], [row.cac, label_y],
                color=bv.GRID, linewidth=1.0, clip_on=False, zorder=3)
        ax.text(rates.max() + 0.40, label_y, f"{row.channel} CAC R$ {row.cac:.2f}",
                va="center", ha="left", fontsize=9.5, color=bv.IVORY)

    # Where the break-even curve crosses the most expensive paid channel is
    # the take rate at which paid acquisition stops paying for itself.
    dearest = paid["cac"].max()
    crossing = np.interp(dearest, sensitivity["break_even_cac"], rates)
    ax.plot([crossing], [dearest], "o", markersize=10, markerfacecolor=bv.CRIMSON,
            markeredgecolor=bv.CARBON, markeredgewidth=2.0, zorder=7)
    bv.annotate(
        ax,
        f"Below a {crossing:.1f}% take rate, paid search and\npaid social stop paying for themselves",
        xy=(crossing - 0.12, dearest), xytext=(rates.min() + 0.3, dearest * 1.42),
        color=bv.CRIMSON,
    )

    modelled = sensitivity[sensitivity["modelled"]]
    if not modelled.empty:
        point = modelled.iloc[0]
        ax.axvline(point["take_rate"] * 100, color=bv.STEEL, linewidth=1.2,
                   linestyle=(0, (3, 3)), zorder=2)
        ax.text(point["take_rate"] * 100, ax.get_ylim()[1], " modelled at 15% ",
                va="top", ha="left", fontsize=9.5, color=bv.STEEL)

    ax.set_xlabel("Marketplace take rate")
    ax.set_ylabel("Maximum CAC the business can pay")
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:.1f}%")
    ax.yaxis.set_major_formatter(lambda value, _: f"R$ {value:.0f}")
    ax.set_xlim(rates.min() - 0.4, rates.max() + 0.4)
    ax.legend(loc="upper left")
    fig.subplots_adjust(right=0.74)
    bv.clean(ax, axis="both", spines=("top", "right"))
    return bv.save(fig, FIGURES / "take_rate_sensitivity.svg")


def headline(summary: pd.DataFrame, headline_row: pd.Series, sensitivity: pd.DataFrame):
    """The three numbers the README leads with."""
    modelled = sensitivity[sensitivity["modelled"]].iloc[0]
    worst = summary[summary["paid"]].sort_values("ltv_cac_ratio").iloc[0]
    fig, _ = bv.kpi_strip([
        (f"{headline_row['repeat_purchase_rate']:.1%}",
         f"Of {headline_row['customers']:,.0f} customers ever place\na second order"),
        (f"R$ {modelled['break_even_cac']:.2f}",
         "First-order margin, and therefore the\nhard ceiling on what a customer can cost"),
        (f"{worst['acquisition_share_of_first_margin']:.0%}",
         f"Of that margin consumed by {worst['channel']}\nto acquire the customer"),
    ])
    return bv.save(fig, FIGURES / "headline.svg")


def build_all(refresh: bool = True) -> list[Path]:
    if refresh and PROCESSED.exists():
        refresh_reports()

    summary = pd.read_csv(REPORTS / "channel_summary.csv")
    retention = pd.read_csv(REPORTS / "retention.csv")
    sensitivity = pd.read_csv(REPORTS / "take_rate_sensitivity.csv")
    headline_row = pd.read_csv(REPORTS / "headline.csv").iloc[0]
    return [
        headline(summary, headline_row, sensitivity),
        repeat_purchase(retention, headline_row),
        channel_economics(summary),
        take_rate_sensitivity(sensitivity, summary),
    ]


if __name__ == "__main__":
    for path in build_all():
        print(path.relative_to(ROOT))
