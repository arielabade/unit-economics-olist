"""Unit-economics formulas.

Kept as pure functions so they can be tested directly and cited in the README
without a reader having to read SQL. Each returns ``None`` where the metric is
undefined, because an undefined metric is information and a silent zero is a
bug that reaches a slide deck.

The SQL in ``sql/02`` and ``sql/03`` applies the same definitions row by row;
``tests/test_pipeline.py`` checks that the two agree on a hand-built order.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .config import COSTS, CostAssumptions


def payment_fee(method: str | None, amount_paid: float, costs: CostAssumptions = COSTS) -> float:
    """Gateway fee on one paid order. The rates are assumptions (config.py).

    Pix and card are charged as a share of the amount; boleto as a fixed fee.
    An order with no approved payment pays no fee.
    """
    if method == "pix":
        return amount_paid * costs.payment_fee_pix
    if method == "cartao_credito":
        return amount_paid * costs.payment_fee_card
    if method == "boleto":
        return costs.payment_fee_boleto
    return 0.0


def contribution_margin(
    revenue: float,
    product_cost: float,
    freight_cost: float,
    payment_fee: float,
    variable_order_cost: float,
    refunds: float = 0.0,
    restocked_cost: float = 0.0,
) -> float:
    """What a retailer keeps from one order before media spend.

    revenue         products - discount + freight charged to the customer
    product_cost    quantity x unit cost of the goods sold
    freight_cost    what the carrier really charged (often above what the
                    customer paid: free shipping is a cost, not a discount)
    refunds         money returned on an approved return
    restocked_cost  product cost recovered when the returned item went back
                    to stock
    """
    return (
        revenue
        - product_cost
        - freight_cost
        - refunds
        + restocked_cost
        - payment_fee
        - variable_order_cost
    )


def cac(spend: float | None, new_customers: float) -> float | None:
    """Cost to acquire one customer.

    `spend` is ``None`` for a channel that has no media line at all (organic,
    direct, e-mail). That is different from a paid channel that happened to
    spend 0.00 in a period, which legitimately yields a CAC of zero, so the two
    cases are kept apart rather than collapsed.

    Also undefined when the channel acquired nobody: dividing by zero customers
    is not an infinite CAC, it is an unanswerable question.
    """
    if spend is None or new_customers <= 0:
        return None
    return spend / new_customers


def ltv_cac_ratio(ltv: float, customer_acquisition_cost: float | None) -> float | None:
    """How many times the acquisition cost is returned over the measured life.

    Undefined without a CAC: an unpaid channel does not have an infinite ratio,
    it has no ratio.
    """
    if customer_acquisition_cost is None or customer_acquisition_cost <= 0:
        return None
    return ltv / customer_acquisition_cost


def payback_months(
    customer_acquisition_cost: float | None,
    monthly_margin: float,
) -> float | None:
    """Months of contribution margin needed to repay acquisition, at a flat rate.

    Returns ``None`` when the customer never repays, which is the honest answer
    and distinct from "repays very slowly".
    """
    if customer_acquisition_cost is None:
        return None
    if monthly_margin <= 0:
        return None
    return customer_acquisition_cost / monthly_margin


def payback_from_curve(
    cumulative_margin: Sequence[float],
    customer_acquisition_cost: float | None,
) -> int | None:
    """Months of margin needed to cover the CAC, counting the acquisition month.

    ``cumulative_margin[k]`` is the margin per customer accumulated by the end
    of month k, with month 0 the acquisition month, so a result of 1 means the
    acquisition month alone paid for the customer. ``None`` means not repaid
    within the months observed, which is not the same as "never".
    """
    if customer_acquisition_cost is None:
        return None
    for month, margin in enumerate(cumulative_margin):
        if margin >= customer_acquisition_cost:
            return month + 1
    return None


def break_even_cac(ltv: float, target_ratio: float = 1.0) -> float:
    """Highest CAC that still clears `target_ratio`.

    At target_ratio = 1 this is the break-even ceiling. Teams usually plan
    against 3.0, which is a convention, not a law.
    """
    return ltv / target_ratio


def ratio_of_sums(numerators: Iterable[float], denominators: Iterable[float]) -> float | None:
    """sum(numerators) / sum(denominators): how every rate here is pooled.

    Averaging monthly CACs gives a quiet month with 20 customers the same say
    as Black Friday with 1,800. Pooling the sums weights each month by what
    actually happened in it.
    """
    top, bottom = sum(numerators), sum(denominators)
    if bottom == 0:
        return None
    return top / bottom
