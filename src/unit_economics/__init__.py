"""Unit economics of a marketplace, by acquisition channel."""

from .config import CHANNELS, MARGIN
from .metrics import cac, ltv_cac_ratio, payback_months

__all__ = ["CHANNELS", "MARGIN", "cac", "ltv_cac_ratio", "payback_months"]
