"""
Reads NADAC.csv (CMS comma-delimited pricing file) into DuckDB raw_nadac.nadac_prices.

Run directly:  python -m src.ingest.ingest_nadac
"""

from pathlib import Path
from datetime import date

import pandas as pd
import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
NADAC_PATH = BASE_DIR / "NADAC.csv"
WAREHOUSE_PATH = BASE_DIR / "data" / "warehouse" / "pharmaflow.duckdb"

INGEST_DATE = date.today().isoformat()

# Canonical column rename map: CSV header → snake_case
_COL_MAP = {
    "NDC Description": "ndc_description",
    "NDC": "ndc",
    "NADAC Per Unit": "nadac_per_unit",
    "Effective Date": "effective_date",
    "Pricing Unit": "pricing_unit",
    "Pharmacy Type Indicator": "pharmacy_type",
    "OTC": "otc",
    "Explanation Code": "explanation_code",
    "Classification for Rate Setting": "classification",
    "Corresponding Generic Drug NADAC Per Unit": "generic_nadac_per_unit",
    "Corresponding Generic Drug Effective Date": "generic_effective_date",
    "As of Date": "as_of_date",
}


def run() -> None:
    df = pd.read_csv(NADAC_PATH, dtype=str, keep_default_na=False)
    df.rename(columns=_COL_MAP, inplace=True)

    # Coerce numeric columns; leave as NaN where unparseable
    df["nadac_per_unit"] = pd.to_numeric(df["nadac_per_unit"], errors="coerce")
    df["generic_nadac_per_unit"] = pd.to_numeric(df["generic_nadac_per_unit"], errors="coerce")

    df["ndc_description"] = df["ndc_description"].str.strip().str.upper()
    df["classification"] = df["classification"].str.strip().str.upper()
    df["pricing_unit"] = df["pricing_unit"].str.strip().str.upper()
    df["ingest_date"] = INGEST_DATE

    con = duckdb.connect(str(WAREHOUSE_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw_nadac")
    con.execute("CREATE OR REPLACE TABLE raw_nadac.nadac_prices AS SELECT * FROM df")

    count = con.execute("SELECT count(*) FROM raw_nadac.nadac_prices").fetchone()[0]
    print(f"NADAC ingested: {count} rows")
    con.close()


if __name__ == "__main__":
    run()
