"""
Data service: warehouse bootstrap + shared DuckDB connection + claims loader.

On first boot, if the DuckDB warehouse doesn't exist, runs the full
ingest + transform pipeline automatically.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
WAREHOUSE_PATH = BASE_DIR / "data" / "warehouse" / "pharmaflow.duckdb"
CLAIMS_PATH = BASE_DIR / "data" / "synthetic" / "claims.csv"


def ensure_warehouse() -> None:
    """Run the full ingest + transform pipeline if the warehouse is missing."""
    if WAREHOUSE_PATH.exists():
        return

    WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    print("Warehouse not found — running ingest + transform pipeline...")

    from src.ingest.ingest_orange_book import run as ingest_ob
    from src.ingest.ingest_nadac import run as ingest_nadac
    from src.transform.build_orange_book_marts import run as build_marts
    from src.transform.build_equivalence_map import run as build_map

    ingest_ob()
    ingest_nadac()
    build_marts()
    build_map()
    print("Warehouse ready.")


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return a new read-write DuckDB connection to the warehouse."""
    ensure_warehouse()
    return duckdb.connect(str(WAREHOUSE_PATH))


def load_claims() -> pd.DataFrame:
    """Load synthetic claims; generate if the CSV is missing."""
    if not CLAIMS_PATH.exists():
        ensure_warehouse()
        from scripts.data.synthetic_generator import generate
        generate()
    return pd.read_csv(CLAIMS_PATH, dtype=str)
