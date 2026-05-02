"""
Reads Orange_book_data_files/ (tilde-delimited FDA text files) into DuckDB raw_fda.* tables
and writes parquet intermediates to data/processed/.

Run directly:  python -m src.ingest.ingest_orange_book
"""

from pathlib import Path
from datetime import date

import pandas as pd
import duckdb

BASE_DIR = Path(__file__).resolve().parents[2]
OB_DIR = BASE_DIR / "Orange_book_data_files"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
WAREHOUSE_PATH = BASE_DIR / "data" / "warehouse" / "pharmaflow.duckdb"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

INGEST_DATE = date.today().isoformat()

PRODUCTS_COLUMNS = [
    "ingredient",
    "dosage_form_route",
    "trade_name",
    "applicant",
    "strength",
    "appl_type",
    "appl_no",
    "product_no",
    "te_code",
    "approval_date",
    "rld",
    "rs",
    "type",
    "applicant_full_name",
]

PATENT_COLUMNS = [
    "appl_type",
    "appl_no",
    "product_no",
    "patent_no",
    "patent_expire_date",
    "drug_substance_flag",
    "drug_product_flag",
    "patent_use_code",
    "delist_flag",
    "submission_date",
]

EXCLUSIVITY_COLUMNS = [
    "appl_type",
    "appl_no",
    "product_no",
    "exclusivity_code",
    "exclusivity_date",
]


def _read_ob_file(path: Path, columns: list[str]) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        sep="~",
        dtype=str,
        encoding="latin1",
        keep_default_na=False,
        header=0,
    )
    # Rename columns to snake_case; header row uses mixed case / special chars
    df.columns = columns[: len(df.columns)]
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    df["ingest_date"] = INGEST_DATE
    return df


def run() -> None:
    products = _read_ob_file(OB_DIR / "products.txt", PRODUCTS_COLUMNS)
    patents = _read_ob_file(OB_DIR / "patent.txt", PATENT_COLUMNS)
    exclusivity = _read_ob_file(OB_DIR / "exclusivity.txt", EXCLUSIVITY_COLUMNS)

    products.to_parquet(PROCESSED_DIR / "orange_book_products.parquet", index=False)
    patents.to_parquet(PROCESSED_DIR / "orange_book_patents.parquet", index=False)
    exclusivity.to_parquet(PROCESSED_DIR / "orange_book_exclusivity.parquet", index=False)

    con = duckdb.connect(str(WAREHOUSE_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw_fda")

    con.execute("CREATE OR REPLACE TABLE raw_fda.orange_book_products AS SELECT * FROM products")
    con.execute("CREATE OR REPLACE TABLE raw_fda.orange_book_patents AS SELECT * FROM patents")
    con.execute("CREATE OR REPLACE TABLE raw_fda.orange_book_exclusivity AS SELECT * FROM exclusivity")

    print(f"Orange Book ingested: products={len(products)}, patents={len(patents)}, exclusivity={len(exclusivity)}")
    con.close()


if __name__ == "__main__":
    run()
