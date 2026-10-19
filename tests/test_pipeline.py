"""The SQL pipeline, run end to end on the hand-built tables in conftest.py.

Margins below follow the default assumptions in config.py: Pix 1.0%,
card 3.5%, boleto R$3.50, R$3.00 of handling per order.
"""

import pandas as pd
import pytest

from unit_economics.config import COSTS
from unit_economics.metrics import contribution_margin, payment_fee
from unit_economics.pipeline import Settings, connect

from conftest import build_raw


@pytest.fixture
def con(raw_dir):
    connection = connect(Settings(), raw_dir)
    yield connection
    connection.close()


def _one(con, sql):
    return con.execute(sql).fetchone()


def _monthly(con, channel, month):
    frame = con.execute(
        "SELECT * FROM channel_monthly WHERE channel = ? AND month = ?", [channel, month]
    ).df()
    assert len(frame) == 1, (channel, month)
    return frame.iloc[0]


# --- staging ------------------------------------------------------------------

def test_accounts_with_the_same_cpf_are_one_person(con):
    (customer_1,) = _one(con, "SELECT customer_id FROM stg_customers WHERE cliente_id = 1")
    (customer_2,) = _one(con, "SELECT customer_id FROM stg_customers WHERE cliente_id = 2")
    assert customer_1 == customer_2 == 1


def test_staff_test_accounts_and_orders_are_excluded(con):
    assert _one(con, "SELECT COUNT(*) FROM stg_customers WHERE cliente_id = 4") == (0,)
    assert _one(con, "SELECT COUNT(*) FROM stg_orders WHERE order_id = 4") == (0,)


def test_only_paid_orders_count(con):
    # Order 5 was cancelled; order 2 was returned, but it was paid.
    orders = {row[0] for row in con.execute("SELECT order_id FROM stg_orders").fetchall()}
    assert orders == {1, 2, 3, 6, 7, 8}


def test_brand_and_generic_search_are_split_by_campaign(con):
    channels = dict(con.execute("SELECT order_id, channel FROM stg_order_channel").fetchall())
    assert channels[3] == "paid_search_brand"
    assert channels[8] == "paid_search_generic"


def test_order_without_a_session_is_untracked_and_with_one_is_direct(con):
    channels = dict(con.execute("SELECT order_id, channel FROM stg_order_channel").fetchall())
    assert channels[6] == "untracked"
    assert channels[7] == "direct"


def test_only_the_approved_payment_attempt_is_charged(con):
    method, amount = _one(con, "SELECT payment_method, amount_paid FROM stg_order_costs WHERE order_id = 7")
    assert (method, amount) == ("pix", 80.0)


# --- order and customer economics ---------------------------------------------

def test_retail_margin_uses_the_dataset_costs(con):
    # Order 1: R$200 revenue - R$60 goods - R$25 freight - R$2 Pix fee - R$3 handling.
    (margin,) = _one(con, "SELECT contribution_margin FROM order_economics WHERE order_id = 1")
    assert margin == pytest.approx(110.0)


def test_sql_margin_matches_the_tested_formula(con):
    row = con.execute("SELECT * FROM order_economics WHERE order_id = 2").df().iloc[0]
    expected = contribution_margin(
        revenue=row.revenue, product_cost=row.product_cost, freight_cost=row.freight_cost,
        payment_fee=payment_fee(row.payment_method, row.revenue, COSTS),
        variable_order_cost=COSTS.variable_order_cost,
        refunds=row.refunds, restocked_cost=row.restocked_cost,
    )
    # 100 - 40 - 10 - 30 refunded + 20 restocked - 3.50 card fee - 3.00 = 33.50
    assert row.contribution_margin == pytest.approx(expected) == pytest.approx(33.5)


def test_a_refused_return_refunds_nothing(con):
    (refunds,) = _one(con, "SELECT refunds FROM order_economics WHERE order_id = 7")
    assert refunds == 0


def test_a_second_account_order_is_a_repeat_not_a_new_customer(con):
    row = con.execute("SELECT * FROM customer_economics WHERE customer_id = 1").df().iloc[0]
    assert row.orders == 2
    assert row.first_order_margin == pytest.approx(110.0)
    assert row.margin_in_horizon == pytest.approx(143.5)
    assert row.days_to_second_order == 55


def test_legacy_customers_are_never_acquired(con):
    assert _one(con, "SELECT COUNT(*) FROM customer_channel WHERE customer_id = 3") == (0,)


def test_the_first_paid_order_defines_acquisition(con):
    # Person 5 cancelled in January and paid in February.
    (cohort,) = _one(con, "SELECT cohort_month FROM customer_economics WHERE customer_id = 5")
    assert cohort == "2024-02"


# --- channel economics ----------------------------------------------------------

def test_paid_channel_cac_divides_spend_by_new_customers(con):
    row = _monthly(con, "paid_social", "2024-01")
    assert row.spend == 150.0
    assert row.new_customers == 1
    assert row.cac == pytest.approx(150.0)
    assert row.cac_share_of_first_margin == pytest.approx(150.0 / 110.0)


def test_unpaid_channel_has_no_spend_and_no_cac(con):
    row = _monthly(con, "direct", "2024-01")
    assert pd.isna(row.spend)
    assert pd.isna(row.cac)
    assert pd.isna(row.ltv_cac)
    assert row.new_customers == 1


def test_untracked_customers_have_no_cac(con):
    row = _monthly(con, "untracked", "2024-02")
    assert row.new_customers == 1
    assert pd.isna(row.cac)


def test_spend_without_new_customers_has_no_cac(con):
    # Brand search spent R$20 in January but only re-acquired a legacy customer.
    row = _monthly(con, "paid_search_brand", "2024-01")
    assert row.spend == 20.0
    assert row.new_customers == 0
    assert pd.isna(row.cac)
    assert row.orders == 1  # the legacy customer's order is still activity


def test_spend_sits_next_to_customers_and_margin(con):
    row = _monthly(con, "paid_search_generic", "2024-01")
    # R$80 of spend, one customer whose first order made R$150 - 20 - 10 - 1.50 - 3 = R$115.50.
    assert (row.spend, row.new_customers) == (80.0, 1)
    assert row.contribution_margin == pytest.approx(115.5)
    assert row.margin_after_media == pytest.approx(35.5)
    assert row.payback_months == 1


def test_payback_is_null_when_the_cohort_has_not_repaid(con):
    # Meta's January customer has made 110 + 33.50 against R$150 of spend.
    assert pd.isna(_monthly(con, "paid_social", "2024-01").payback_months)





def test_small_samples_are_flagged(con):
    assert bool(_monthly(con, "paid_social", "2024-01").small_sample)


def test_attribution_model_changes_the_acquiring_channel(raw_dir):
    first = connect(Settings(attribution_model="first_click"), raw_dir)
    (channel,) = first.execute("SELECT channel FROM customer_channel WHERE customer_id = 1").fetchone()
    assert channel == "organic_search"
    first.close()


# --- the anti-circularity guard ---------------------------------------------------

def test_spend_does_not_depend_on_acquisitions(tmp_path):
    """Spend is read from the media tables and nothing else.

    Adding 9 more customers acquired by Meta must leave Meta's spend where it
    was, so CAC falls. If spend were ever sized from acquisitions, CAC would
    stay constant by construction and the analysis would return its input.
    """
    base = connect(Settings(), build_raw(tmp_path / "base"))
    more = connect(Settings(), build_raw(tmp_path / "more", extra_orders=9))
    query = "SELECT spend, new_customers, cac FROM channel_monthly WHERE channel = 'paid_social' AND month = '2024-01'"
    spend_base, customers_base, cac_base = base.execute(query).fetchone()
    spend_more, customers_more, cac_more = more.execute(query).fetchone()
    assert spend_more == spend_base == 150.0
    assert (customers_base, customers_more) == (1, 10)
    assert cac_more == pytest.approx(cac_base / 10)
