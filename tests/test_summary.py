"""Roll-up must preserve the undefined cases rather than flatten them."""

import pandas as pd

from unit_economics.summary import channel_summary, repeat_purchase_rate


def _monthly():
    return pd.DataFrame(
        [
            {"channel": "paid_search", "month": "2017-02", "new_customers": 100,
             "gmv": 10_000.0, "contribution_margin": 1_600.0, "spend": 800.0},
            {"channel": "organic_search", "month": "2017-02", "new_customers": 200,
             "gmv": 20_000.0, "contribution_margin": 3_200.0, "spend": None},
        ]
    )


def test_unpaid_channel_reports_no_cac_and_no_ratio():
    """The invariant is not "is None" but "is not a flattering zero".

    pandas stores a missing float as NaN, so the roll-up cannot return None
    itself. What must never happen is an unpaid channel reporting a CAC of 0.00
    and an infinite LTV/CAC, which would make organic look like the best
    performing channel in every deck it ever appears in.
    """
    row = channel_summary(_monthly()).set_index("channel").loc["organic_search"]
    assert pd.isna(row["cac"])
    assert row["cac"] != 0
    assert pd.isna(row["ltv_cac_ratio"])
    assert not row["paid"]  # numpy.bool_, so compare by value


def test_paid_channel_economics():
    row = channel_summary(_monthly()).set_index("channel").loc["paid_search"]
    assert row["cac"] == 8.0            # 800 / 100
    assert row["margin_per_customer"] == 16.0
    assert row["ltv_cac_ratio"] == 2.0  # 16 / 8
    assert row["acquisition_share_of_first_margin"] == 0.5


def test_break_even_ceiling_is_reported_for_every_channel():
    summary = channel_summary(_monthly())
    assert summary["break_even_cac"].notna().all()
    assert summary["cac_ceiling_at_3x"].notna().all()


def test_repeat_purchase_rate():
    customers = pd.DataFrame({"orders": [1, 1, 1, 2]})
    assert repeat_purchase_rate(customers) == 0.25
