"""Roll-up must preserve the undefined cases rather than flatten them."""

import pandas as pd
import pytest

from unit_economics.summary import channel_summary, repeat_purchase_rate


def _comparisons():
    base = {"first_order_revenue": 0.0, "orders": 0.0, "revenue": 0.0}
    return pd.DataFrame(
        [
            # A mature cohort and a young one for a paid channel.
            {**base, "channel": "paid_social", "month": "2024-01", "is_paid": True, "is_mature": True,
             "spend": 800.0, "new_customers": 100, "first_order_margin": 6_000.0,
             "margin_in_horizon": 16_000.0, "contribution_margin": 7_000.0},
            {**base, "channel": "paid_social", "month": "2026-08", "is_paid": True, "is_mature": False,
             "spend": 1_200.0, "new_customers": 100, "first_order_margin": 6_000.0,
             "margin_in_horizon": 7_000.0, "contribution_margin": 7_000.0},
            {**base, "channel": "organic_search", "month": "2024-01", "is_paid": False, "is_mature": True,
             "spend": None, "new_customers": 200, "first_order_margin": 12_000.0,
             "margin_in_horizon": 32_000.0, "contribution_margin": 14_000.0},
        ]
    )


def _curve():
    return pd.DataFrame({
        "channel": ["paid_social"] * 3,
        "months_since": [0, 1, 2],
        "cumulative_margin_per_customer": [60.0, 90.0, 160.0],
    })


def _row(channel):
    return channel_summary(_comparisons(), _curve()).set_index("channel").loc[channel]


def test_unpaid_channel_reports_no_cac_and_no_ratio():
    """The invariant is not "is None" but "is not a flattering zero".

    pandas stores a missing float as NaN, so the roll-up cannot return None
    itself. What must never happen is an unpaid channel reporting a CAC of 0.00
    and an infinite LTV/CAC, which would make organic look like the best
    performing channel in every deck it ever appears in.
    """
    row = _row("organic_search")
    assert pd.isna(row["cac"])
    assert row["cac"] != 0
    assert pd.isna(row["ltv_cac_ratio"])
    assert pd.isna(row["payback_months"])
    assert not row["paid"]  # numpy.bool_, so compare by value


def test_cac_pools_every_cohort_in_the_window():
    # (800 + 1,200) / 200 customers, not the mean of 8 and 12 per month.
    assert _row("paid_social")["cac"] == pytest.approx(10.0)


def test_ltv_and_its_ratio_use_only_mature_cohorts():
    row = _row("paid_social")
    assert row["ltv"] == pytest.approx(160.0)                 # 16,000 / 100
    assert row["cac_mature_cohorts"] == pytest.approx(8.0)    # 800 / 100
    assert row["ltv_cac_ratio"] == pytest.approx(20.0)        # 16,000 / 800


def test_cac_share_of_first_order_margin():
    # CAC R$10 against R$60 of first-order margin per customer.
    assert _row("paid_social")["cac_share_of_first_margin"] == pytest.approx(10.0 / 60.0, abs=1e-3)


def test_payback_reads_the_cumulative_curve():
    # CAC R$10 is covered in the acquisition month.
    assert _row("paid_social")["payback_months"] == 1


def test_break_even_ceiling_is_reported_for_every_channel():
    summary = channel_summary(_comparisons())
    assert summary["break_even_cac"].notna().all()
    assert summary["cac_ceiling_at_3x"].notna().all()


def test_repeat_purchase_rate():
    customers = pd.DataFrame({"orders": [1, 1, 1, 2]})
    assert repeat_purchase_rate(customers) == 0.25
