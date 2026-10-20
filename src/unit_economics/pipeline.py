"""Build the analysis in DuckDB and write the outputs.

DuckDB rather than pandas because the joins and aggregations are set work, and
expressing them in SQL keeps the business logic reviewable by an analyst who
does not read Python. It runs in-process over the Parquet files the ingest
wrote, so there is no warehouse to stand up to reproduce the project.

The SQL files run in order, each building on the tables of the one before:

    01_staging  ->  02_customer_economics  ->  03_channel_economics
                ->  04_channel_comparisons ->  05_retention
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import duckdb
import pandas as pd

from .config import (
    ANALYSIS_END,
    ANALYSIS_START,
    ATTRIBUTION_MODEL,
    CHANNELS,
    COSTS,
    DATA_END,
    DOCUMENTED_EVENTS,
    LTV_HORIZON_MONTHS,
    ROOT,
    SEASONAL_MIN_DAYS,
    SMALL_SAMPLE_CUSTOMERS,
    CostAssumptions,
)
from .ingest import DATA_DIR, verify

SQL_DIR = ROOT / "sql"
OUT_DIR = ROOT / "data" / "processed"
SQL_FILES = (
    "01_staging.sql",
    "02_customer_economics.sql",
    "03_channel_economics.sql",
    "04_channel_comparisons.sql",
    "05_retention.sql",
)

#: Tables written to data/processed after a build.
OUTPUTS = (
    "customer_economics",
    "channel_monthly",
    "channel_comparisons",
    "channel_cohort_curve",
    "channel_ltv_curve",
    "channel_retention",
    "monthly_totals",
    "monthly_pnl",
    "month_events",
)


@dataclass(frozen=True)
class Settings:
    """Everything a build depends on. Sensitivity runs change one field."""

    costs: CostAssumptions = COSTS
    attribution_model: str = ATTRIBUTION_MODEL
    ltv_horizon_months: int = LTV_HORIZON_MONTHS

    def with_(self, **changes) -> "Settings":
        return replace(self, **changes)

    def sql_variables(self, raw_dir: Path) -> dict:
        return {
            "raw_dir": str(raw_dir),
            "attribution_model": self.attribution_model,
            "ltv_horizon_months": self.ltv_horizon_months,
            "data_end": DATA_END,
            "analysis_start": ANALYSIS_START,
            "analysis_end": ANALYSIS_END,
            "small_sample": SMALL_SAMPLE_CUSTOMERS,
            "seasonal_min_days": SEASONAL_MIN_DAYS,
            "paid_channels": list(CHANNELS.paid),
            **self.costs.as_sql_variables(),
        }


def run_sql_file(con: duckdb.DuckDBPyConnection, name: str) -> None:
    """Execute one .sql file. Its parameters are already session variables.

    DuckDB cannot bind prepared parameters inside CREATE TABLE AS, so the
    settings travel as session variables that the SQL reads with
    getvariable(). That keeps the .sql files parameterised and reviewable on
    their own, instead of being string-formatted from Python.
    """
    con.execute((SQL_DIR / name).read_text(encoding="utf-8"))


def connect(settings: Settings = Settings(), raw_dir: Path = DATA_DIR,
            upto: str | None = None) -> duckdb.DuckDBPyConnection:
    """An in-memory database with every SQL file run, up to ``upto`` inclusive."""
    con = duckdb.connect()
    for key, value in settings.sql_variables(raw_dir).items():
        con.execute(f"SET VARIABLE {key} = ?", [value])
    events = pd.DataFrame(
        [{"month": month, "event": event} for month, event in DOCUMENTED_EVENTS.items()],
        columns=["month", "event"],
    )
    con.register("documented_events", events)
    for name in SQL_FILES:
        run_sql_file(con, name)
        if upto and name.startswith(upto):
            break
    return con


def build(settings: Settings = Settings(), raw_dir: Path = DATA_DIR,
          write: bool = True) -> dict[str, pd.DataFrame]:
    if raw_dir == DATA_DIR:
        verify(raw_dir)
    con = connect(settings, raw_dir)
    outputs = {name: con.execute(f"SELECT * FROM {name}").df() for name in OUTPUTS}
    con.close()
    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for name, frame in outputs.items():
            frame.to_parquet(OUT_DIR / f"{name}.parquet", index=False)
    return outputs


if __name__ == "__main__":
    result = build()
    for name, frame in result.items():
        print(f"\n=== {name}: {len(frame):,} rows")
        print(frame.head(6).to_string(index=False))
