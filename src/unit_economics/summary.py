"""Channel-level roll-up and the headline reading.

Kept separate from the SQL so the economics are computed through the tested
functions in `metrics`, not re-implemented in a second place.

Two populations meet in this table, and they are kept apart on purpose:

* **every cohort in the window** for what is known on the day a customer is
  acquired: spend, new customers, CAC, first-order margin;
* **mature cohorts only** (the whole LTV horizon observed) for what takes
  time to know: LTV, and the LTV/CAC built from those same cohorts' spend, so
  that LTV / CAC on a row is exactly the ratio shown next to it.
"""

from __future__ import annotations

import pandas as pd

from .config import CHANNELS, SMALL_SAMPLE_WINDOW
from .metrics import break_even_cac, cac, ltv_cac_ratio, payback_from_curve, ratio_of_sums

ROLLUPS = ("paid_total", "all")
ROLLUP_LABELS = {"paid_total": "Canais pagos (total)", "all": "Loja inteira"}


def label(channel: str) -> str:
    return ROLLUP_LABELS.get(channel) or CHANNELS.label(channel)


def channel_summary(comparisons: pd.DataFrame, ltv_curve: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per channel (and per roll-up) for the whole analysis window.

    ``comparisons`` is ``channel_comparisons`` (or any frame with its
    columns); ``ltv_curve`` is ``channel_ltv_curve`` and only feeds payback.
    """
    records = []
    for channel, rows in comparisons.groupby("channel", sort=False):
        is_paid = bool(rows["is_paid"].iloc[0])
        mature = rows[rows["is_mature"].astype(bool)]
        new_customers = float(rows["new_customers"].sum())
        mature_customers = float(mature["new_customers"].sum())

        # A channel with no media line is handed None, never 0.0: it has no
        # CAC, and therefore no LTV/CAC and no payback.
        spend = float(rows["spend"].sum()) if is_paid or channel == "all" else None
        mature_spend = float(mature["spend"].sum()) if spend is not None else None

        customer_cac = cac(spend, new_customers)
        mature_cac = cac(mature_spend, mature_customers)
        ltv = ratio_of_sums(mature["margin_in_horizon"], mature["new_customers"])
        first_margin = ratio_of_sums(rows["first_order_margin"], rows["new_customers"])
        ratio = ltv_cac_ratio(ltv, mature_cac) if ltv is not None else None

        payback = None
        if ltv_curve is not None and customer_cac is not None and channel != "all":
            curve = ltv_curve[ltv_curve["channel"] == channel].sort_values("months_since")
            payback = payback_from_curve(curve["cumulative_margin_per_customer"].tolist(), customer_cac)

        contribution = float(rows["contribution_margin"].sum())
        records.append({
            "channel": channel,
            "label": label(channel),
            "paid": is_paid,
            "spend": _round(spend),
            "new_customers": round(new_customers, 1),
            "orders": round(float(rows["orders"].sum()), 1),
            "revenue": round(float(rows["revenue"].sum()), 2),
            "contribution_margin": round(contribution, 2),
            "margin_after_media": round(contribution - (spend or 0.0), 2),
            "first_order_margin_per_customer": _round(first_margin),
            "cac": _round(customer_cac),
            # With every channel, how much of the first order's margin went on
            # acquiring the customer. Above 1, the first order does not pay
            # for itself and the customer has to come back.
            "cac_share_of_first_margin": (
                round(customer_cac / first_margin, 3)
                if customer_cac is not None and first_margin and first_margin > 0 else None
            ),
            "mature_customers": round(mature_customers, 1),
            "cac_mature_cohorts": _round(mature_cac),
            "ltv": _round(ltv),
            "ltv_cac_ratio": round(ratio, 2) if ratio is not None else None,
            "break_even_cac": _round(break_even_cac(ltv)) if ltv is not None else None,
            "cac_ceiling_at_3x": _round(break_even_cac(ltv, 3.0)) if ltv is not None else None,
            "payback_months": payback,
            "small_sample": new_customers < SMALL_SAMPLE_WINDOW,
        })
    summary = pd.DataFrame(records)
    order = {name: i for i, name in enumerate(ROLLUPS)}
    summary["_rollup"] = summary["channel"].map(order).fillna(-1)
    summary = summary.sort_values(["_rollup", "new_customers"], ascending=[True, False])
    return summary.drop(columns="_rollup").reset_index(drop=True)


def repeat_purchase_rate(customer_economics: pd.DataFrame) -> float:
    """Share of customers with more than one paid order."""
    return float((customer_economics["orders"] > 1).mean())


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None
