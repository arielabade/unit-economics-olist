"""Channel-level roll-up and the headline reading.

Kept separate from the SQL so the economics are computed through the tested
functions in `metrics`, not re-implemented in a second place.
"""

from __future__ import annotations

import pandas as pd

from .config import CHANNELS
from .metrics import break_even_cac, cac, ltv_cac_ratio


def channel_summary(channel_monthly: pd.DataFrame) -> pd.DataFrame:
    """One row per channel for the whole analysis window."""
    grouped = (
        channel_monthly.groupby("channel")
        .agg(
            new_customers=("new_customers", "sum"),
            gmv=("gmv", "sum"),
            contribution_margin=("contribution_margin", "sum"),
            spend=("spend", "sum"),
        )
        .reset_index()
    )

    records = []
    for row in grouped.itertuples():
        is_paid = row.channel in CHANNELS.paid_channels
        # An unpaid channel has no media line, so it is handed None rather than
        # 0.0: it has no CAC, and therefore no LTV/CAC ratio.
        spend = float(row.spend) if is_paid else None
        margin_per_customer = row.contribution_margin / row.new_customers
        customer_cac = cac(spend, int(row.new_customers))
        records.append(
            {
                "channel": row.channel,
                "paid": is_paid,
                "new_customers": int(row.new_customers),
                "gmv": round(row.gmv, 2),
                "contribution_margin": round(row.contribution_margin, 2),
                "margin_per_customer": round(margin_per_customer, 2),
                "spend": round(spend, 2) if spend is not None else None,
                "cac": round(customer_cac, 2) if customer_cac is not None else None,
                "ltv_cac_ratio": (
                    round(value, 2)
                    if (value := ltv_cac_ratio(margin_per_customer, customer_cac)) is not None
                    else None
                ),
                # With a 97% single-purchase base there is no second order to
                # recover from, so the question is not "how many months to
                # payback" but "how much of the first order's margin did
                # acquisition consume".
                "acquisition_share_of_first_margin": (
                    round(customer_cac / margin_per_customer, 3)
                    if customer_cac is not None and margin_per_customer > 0
                    else None
                ),
                "break_even_cac": round(break_even_cac(margin_per_customer), 2),
                "cac_ceiling_at_3x": round(break_even_cac(margin_per_customer, 3.0), 2),
            }
        )
    return pd.DataFrame(records).sort_values("new_customers", ascending=False).reset_index(drop=True)


def repeat_purchase_rate(customer_economics: pd.DataFrame) -> float:
    """Share of customers with more than one delivered order."""
    return float((customer_economics["orders"] > 1).mean())
