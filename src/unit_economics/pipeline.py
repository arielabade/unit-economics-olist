"""Build the analysis in DuckDB and write the outputs.

DuckDB rather than pandas because the joins and aggregations are set work, and
expressing them in SQL keeps the business logic reviewable by an analyst who
does not read Python. It runs in-process, so there is no warehouse to stand up
to reproduce the project.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from .channels import assign_channels, simulate_monthly_spend
from .config import ANALYSIS_END, ANALYSIS_START, BUDGET_BASE_START, MARGIN
from .ingest import DATA_DIR, download, verify

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql"
OUT_DIR = ROOT / "data" / "processed"


def _run_sql_file(con: duckdb.DuckDBPyConnection, name: str, params: dict) -> None:
    """Execute a .sql file after publishing `params` as session variables.

    DuckDB cannot bind prepared parameters inside CREATE VIEW, so the
    assumptions travel as session variables that the SQL reads with
    getvariable(). That keeps the .sql files parameterised and reviewable on
    their own, instead of being string-formatted from Python.
    """
    for key, value in params.items():
        con.execute(f"SET VARIABLE {key} = ?", [value])
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    for statement in [s.strip() for s in sql.split(";") if s.strip()]:
        con.execute(statement)


def build(force_download: bool = False) -> dict[str, pd.DataFrame]:
    download(force=force_download)
    verify()

    con = duckdb.connect()
    _run_sql_file(
        con,
        "01_staging.sql",
        {
            "orders_path": str(DATA_DIR / "olist_orders_dataset.csv"),
            "customers_path": str(DATA_DIR / "olist_customers_dataset.csv"),
            "items_path": str(DATA_DIR / "olist_order_items_dataset.csv"),
        },
    )
    _run_sql_file(
        con,
        "02_customer_economics.sql",
        {
            "take_rate": MARGIN.take_rate,
            "psp_fee_rate": MARGIN.psp_fee_rate,
            "variable_support_cost": MARGIN.variable_support_cost,
        },
    )

    # Channel membership and spend are simulated; see channels.py.
    customers = con.execute("SELECT DISTINCT customer_unique_id FROM customer_economics").df()
    customers["channel"] = assign_channels(customers["customer_unique_id"])
    con.register("customer_channel", customers)

    # Budget is sized from the previous month's net revenue, so the spend table
    # is built from the revenue curve rather than from acquisition counts.
    monthly_revenue = con.execute(
        """
        SELECT cohort_month AS month,
               SUM(gmv) * ? AS net_revenue
        FROM customer_economics
        WHERE cohort_month >= ?
        GROUP BY cohort_month ORDER BY cohort_month
        """,
        [MARGIN.take_rate, BUDGET_BASE_START],
    ).df()
    spend = simulate_monthly_spend(monthly_revenue)
    con.register("channel_spend", spend)

    _run_sql_file(con, "03_channel_economics.sql", {})

    outputs = {
        "customer_economics": con.execute("SELECT * FROM customer_economics").df(),
        # The launch months are excluded from the channel view: see config.py.
        "channel_monthly": con.execute(
            "SELECT * FROM channel_monthly WHERE month BETWEEN ? AND ? ORDER BY month, channel",
            [ANALYSIS_START, ANALYSIS_END],
        ).df(),
        "retention": con.execute(
            """
            SELECT orders AS orders_per_customer,
                   COUNT(*) AS customers,
                   ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_customers
            FROM customer_economics GROUP BY orders ORDER BY orders
            """
        ).df(),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        frame.to_parquet(OUT_DIR / f"{name}.parquet", index=False)
    con.close()
    return outputs


if __name__ == "__main__":
    result = build()
    for name, frame in result.items():
        print(f"\n=== {name}: {len(frame):,} rows")
        print(frame.head(8).to_string(index=False))
