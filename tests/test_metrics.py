"""The economics must hold, and undefined must stay undefined."""

import pytest

from unit_economics.config import CostAssumptions
from unit_economics.metrics import (
    break_even_cac,
    cac,
    contribution_margin,
    ltv_cac_ratio,
    payback_from_curve,
    payback_months,
    payment_fee,
    ratio_of_sums,
)


def test_contribution_margin_is_built_on_the_sale_less_costs():
    # A retailer keeps the sale: R$200 - R$60 goods - R$25 freight - R$2 fee - R$3 handling.
    assert contribution_margin(200.0, 60.0, 25.0, 2.0, 3.0) == pytest.approx(110.0)


def test_contribution_margin_charges_refunds_and_credits_restocked_goods():
    # R$30 goes back to the customer; the item returns to stock, recovering R$20 of cost.
    margin = contribution_margin(100.0, 40.0, 10.0, 3.5, 3.0, refunds=30.0, restocked_cost=20.0)
    assert margin == pytest.approx(33.5)


def test_contribution_margin_can_be_negative_when_free_shipping_costs_more():
    # A small order with free shipping: the carrier costs more than the goods earn.
    assert contribution_margin(40.0, 22.0, 18.0, 0.4, 3.0) < 0


def test_payment_fee_by_method():
    costs = CostAssumptions(payment_fee_pix=0.01, payment_fee_card=0.035, payment_fee_boleto=3.5)
    assert payment_fee("pix", 200.0, costs) == pytest.approx(2.0)
    assert payment_fee("cartao_credito", 200.0, costs) == pytest.approx(7.0)
    assert payment_fee("boleto", 200.0, costs) == pytest.approx(3.5)  # fixed, not a share
    assert payment_fee(None, 200.0, costs) == 0.0


def test_cac_is_undefined_without_a_media_line():
    # Organic, direct and e-mail have no spend concept at all.
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


def test_payback_from_curve_counts_the_acquisition_month():
    # The first order alone covers a R$80 CAC: one month of margin.
    assert payback_from_curve([115.5, 115.5], 80.0) == 1
    # Repaid in the third month.
    assert payback_from_curve([60.0, 90.0, 150.0], 120.0) == 3


def test_payback_from_curve_is_undefined_when_not_repaid_or_without_cac():
    assert payback_from_curve([110.0, 143.5], 150.0) is None
    assert payback_from_curve([110.0], None) is None


def test_break_even_cac_at_target_ratio():
    assert break_even_cac(16.0) == pytest.approx(16.0)
    assert break_even_cac(16.0, 3.0) == pytest.approx(16.0 / 3)


def test_rates_are_ratios_of_sums_not_means_of_rates():
    # A quiet month (R$1,000 for 10 customers) and Black Friday (R$9,000 for
    # 300): CAC is 10,000 / 310, not the mean of 100 and 30.
    assert ratio_of_sums([1_000, 9_000], [10, 300]) == pytest.approx(10_000 / 310)
    assert ratio_of_sums([1.0], [0]) is None


def test_ratio_of_sums_skips_missing_values():
    # A month with spend and nobody acquired has no margin to add.
    assert ratio_of_sums([259.0, float("nan"), None], [2, 0, 0]) == pytest.approx(129.5)
