"""DuckDB read-oriented analytics. Rebuilds from SQLite operational records."""

import os
from pathlib import Path

import duckdb

from backend.database.sqlite import DB_PATH

ANALYTICS_PATH = Path(os.getenv("FLOWPAY_DUCKDB_PATH", "/data/flowpayai.duckdb"))


def connection():
    ANALYTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(ANALYTICS_PATH))


def refresh():
    import sqlite3

    source = sqlite3.connect(DB_PATH)
    con = connection()
    try:
        for table in (
            "workflow_executions",
            "payment_orders",
            "audit_events",
            "products",
        ):
            df = __import__("pandas").read_sql_query(f"SELECT * FROM {table}", source)
            con.register("source_df", df)
            con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM source_df")
            con.unregister("source_df")
    finally:
        source.close()
        con.close()


def query(sql, params=None):
    con = connection()
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()
