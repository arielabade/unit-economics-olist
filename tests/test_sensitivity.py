"""Sensitivity must move one premise at a time and compare like with like."""

import pytest

from unit_economics import sensitivity
from unit_economics.pipeline import Settings, build


def test_tornado_moves_every_premise_and_ranks_by_swing(raw_dir, monkeypatch):
    monkeypatch.setattr(sensitivity, "build", lambda settings, write=False: build(settings, raw_dir, write=False))
    frame, models = sensitivity.tornado(Settings())
    assert set(frame["premise"]) == {
        "ltv_horizon_months", "attribution_model", "payment_fee_card",
        "variable_order_cost", "payment_fee_pix", "payment_fee_boleto",
    }
    assert list(frame["swing"]) == sorted(frame["swing"], reverse=True)
    assert frame["base"].nunique() == 1
    assert (frame["low"] <= frame["high"]).all()
    assert set(models["model"]) == {"last_click", "first_click", "linear", "data_driven"}


def test_horizon_curve_divides_each_cohorts_margin_by_its_own_spend(raw_dir):
    outputs = build(Settings(), raw_dir, write=False)
    curve = sensitivity.horizon_curve(outputs).set_index(["channel", "months"])
    # Month 1, paid channels: January cohorts made 110 (Meta) + 115.50
    # (generic search) against R$150 + R$80 + R$20 (brand, no new customer):
    # brand's R$20 bought nobody, so it does not enter any cohort's spend.
    first = curve.loc[("paid_total", 1)]
    assert first["ltv_cac"] == pytest.approx((110.0 + 115.5) / (150.0 + 80.0), abs=1e-3)
    # Meta's January customer bought again in March (month 3 counts it).
    assert curve.loc[("paid_social", 3), "margin_per_customer"] == pytest.approx(143.5)
