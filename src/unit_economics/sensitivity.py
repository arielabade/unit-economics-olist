"""How much the conclusion depends on each premise.

Every premise that is a choice rather than a measurement is moved to a low
and a high value, the whole pipeline is rebuilt, and the paid channels'
LTV/CAC is read again. The premise with the widest swing is the one to pin
down before acting, and gets its own detailed view:

* ``tornado``           one row per premise: low, base, high and swing;
* ``horizon_curve``     LTV/CAC as a function of how many months of repeat
                        purchase are counted, per paid channel;
* ``attribution_table`` CAC and LTV/CAC per paid channel under every
                        attribution model in the dataset.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .config import ATTRIBUTION_MODELS, CHANNELS
from .pipeline import Settings, build
from .summary import channel_summary

def _premises(base: Settings):
    """(premise, label, low settings, high settings, low text, high text)."""
    c = base.costs
    alt_models = [m for m in ATTRIBUTION_MODELS if m != base.attribution_model]
    return [
        # Read on the same cohorts at both ends (see tornado): a 24-month LTV
        # exists only for the oldest cohorts, which were acquired more cheaply.
        ("ltv_horizon_months", "Meses de recompra contados no LTV", None, None, "6 meses", "24 meses"),
        ("attribution_model", "Modelo de atribuição do 1º pedido",
         [base.with_(attribution_model=m) for m in alt_models], None, None, None),
        ("payment_fee_card", "Taxa do cartão",
         base.with_(costs=replace(c, payment_fee_card=c.payment_fee_card * 0.5)),
         base.with_(costs=replace(c, payment_fee_card=c.payment_fee_card * 1.5)),
         f"{c.payment_fee_card * 50:.2f}%", f"{c.payment_fee_card * 150:.2f}%"),
        ("variable_order_cost", "Custo de embalagem e atendimento por pedido",
         base.with_(costs=replace(c, variable_order_cost=c.variable_order_cost * 0.5)),
         base.with_(costs=replace(c, variable_order_cost=c.variable_order_cost * 1.5)),
         f"R$ {c.variable_order_cost * 0.5:.2f}", f"R$ {c.variable_order_cost * 1.5:.2f}"),
        ("payment_fee_pix", "Taxa do Pix",
         base.with_(costs=replace(c, payment_fee_pix=c.payment_fee_pix * 0.5)),
         base.with_(costs=replace(c, payment_fee_pix=c.payment_fee_pix * 1.5)),
         f"{c.payment_fee_pix * 50:.2f}%", f"{c.payment_fee_pix * 150:.2f}%"),
        ("payment_fee_boleto", "Taxa do boleto",
         base.with_(costs=replace(c, payment_fee_boleto=c.payment_fee_boleto * 0.5)),
         base.with_(costs=replace(c, payment_fee_boleto=c.payment_fee_boleto * 1.5)),
         f"R$ {c.payment_fee_boleto * 0.5:.2f}", f"R$ {c.payment_fee_boleto * 1.5:.2f}"),
    ]


def _summary(settings: Settings, keep: dict | None = None) -> pd.DataFrame:
    outputs = build(settings, write=False)
    if keep is not None:
        keep.update(outputs)
    return channel_summary(outputs["channel_comparisons"], outputs["channel_ltv_curve"]).set_index("channel")


def _paid_ratio(summary: pd.DataFrame) -> float:
    return float(summary.loc["paid_total", "ltv_cac_ratio"])


def tornado(base: Settings = Settings()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Swing of the paid channels' LTV/CAC per premise, widest first.

    Also returns the per-channel summaries of every attribution model, which
    the attribution table reuses instead of rebuilding them.
    """
    base_outputs: dict = {}
    base_summary = _summary(base, base_outputs)
    base_value = _paid_ratio(base_summary)
    rows, by_model = [], {base.attribution_model: base_summary}
    for premise, text, low, high, low_text, high_text in _premises(base):
        if premise == "attribution_model":
            for settings in low:
                by_model[settings.attribution_model] = _summary(settings)
            values = {m: _paid_ratio(s) for m, s in by_model.items()}
            low_model = min(values, key=values.get)
            high_model = max(values, key=values.get)
            low_value, high_value = values[low_model], values[high_model]
            low_text, high_text = low_model, high_model
        elif premise == "ltv_horizon_months":
            # 6 and 24 months on the cohorts observed for 24: the horizon moves,
            # the customers do not. (Rebuilding at 6 and 24 would compare 31
            # cohorts with the 13 oldest and cheapest ones.)
            low_value, high_value, cohorts = same_cohorts(base_outputs, 6, 24)
            low_text, high_text = f"6 meses ({cohorts} coortes)", f"24 meses (as mesmas {cohorts})"
        else:
            low_value, high_value = _paid_ratio(_summary(low)), _paid_ratio(_summary(high))
        rows.append({
            "premise": premise,
            "label": text,
            "low_setting": low_text,
            "high_setting": high_text,
            "low": round(min(low_value, high_value), 2),
            "base": round(base_value, 2),
            "high": round(max(low_value, high_value), 2),
            "swing": round(abs(high_value - low_value), 2),
        })
    frame = pd.DataFrame(rows).sort_values("swing", ascending=False).reset_index(drop=True)
    models = pd.concat({m: s for m, s in by_model.items()}, names=["model"]).reset_index()
    return frame, models


def attribution_table(models: pd.DataFrame) -> pd.DataFrame:
    """CAC and LTV/CAC per paid channel, one column pair per model."""
    keep = list(CHANNELS.paid) + ["paid_total"]
    frame = models[models["channel"].isin(keep)][
        ["model", "channel", "label", "new_customers", "cac", "ltv_cac_ratio"]
    ]
    return frame.sort_values(["channel", "model"]).reset_index(drop=True)


def same_cohorts(outputs: dict[str, pd.DataFrame], short: int = 12, long: int = 24) -> tuple[float, float, int]:
    """Paid LTV/CAC after ``short`` and ``long`` months on the *same* cohorts.

    The cohorts observed for ``long`` months, read at both horizons: what the
    longer horizon adds once cohort mix is held still.
    """
    curve = outputs["channel_cohort_curve"]
    spend = outputs["channel_monthly"][["channel", "month", "spend"]].rename(columns={"month": "cohort_month"})
    paid = curve[curve["channel"].isin(CHANNELS.paid)].merge(spend, on=["channel", "cohort_month"], how="left")
    observed = paid.groupby("cohort_month")["months_since"].max() + 1
    cohorts = observed[observed >= long].index
    part = paid[paid["cohort_month"].isin(cohorts)]
    total_spend = part[part["months_since"] == 0]["spend"].sum()
    at = lambda k: part[part["months_since"] == k - 1]["cumulative_margin"].sum() / total_spend
    return round(at(short), 3), round(at(long), 3), len(cohorts)


def horizon_curve(outputs: dict[str, pd.DataFrame], max_months: int = 24) -> pd.DataFrame:
    """LTV/CAC after k months, for k = 1..max_months.

    At each k, only cohorts observed for at least k months enter, and their
    margin is divided by *their own* spend: numerator and denominator always
    describe the same customers. Older cohorts acquired more cheaply, so the
    long end of the curve flatters today's CAC; ``cohorts`` says how many
    cohorts stand behind each point. It stops at 24 months, where 13 cohorts
    remain; past that, a handful of launch-period cohorts would be the curve.
    """
    curve = outputs["channel_cohort_curve"]
    spend = outputs["channel_monthly"][["channel", "month", "spend"]].rename(columns={"month": "cohort_month"})
    paid = curve[curve["channel"].isin(CHANNELS.paid)].merge(spend, on=["channel", "cohort_month"], how="left")
    paid = pd.concat([paid, paid.assign(channel="paid_total")])
    observed = paid.groupby(["channel", "cohort_month"])["months_since"].max() + 1

    rows = []
    for channel, group in paid.groupby("channel"):
        months = observed.loc[channel]
        for k in range(1, max_months + 1):
            cohorts = months[months >= k].index
            if len(cohorts) == 0:
                break
            at_k = group[group["cohort_month"].isin(cohorts) & (group["months_since"] == k - 1)]
            acquired = group[group["cohort_month"].isin(cohorts) & (group["months_since"] == 0)]
            total_spend = acquired["spend"].sum()
            if total_spend <= 0:
                continue
            rows.append({
                "channel": channel,
                "months": k,
                "ltv_cac": round(at_k["cumulative_margin"].sum() / total_spend, 3),
                "margin_per_customer": round(at_k["cumulative_margin"].sum() / acquired["new_customers"].sum(), 2),
                "cac": round(total_spend / acquired["new_customers"].sum(), 2),
                "cohorts": len(cohorts),
            })
    return pd.DataFrame(rows)

