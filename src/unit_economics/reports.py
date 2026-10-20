"""The committed result tables in ``reports/``.

The processed Parquet files are git-ignored, because regenerating them
needs the ecommerce database. The *summaries* are not: this module writes
them into ``reports/``, and everything a reader sees is drawn from there —
the README figures (``figures.py``), the README tables (``readme.py``) and
the static dashboard (``dashboard.py``). One source, so no number can say
one thing in the README and another on the dashboard.

Run with ``python -m unit_economics.reports`` after the pipeline. It also
rebuilds the pipeline a dozen times for the sensitivity analysis (~30 s).
"""

from __future__ import annotations

import pandas as pd

from .config import (
    ANALYSIS_END,
    ANALYSIS_START,
    ATTRIBUTION_MODEL,
    CHANNELS,
    COSTS,
    LTV_HORIZON_MONTHS,
    ROOT,
    SMALL_SAMPLE_CUSTOMERS,
)
from .metrics import ratio_of_sums
from .pipeline import OUT_DIR, OUTPUTS
from .sensitivity import attribution_table, horizon_curve, same_cohorts, tornado
from .summary import channel_summary, label

REPORTS = ROOT / "reports"

#: Fiscal-style years of the window, so "year 1 vs year 3" compares whole years.
YEARS = {"ano 1": ("2023-10", "2024-09"), "ano 2": ("2024-10", "2025-09"), "ano 3": ("2025-10", "2026-09")}

#: The pause, and the same two months a year earlier as the seasonal baseline.
PAUSE = ("2025-07", "2025-08")
PAUSE_BASELINE = ("2024-07", "2024-08")

MONTHLY_COLUMNS = [
    "channel", "label", "month", "is_paid", "spend", "new_customers", "orders", "revenue",
    "contribution_margin", "margin_after_media", "first_order_margin", "cac",
    "cac_share_of_first_margin", "ltv", "ltv_cac", "payback_months", "is_mature", "small_sample",
    "events", "spend_mom", "new_customers_mom", "revenue_mom", "margin_mom", "cac_mom",
    "spend_yoy", "new_customers_yoy", "revenue_yoy", "margin_yoy", "cac_yoy",
]


def load_processed() -> dict[str, pd.DataFrame]:
    missing = [n for n in OUTPUTS if not (OUT_DIR / f"{n}.parquet").exists()]
    if missing:
        raise FileNotFoundError(f"{missing} missing; run `python -m unit_economics.pipeline` first")
    return {name: pd.read_parquet(OUT_DIR / f"{name}.parquet") for name in OUTPUTS}


def yearly(comparisons: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, (start, end) in YEARS.items():
        window = comparisons[comparisons["month"].between(start, end)]
        for channel in ("paid_total", "all", *CHANNELS.paid):
            part = window[window["channel"] == channel]
            if part.empty:
                continue
            rows.append({
                "year": year, "start": start, "end": end, "channel": channel, "label": label(channel),
                "spend": round(part["spend"].sum(), 2),
                "new_customers": part["new_customers"].sum(),
                "revenue": round(part["revenue"].sum(), 2),
                "contribution_margin": round(part["contribution_margin"].sum(), 2),
                "cac": _r(ratio_of_sums(part["spend"], part["new_customers"])),
            })
    return pd.DataFrame(rows)


def meta_pause(comparisons: pd.DataFrame) -> pd.DataFrame:
    """New customers in the month before and the month of the pause, by channel."""
    rows = []
    for name, (before, during) in (("pausa 2025", PAUSE), ("mesmo período 2024", PAUSE_BASELINE)):
        for channel in comparisons["channel"].unique():
            part = comparisons[comparisons["channel"] == channel].set_index("month")
            b = part["new_customers"].get(before, 0.0)
            d = part["new_customers"].get(during, 0.0)
            rows.append({
                "period": name, "channel": channel, "label": label(channel),
                "month_before": before, "month_of": during,
                "new_customers_before": b, "new_customers_during": d,
                "spend_before": part["spend"].get(before), "spend_during": part["spend"].get(during),
            })
    return pd.DataFrame(rows)


def headline(summary: pd.DataFrame, pnl: pd.DataFrame, years: pd.DataFrame,
             pause: pd.DataFrame, retention: pd.DataFrame, sensitivity: pd.DataFrame,
             fixed: tuple[float, float, int]) -> pd.DataFrame:
    """The numbers the README and the dashboard quote, keyed by name."""
    s = summary.set_index("channel")
    r = retention.set_index("channel")
    y = years.set_index(["channel", "year"])
    paid, store, meta = s.loc["paid_total"], s.loc["all"], s.loc["paid_social"]

    def pause_drop(period, channels=None, exclude=None):
        part = pause[pause["period"] == period]
        part = part[~part["channel"].isin(["paid_total", "all"])]
        if channels is not None:
            part = part[part["channel"].isin(channels)]
        if exclude is not None:
            part = part[~part["channel"].isin(exclude)]
        return part["new_customers_during"].sum() - part["new_customers_before"].sum()

    top = sensitivity.iloc[0]
    values = {
        "window_start": ANALYSIS_START,
        "window_end": ANALYSIS_END,
        "months": pnl["month"].nunique(),
        "revenue": pnl["revenue"].sum(),
        "orders": pnl["orders"].sum(),
        "contribution_margin": pnl["contribution_margin"].sum(),
        "margin_rate": pnl["contribution_margin"].sum() / pnl["revenue"].sum(),
        "spend": pnl["spend"].sum(),
        "margin_after_media": pnl["margin_after_media"].sum(),
        "freight_subsidy": pnl["freight_cost"].sum() - pnl["freight_charged"].sum(),
        "freight_subsidy_rate": (pnl["freight_cost"].sum() - pnl["freight_charged"].sum()) / pnl["revenue"].sum(),
        "new_customers": store["new_customers"],
        "blended_cac": store["cac"],
        "paid_new_customers": paid["new_customers"],
        "paid_share_of_new_customers": paid["new_customers"] / store["new_customers"],
        "untracked_share_of_new_customers": s.loc["untracked", "new_customers"] / store["new_customers"],
        "paid_cac": paid["cac"],
        "paid_first_order_margin": paid["first_order_margin_per_customer"],
        "paid_cac_share_of_first_margin": paid["cac_share_of_first_margin"],
        "paid_ltv": paid["ltv"],
        "paid_ltv_cac": paid["ltv_cac_ratio"],
        "paid_payback_months": paid["payback_months"],
        "paid_cac_year1": y.loc[("paid_total", "ano 1"), "cac"],
        "paid_cac_year2": y.loc[("paid_total", "ano 2"), "cac"],
        "paid_cac_year3": y.loc[("paid_total", "ano 3"), "cac"],
        "spend_growth_y1_y3": y.loc[("paid_total", "ano 3"), "spend"] / y.loc[("paid_total", "ano 1"), "spend"] - 1,
        "paid_customers_growth_y1_y3": (y.loc[("paid_total", "ano 3"), "new_customers"]
                                        / y.loc[("paid_total", "ano 1"), "new_customers"] - 1),
        "revenue_growth_y1_y3": y.loc[("all", "ano 3"), "revenue"] / y.loc[("all", "ano 1"), "revenue"] - 1,
        "repeat_rate_horizon": r.loc["all", "repeat_rate_in_horizon"],
        "repeat_rate_90d": r.loc["all", "repeat_rate_90d"],
        "repeat_rate_horizon_min": r.loc[[c for c in r.index if c in CHANNELS.paid and not s.loc[c, "small_sample"]],
                                         "repeat_rate_in_horizon"].min(),
        "repeat_rate_horizon_max": r.loc[[c for c in r.index if c in CHANNELS.paid and not s.loc[c, "small_sample"]],
                                         "repeat_rate_in_horizon"].max(),
        "meta_spend": meta["spend"],
        "meta_spend_share": meta["spend"] / paid["spend"],
        "meta_cac": meta["cac"],
        "meta_first_order_margin": meta["first_order_margin_per_customer"],
        "meta_cac_share_of_first_margin": meta["cac_share_of_first_margin"],
        "meta_ltv": meta["ltv"],
        "meta_ltv_cac": meta["ltv_cac_ratio"],
        "meta_payback_months": meta["payback_months"],
        "meta_margin_after_media": meta["margin_after_media"],
        "brand_cac": s.loc["paid_search_brand", "cac"],
        "brand_ltv_cac": s.loc["paid_search_brand", "ltv_cac_ratio"],
        "generic_ltv_cac": s.loc["paid_search_generic", "ltv_cac_ratio"],
        "pmax_ltv_cac": s.loc["performance_max", "ltv_cac_ratio"],
        "shopping_ltv_cac": s.loc["paid_shopping", "ltv_cac_ratio"],
        "video_spend": s.loc["paid_video", "spend"],
        "video_new_customers": s.loc["paid_video", "new_customers"],
        "email_new_customers": s.loc["email", "new_customers"],
        "email_orders": s.loc["email", "orders"],
        "pause_meta_drop": pause_drop("pausa 2025", channels=["paid_social"]),
        "pause_others_drop": pause_drop("pausa 2025", exclude=["paid_social"]),
        "pause_store_change": _pause_change(pause, "pausa 2025"),
        "baseline_store_change": _pause_change(pause, "mesmo período 2024"),
        "baseline_others_drop": pause_drop("mesmo período 2024", exclude=["paid_social"]),
        "top_premise": top["premise"],
        "top_premise_low": top["low"],
        "top_premise_high": top["high"],
        "second_premise": sensitivity.iloc[1]["premise"],
        "second_premise_low": sensitivity.iloc[1]["low"],
        "second_premise_high": sensitivity.iloc[1]["high"],
        "same_cohorts_12": fixed[0],
        "same_cohorts_24": fixed[1],
        "same_cohorts_count": fixed[2],
        "costs_max_swing": sensitivity[sensitivity["premise"].str.startswith(("payment", "variable"))]["swing"].max(),
        "ltv_horizon_months": LTV_HORIZON_MONTHS,
        "attribution_model": ATTRIBUTION_MODEL,
        "small_sample_customers": SMALL_SAMPLE_CUSTOMERS,
        "fee_pix": COSTS.payment_fee_pix,
        "fee_card": COSTS.payment_fee_card,
        "fee_boleto": COSTS.payment_fee_boleto,
        "variable_order_cost": COSTS.variable_order_cost,
    }
    return pd.DataFrame([{"key": k, "value": _r(v, 4) if isinstance(v, float) else v} for k, v in values.items()])


def _pause_change(pause: pd.DataFrame, period: str) -> float:
    row = pause[(pause["period"] == period) & (pause["channel"] == "all")].iloc[0]
    return row["new_customers_during"] / row["new_customers_before"] - 1


def _r(value, digits: int = 2):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def refresh(outputs: dict[str, pd.DataFrame] | None = None) -> dict[str, pd.DataFrame]:
    outputs = outputs or load_processed()
    comparisons = outputs["channel_comparisons"]
    summary = channel_summary(comparisons, outputs["channel_ltv_curve"])
    sensitivity, models = tornado()
    years = yearly(comparisons)
    pause = meta_pause(comparisons)

    monthly = comparisons.assign(label=comparisons["channel"].map(label))[MONTHLY_COLUMNS]
    tables = {
        "channel_summary": summary,
        "channel_monthly": monthly.round(4),
        "monthly_pnl": outputs["monthly_pnl"].round(2),
        "retention": outputs["channel_retention"].assign(
            label=outputs["channel_retention"]["channel"].map(label)).round(4),
        "ltv_curve": horizon_curve(outputs).assign(label=lambda f: f["channel"].map(label)),
        "sensitivity": sensitivity,
        "attribution_models": attribution_table(models),
        "yearly": years,
        "meta_pause": pause,
        "events": outputs["month_events"].sort_values("month"),
    }
    tables["headline"] = headline(summary, outputs["monthly_pnl"], years, pause,
                                  outputs["channel_retention"], sensitivity, same_cohorts(outputs))

    REPORTS.mkdir(exist_ok=True)
    for name, frame in tables.items():
        frame.to_csv(REPORTS / f"{name}.csv", index=False)
    return tables


def read() -> dict[str, pd.DataFrame]:
    """The committed tables, as figures, README and dashboard read them."""
    names = ["channel_summary", "channel_monthly", "monthly_pnl", "retention", "ltv_curve", "sensitivity",
             "attribution_models", "yearly", "meta_pause", "events", "headline"]
    return {name: pd.read_csv(REPORTS / f"{name}.csv") for name in names}


def headline_values(tables: dict[str, pd.DataFrame] | None = None) -> dict:
    frame = (tables or read())["headline"]
    values = {}
    for key, value in zip(frame["key"], frame["value"]):
        try:
            values[key] = float(value)
        except (TypeError, ValueError):
            values[key] = value
    return values


if __name__ == "__main__":
    for name, frame in refresh().items():
        print(f"reports/{name}.csv  {len(frame):>4} rows")
