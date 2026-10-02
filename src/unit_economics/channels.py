"""SIMULATED acquisition channels and media spend.

================================ READ THIS =================================
Olist publishes no acquisition channel and no media spend. Everything in this
module is generated. It is NOT a measurement of Olist's real marketing.

Two deliberate choices keep the simulation honest:

1. Channel membership is a deterministic hash of ``customer_unique_id``, so it
   is stable across runs and across machines without storing a lookup table.

2. The monthly budget is a declared share of the PREVIOUS month's net revenue,
   not of the customers acquired this month. Sizing a budget from realised
   acquisitions would make CAC a constant by construction and the whole
   analysis circular: the model would return the target CPA it was fed. The
   one-month lag is also how budgets are planned in practice.

The consequence to keep in mind when reading results: channel-level findings
demonstrate the measurement framework. They are not findings about Olist. The
retention and margin results, which come from the real order data, are.
============================================================================
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .config import CHANNELS


def assign_channel(customer_unique_id: str) -> str:
    """Stable pseudo-random channel for a customer.

    A hash keeps the assignment reproducible without persisting a mapping, and
    without depending on row order or pandas version.
    """
    digest = hashlib.sha256(customer_unique_id.encode("utf-8")).digest()
    draw = int.from_bytes(digest[:8], "big") / 2**64
    cumulative = 0.0
    for channel, weight in CHANNELS.weights.items():
        cumulative += weight
        if draw < cumulative:
            return channel
    return list(CHANNELS.weights)[-1]


def assign_channels(customer_unique_ids: pd.Series) -> pd.Series:
    return customer_unique_ids.map(assign_channel)


def simulate_monthly_spend(monthly_net_revenue: pd.DataFrame) -> pd.DataFrame:
    """Media spend per paid channel per month.

    `monthly_net_revenue` must have columns ``month`` and ``net_revenue``. The
    budget for a month is a share of the PREVIOUS month's net revenue, so the
    first month of the series carries no spend. See the module docstring for
    why the lag matters.
    """
    rng = np.random.default_rng(CHANNELS.seed)
    series = monthly_net_revenue.sort_values("month").reset_index(drop=True)
    series["budget_base"] = series["net_revenue"].shift(1) * CHANNELS.marketing_intensity

    rows = []
    for _, record in series.iterrows():
        if pd.isna(record["budget_base"]):
            continue
        for channel, share in CHANNELS.budget_share.items():
            noise = rng.normal(1.0, CHANNELS.budget_noise_sd)
            spend = max(record["budget_base"] * share * noise, 0.0)
            rows.append({"month": record["month"], "channel": channel, "spend": round(spend, 2)})
    return pd.DataFrame(rows)
