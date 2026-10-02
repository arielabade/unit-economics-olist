"""The simulation must be reproducible, and must not leak the answer."""

import pandas as pd
import pytest

from unit_economics.channels import assign_channel, assign_channels, simulate_monthly_spend
from unit_economics.config import CHANNELS


def test_channel_assignment_is_deterministic():
    assert assign_channel("customer-abc") == assign_channel("customer-abc")


def test_channel_assignment_matches_declared_mix():
    ids = pd.Series([f"customer-{i}" for i in range(40_000)])
    observed = assign_channels(ids).value_counts(normalize=True)
    for channel, expected in CHANNELS.weights.items():
        assert observed[channel] == pytest.approx(expected, abs=0.01)


def test_every_assignment_is_a_known_channel():
    ids = pd.Series([f"customer-{i}" for i in range(2_000)])
    assert set(assign_channels(ids)) <= set(CHANNELS.weights)


def _revenue(values):
    months = [f"2017-{i:02d}" for i in range(1, len(values) + 1)]
    return pd.DataFrame({"month": months, "net_revenue": values})


def test_first_month_has_no_spend_because_the_budget_lags():
    spend = simulate_monthly_spend(_revenue([100_000.0, 120_000.0, 140_000.0]))
    assert "2017-01" not in set(spend["month"])
    assert {"2017-02", "2017-03"} == set(spend["month"])


def test_budget_tracks_previous_month_revenue():
    flat = simulate_monthly_spend(_revenue([100_000.0] * 6))["spend"].sum()
    growing = simulate_monthly_spend(_revenue([100_000.0 * 1.5**i for i in range(6)]))["spend"].sum()
    assert growing > flat


def test_spend_is_independent_of_acquisitions():
    """The guard against a circular model.

    simulate_monthly_spend never sees how many customers were acquired, so CAC
    cannot collapse to a target CPA that was fed in. This test pins the
    signature: if spend ever starts depending on acquisitions, it breaks.
    """
    import inspect

    parameters = set(inspect.signature(simulate_monthly_spend).parameters)
    assert parameters == {"monthly_net_revenue"}


def test_simulation_is_reproducible_across_runs():
    revenue = _revenue([100_000.0, 110_000.0, 120_000.0])
    pd.testing.assert_frame_equal(simulate_monthly_spend(revenue), simulate_monthly_spend(revenue))
