"""Fetch the Olist CSVs.

The canonical dataset lives on Kaggle behind a login. This project reads a
public mirror of the same files so that anyone can clone the repository and
reproduce the analysis without credentials. Row counts are asserted against the
published figures so a swapped or truncated mirror fails loudly instead of
quietly changing the results.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from .config import DATA_SOURCE, OLIST_TABLES

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

# Published row counts for the Olist Brazilian E-Commerce dataset.
EXPECTED_ROWS = {
    "olist_customers_dataset": 99_441,
    "olist_orders_dataset": 99_441,
    "olist_order_items_dataset": 112_650,
    "olist_order_payments_dataset": 103_886,
}


def download(force: bool = False) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for table in OLIST_TABLES:
        target = DATA_DIR / f"{table}.csv"
        if target.exists() and not force:
            continue
        print(f"downloading {table}.csv")
        urllib.request.urlretrieve(f"{DATA_SOURCE}/{table}.csv", target)
    return DATA_DIR


def verify() -> dict[str, int]:
    """Fail loudly if the mirror does not match the published dataset."""
    counts = {}
    for table, expected in EXPECTED_ROWS.items():
        path = DATA_DIR / f"{table}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run `python -m unit_economics.ingest`")
        with path.open("r", encoding="utf-8") as fh:
            rows = sum(1 for _ in fh) - 1  # header
        if rows != expected:
            raise ValueError(f"{table}: expected {expected} rows, found {rows}")
        counts[table] = rows
    return counts


if __name__ == "__main__":
    download()
    for table, rows in verify().items():
        print(f"{table:38} {rows:>8,} rows  ok")
