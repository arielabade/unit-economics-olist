"""The economics must hold, and undefined must stay undefined."""

import pytest

from unit_economics.metrics import (
    break_even_cac,
    cac,
    contribution_margin,
    ltv_cac_ratio,
    payback_months,
)


def test_contribution_margin_is_built_on_commission_not_gmv():
    # R$100 GMV at a 15% take rate, 2.5% payment cost on the full transaction
    # and R$1.50 of support: 15.00 - 2.50 - 1.50 = 11.00
    assert contribution_margin(100.0, 0.15, 0.025, 1.50) == pytest.approx(11.00)


def test_contribution_margin_charges_support_per_order():
    two_orders = contribution_margin(100.0, 0.15, 0.025, 1.50, orders=2)
    assert two_orders == pytest.approx(9.50)


def test_contribution_margin_can_be_negative_on_tiny_baskets():
    # A R$10 order does not cover the fixed support cost. The model must say so
    # rather than clamp at zero.
    assert contribution_margin(10.0, 0.15, 0.025, 1.50) < 0


def test_cac_is_undefined_without_a_media_line():
    # Organic and direct have no spend concept at all.
    assert cac(None, 500) is None


def test_cac_of_zero_spend_is_zero_not_undefined():
    # A paid channel that paused spend genuinely acquired at zero cost that
    # period. That is different from having no media line.
    assert cac(0.0, 500) == 0.0


def test_cac_is_undefined_without_customers():
    assert cac(10_000.0, 0) is None


def test_cac_divides_spend_by_customers():
    assert cac(10_000.0, 250) == pytest.approx(40.0)


def test_ltv_cac_ratio_is_undefined_without_cac():
    assert ltv_cac_ratio(50.0, None) is None


def test_ltv_cac_ratio_is_undefined_at_zero_cac():
    # Not infinity: an unpaid channel has no ratio to report.
    assert ltv_cac_ratio(50.0, 0.0) is None


def test_payback_never_happens_without_margin():
    assert payback_months(40.0, 0.0) is None
    assert payback_months(40.0, -5.0) is None


def test_payback_months_divides_cac_by_monthly_margin():
    assert payback_months(40.0, 10.0) == pytest.approx(4.0)


def test_break_even_cac_at_target_ratio():
    assert break_even_cac(16.0) == pytest.approx(16.0)
    assert break_even_cac(16.0, 3.0) == pytest.approx(16.0 / 3)
