"""Unit-economics formulas.

Kept as pure functions so they can be tested directly and cited in the README
without a reader having to read SQL. Each returns ``None`` where the metric is
undefined, because an undefined metric is information and a silent zero is a
bug that reaches a slide deck.
"""

from __future__ import annotations


def contribution_margin(
    gmv: float,
    take_rate: float,
    psp_fee_rate: float,
    variable_support_cost: float,
    orders: int = 1,
) -> float:
    """Margin the marketplace keeps on `gmv`.

    commission        = gmv * take_rate
    payment cost      = gmv * psp_fee_rate   (charged on the full transaction)
    support cost      = variable_support_cost * orders
    """
    commission = gmv * take_rate
    payment_cost = gmv * psp_fee_rate
    support_cost = variable_support_cost * orders
    return commission - payment_cost - support_cost


def cac(spend: float | None, new_customers: int) -> float | None:
    """Cost to acquire one customer.

    `spend` is ``None`` for a channel that has no media line at all (organic,
    direct, referral). That is different from a paid channel that happened to
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
    """Months of contribution margin needed to repay acquisition.

    Returns ``None`` when the customer never repays, which is the honest answer
    and distinct from "repays very slowly".
    """
    if customer_acquisition_cost is None:
        return None
    if monthly_margin <= 0:
        return None
    return customer_acquisition_cost / monthly_margin


def break_even_cac(ltv: float, target_ratio: float = 1.0) -> float:
    """Highest CAC that still clears `target_ratio`.

    At target_ratio = 1 this is the break-even ceiling. Teams usually plan
    against 3.0, which is a convention, not a law.
    """
    return ltv / target_ratio
