"""
Transforms raw_fda.orange_book_products into analysis-ready mart tables:
  - marts.orange_book_products_clean
  - marts.therapeutic_equivalence_groups

Run directly:  python -m src.transform.build_orange_book_marts
"""

from pathlib import Path
import duckdb

WAREHOUSE_PATH = Path(__file__).resolve().parents[2] / "data" / "warehouse" / "pharmaflow.duckdb"


def run() -> None:
    con = duckdb.connect(str(WAREHOUSE_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS marts")

    con.execute("""
    CREATE OR REPLACE TABLE marts.orange_book_products_clean AS
    SELECT
        upper(trim(ingredient))          AS ingredient,
        upper(trim(dosage_form_route))   AS dosage_form_route,
        upper(trim(trade_name))          AS trade_name,
        upper(trim(applicant))           AS applicant,
        upper(trim(applicant_full_name)) AS applicant_full_name,
        upper(trim(strength))            AS strength,
        upper(trim(appl_type))           AS appl_type,
        trim(appl_no)                    AS appl_no,
        trim(product_no)                 AS product_no,
        upper(trim(te_code))             AS te_code,
        trim(approval_date)              AS approval_date,
        upper(trim(rld))                 AS rld,
        upper(trim(rs))                  AS rs,
        upper(trim(type))                AS drug_type,
        ingest_date,

        CASE
            WHEN upper(trim(appl_type)) = 'N' THEN 'NDA_BRAND'
            WHEN upper(trim(appl_type)) = 'A' THEN 'ANDA_GENERIC'
            ELSE 'UNKNOWN'
        END AS application_category,

        CASE WHEN upper(trim(rld)) = 'YES' THEN 1 ELSE 0 END AS is_rld,
        CASE WHEN upper(trim(rs))  = 'YES' THEN 1 ELSE 0 END AS is_rs

    FROM raw_fda.orange_book_products
    """)

    # Therapeutic equivalence groups: same ingredient + route + strength + TE code
    # Only include groups where at least one generic (ANDA) exists
    con.execute("""
    CREATE OR REPLACE TABLE marts.therapeutic_equivalence_groups AS
    SELECT
        ingredient,
        dosage_form_route,
        strength,
        te_code,
        count(*)                                              AS total_products,
        count_if(application_category = 'NDA_BRAND')         AS brand_count,
        count_if(application_category = 'ANDA_GENERIC')      AS generic_count,
        count_if(is_rld = 1)                                  AS rld_count,
        count_if(is_rs = 1)                                   AS rs_count,
        -- representative brand trade name (RLD preferred)
        first(trade_name) FILTER (WHERE is_rld = 1)          AS rld_trade_name,
        first(trade_name) FILTER (WHERE application_category = 'NDA_BRAND') AS brand_trade_name
    FROM marts.orange_book_products_clean
    WHERE drug_type = 'RX'
      AND te_code IS NOT NULL
      AND te_code <> ''
      AND te_code <> 'NAN'
    GROUP BY ingredient, dosage_form_route, strength, te_code
    HAVING generic_count > 0
    ORDER BY brand_count DESC
    """)

    groups = con.execute("SELECT count(*) FROM marts.therapeutic_equivalence_groups").fetchone()[0]
    products = con.execute("SELECT count(*) FROM marts.orange_book_products_clean").fetchone()[0]
    print(f"Orange Book marts built: {products} clean products, {groups} equivalence groups")
    con.close()


if __name__ == "__main__":
    run()
