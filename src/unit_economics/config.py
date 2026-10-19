"""Business assumptions and source configuration, in one place.

The data comes from the Tecelã Tecidos e-commerce database (the sibling
``ecommerce`` repository): a synthetic, deterministic replica of a Brazilian
online fabric store. It is a *retailer*, not a marketplace: the store keeps
the whole sale and pays for the goods, so contribution margin is built on
revenue minus real costs, not on a commission.

What the dataset provides, and what is still assumed, is split explicitly:

========================  =====================================================
From the dataset          Revenue, discounts, freight charged, product cost per
                          item, real freight cost, refunds and restocks,
                          payment method, acquisition channel (attribution
                          table), media spend per day and campaign.
Assumed (this module)     Payment-processing fee per method and a variable
                          per-order cost (packaging and service). The dataset
                          records neither.
========================  =====================================================

Nothing about channels or spend is simulated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# --- Source -------------------------------------------------------------------

#: Where the ``ecommerce`` repository lives. Only read, never written.
ECOMMERCE_DIR = Path(os.environ.get("ECOMMERCE_DIR", ROOT.parent / "ecommerce"))


def _dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            pairs[key.strip()] = value.strip()
    return pairs


def mysql_settings() -> dict:
    """Connection to the ecommerce MySQL, with that repository's own defaults.

    Precedence: environment variables, then ``ecommerce/.env``, then the
    defaults its docker-compose.yml uses.
    """
    dotenv = _dotenv(ECOMMERCE_DIR / ".env")
    return {
        "host": os.environ.get("ECOMMERCE_MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("ECOMMERCE_MYSQL_PORT", dotenv.get("MYSQL_PORT", "3336"))),
        "user": os.environ.get("ECOMMERCE_MYSQL_USER", "analista"),
        "password": os.environ.get("ECOMMERCE_MYSQL_PASSWORD", dotenv.get("MYSQL_PASSWORD", "analista123")),
        "database": os.environ.get("ECOMMERCE_MYSQL_DB", "tecidos"),
    }


#: Generator seed and scale the expected figures below belong to
#: (ecommerce/gerador/config.py and data/verdade/resumo.json).
SOURCE_SEED = 20231001
SOURCE_SCALE = 1.0

#: Full-table row counts produced by the generator at SOURCE_SEED and
#: SOURCE_SCALE. The ingest refuses to continue on any difference, so a
#: different seed, scale or a half-loaded database fails loudly.
EXPECTED_ROWS = {
    "clientes": 50_140,
    "cupons": 15,
    "pedidos": 143_633,
    "itens_pedido": 268_214,
    "pagamentos": 147_389,
    "fretes": 143_633,
    "devolucoes": 3_321,
    "movimentacoes_estoque": 267_389,
    "atribuicoes": 669_012,
    "meta_campanhas": 18,
    "meta_conjuntos": 29,
    "meta_anuncios": 117,
    "meta_metricas_diarias": 17_603,
    "google_campanhas": 7,
    "google_grupos_anuncio": 18,
    "google_metricas_diarias": 12_815,
}

#: Control sums: equal row counts with different values would still pass the
#: check above, so the money columns are pinned too (BRL, to the cent).
EXPECTED_SUMS = {
    ("pedidos", "total"): 42_013_147.72,
    ("itens_pedido", "total_item"): 40_185_705.20,
    ("fretes", "custo_real"): 3_703_961.49,
    ("meta_metricas_diarias", "investimento"): 2_503_503.11,
    ("google_metricas_diarias", "investimento"): 1_792_022.73,
}

# --- Analysis window ----------------------------------------------------------

#: The store's data runs from 2023-10-01 to 2026-10-13. October 2026 has 13
#: days, so it is left out of every monthly comparison rather than reported
#: as a collapse.
ANALYSIS_START = "2023-10"
ANALYSIS_END = "2026-09"
#: Last day with data. Cohort maturity is measured against it.
DATA_END = "2026-10-13"

#: LTV is the contribution margin a customer generates in their first N months
#: (month 0 = the acquisition month). Only cohorts observed for the whole
#: horizon carry an LTV: a younger cohort's figure would be biased down.
LTV_HORIZON_MONTHS = 12

#: Below this many new customers, a channel-month is reported but flagged as a
#: small sample instead of being read as a trend.
SMALL_SAMPLE_CUSTOMERS = 30
#: The same idea for a channel over the whole window.
SMALL_SAMPLE_WINDOW = 100

#: Attribution model that assigns each customer's first order to a channel.
#: last_click is what the source's own dbt marts use (dim_clientes).
ATTRIBUTION_MODEL = "last_click"
ATTRIBUTION_MODELS = ("last_click", "first_click", "linear", "data_driven")


# --- Assumptions (not in the dataset) -----------------------------------------


@dataclass(frozen=True)
class CostAssumptions:
    """Costs the dataset does not record.

    payment_fee_pix / payment_fee_card
        Share of the approved amount kept by the gateway. ``pagamentos`` holds
        the method, gateway and instalments, but not the fee. 1.0% for Pix and
        3.5% for card sit inside Brazilian gateways' published ranges.
    payment_fee_boleto
        Fixed BRL fee per paid boleto.
    variable_order_cost
        Packaging and customer service per paid order, in BRL.
    """

    payment_fee_pix: float = 0.010
    payment_fee_card: float = 0.035
    payment_fee_boleto: float = 3.50
    variable_order_cost: float = 3.00

    def as_sql_variables(self) -> dict[str, float]:
        return {
            "fee_pix": self.payment_fee_pix,
            "fee_card": self.payment_fee_card,
            "fee_boleto": self.payment_fee_boleto,
            "variable_order_cost": self.variable_order_cost,
        }


# --- Channels -----------------------------------------------------------------


@dataclass(frozen=True)
class Channels:
    """Acquisition channels, as the dataset's attribution table names them.

    Google Search is split into brand and non-brand with the campaign's
    ``campanha_marca`` flag: brand search mostly harvests people already
    looking for the store, and blending it with generic search would make
    generic search look cheaper than it is.

    A channel is *paid* when the dataset records media spend for it. Every
    other channel has no media line, so its CAC is undefined, never zero.
    """

    paid: tuple[str, ...] = (
        "paid_social",
        "paid_search_generic",
        "paid_search_brand",
        "performance_max",
        "paid_shopping",
        "paid_video",
    )
    # Orders with no session (ad blockers, WhatsApp sales) have no channel.
    untracked: str = "untracked"
    labels: dict[str, str] = field(
        default_factory=lambda: {
            "paid_social": "Meta Ads",
            "paid_search_generic": "Google Busca (genérica)",
            "paid_search_brand": "Google Busca (marca)",
            "performance_max": "Google Performance Max",
            "paid_shopping": "Google Shopping",
            "paid_video": "Google Demand Gen (vídeo)",
            "organic_search": "Busca orgânica",
            "direct": "Direto",
            "organic_social": "Social orgânico",
            "email": "E-mail",
            "referral": "Sites de referência",
            "whatsapp": "WhatsApp",
            "untracked": "Sem rastreio",
        }
    )

    def label(self, code: str) -> str:
        return self.labels.get(code, code)


#: Documented in the ecommerce README: all Meta prospecting was paused from
#: 2025-08-04 to 2025-08-24 as an incrementality test.
DOCUMENTED_EVENTS = {"2025-08": "Pausa da prospecção Meta (teste de incrementalidade)"}

#: A seasonal campaign marks a month when it ran for at least this many days in it.
SEASONAL_MIN_DAYS = 7

COSTS = CostAssumptions()
CHANNELS = Channels()
