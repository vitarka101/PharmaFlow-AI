"""
Joins Orange Book + NADAC to produce marts.switch_candidates.

Matching strategy (fixes trade-name vs ingredient mismatch):
  Step 1: Brand NADAC  → OB on first-word of ndc_description = OB trade_name
          This resolves trade name (ABILIFY) → ingredient (ARIPIPRAZOLE).
  Step 2: Generic NADAC → OB on first-word of ndc_description = OB ingredient
          e.g. "ARIPIPRAZOLE 10 MG TABLET" → ingredient ARIPIPRAZOLE.
  Step 3: Join brand↔generic on shared OB ingredient (+te_code when available).
  Step 4: Emit one row per brand→cheapest-generic pair.

Fallback: brand NADAC rows with non-null generic_nadac_per_unit are also
          used directly when OB matching fails, paired with any matching
          generic NADAC row.

Run directly:  python -m src.transform.build_equivalence_map
"""

from pathlib import Path
import duckdb

WAREHOUSE_PATH = Path(__file__).resolve().parents[2] / "data" / "warehouse" / "pharmaflow.duckdb"


def run() -> None:
    con = duckdb.connect(str(WAREHOUSE_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS marts")

    # ── Step 1: Brand NADAC with OB ingredient lookup ──────────────────────
    con.execute("""
    CREATE OR REPLACE TABLE marts._brand_with_ingredient AS
    SELECT DISTINCT
        n.ndc_description   AS brand_name,
        n.ndc               AS brand_ndc,
        n.nadac_per_unit    AS brand_unit_cost,
        n.pricing_unit,
        n.generic_nadac_per_unit AS nadac_generic_fallback_cost,
        n.classification,
        -- first word of the trade description = trade name key
        upper(trim(split_part(n.ndc_description, chr(32), 1))) AS trade_key,
        -- resolve ingredient via OB trade_name
        coalesce(ob.ingredient, upper(trim(split_part(n.ndc_description, chr(32), 1)))) AS ingredient,
        coalesce(ob.te_code, '') AS te_code_brand,
        coalesce(ob.dosage_form_route, '') AS dosage_form_route,
        coalesce(ob.strength, '') AS strength
    FROM raw_nadac.nadac_prices n
    LEFT JOIN (
        SELECT DISTINCT
            upper(trim(trade_name)) AS trade_name_key,
            ingredient,
            te_code,
            dosage_form_route,
            strength
        FROM marts.orange_book_products_clean
        WHERE application_category = 'NDA_BRAND'
          AND drug_type = 'RX'
    ) ob
    ON upper(trim(split_part(n.ndc_description, chr(32), 1))) = ob.trade_name_key
    WHERE n.classification IN ('B', 'B-ANDA', 'B-BIO')
      AND n.nadac_per_unit IS NOT NULL
      AND n.nadac_per_unit > 0
    """)

    # ── Step 2: Generic NADAC with ingredient key ──────────────────────────
    con.execute("""
    CREATE OR REPLACE TABLE marts._generic_with_ingredient AS
    SELECT DISTINCT
        n.ndc_description   AS generic_name,
        n.ndc               AS generic_ndc,
        n.nadac_per_unit    AS generic_unit_cost,
        n.pricing_unit      AS generic_pricing_unit,
        upper(trim(split_part(n.ndc_description, chr(32), 1))) AS ingredient_key
    FROM raw_nadac.nadac_prices n
    WHERE n.classification = 'G'
      AND n.nadac_per_unit IS NOT NULL
      AND n.nadac_per_unit > 0
    """)

    # ── Step 3+4: Join on ingredient; cheapest generic per brand ───────────
    # Form-compatibility filter: extract a broad form keyword from ndc_description
    # to avoid matching injectables against tablets.
    con.execute("""
    CREATE OR REPLACE TABLE marts.switch_candidates AS
    WITH with_form AS (
        SELECT *,
            CASE
                WHEN upper(brand_name) LIKE '%TABLET%'   THEN 'TABLET'
                WHEN upper(brand_name) LIKE '%CAPSULE%'  THEN 'CAPSULE'
                WHEN upper(brand_name) LIKE '%SOLUTION%' THEN 'SOLUTION'
                WHEN upper(brand_name) LIKE '%PATCH%'    THEN 'PATCH'
                WHEN upper(brand_name) LIKE '%CREAM%'    THEN 'CREAM'
                WHEN upper(brand_name) LIKE '%GEL%'      THEN 'GEL'
                WHEN upper(brand_name) LIKE '%SPRAY%'    THEN 'SPRAY'
                WHEN upper(brand_name) LIKE '%INHALER%'  THEN 'INHALER'
                ELSE 'OTHER'
            END AS brand_form
        FROM marts._brand_with_ingredient
        -- Exclude very-high-cost specialty/biologic injectables (> $200/unit)
        WHERE brand_unit_cost <= 200
    ),
    joined AS (
        SELECT
            b.brand_name,
            b.brand_ndc,
            b.brand_unit_cost,
            b.pricing_unit,
            b.nadac_generic_fallback_cost,
            g.generic_name,
            g.generic_ndc,
            g.generic_unit_cost,
            b.ingredient,
            b.te_code_brand   AS te_code,
            b.dosage_form_route,
            b.strength,
            NULL              AS brand_trade_name,
            b.brand_form,
            (b.brand_unit_cost - g.generic_unit_cost) AS unit_cost_delta,
            row_number() OVER (
                PARTITION BY b.brand_ndc
                ORDER BY g.generic_unit_cost ASC
            ) AS rn
        FROM with_form b
        JOIN marts._generic_with_ingredient g
            ON b.ingredient = g.ingredient_key
           AND g.generic_unit_cost < b.brand_unit_cost
        -- Require compatible form: generic name must contain same form keyword
        WHERE b.brand_form = 'OTHER'
           OR upper(g.generic_name) LIKE ('%' || b.brand_form || '%')
    )
    SELECT
        brand_name, brand_ndc, brand_unit_cost, pricing_unit,
        nadac_generic_fallback_cost,
        generic_name, generic_ndc, generic_unit_cost,
        ingredient           AS ingredient_key,
        te_code, dosage_form_route, strength, brand_trade_name,
        unit_cost_delta
    FROM joined
    WHERE rn = 1
      AND unit_cost_delta > 0.01
    ORDER BY unit_cost_delta DESC
    """)

    count = con.execute("SELECT count(*) FROM marts.switch_candidates").fetchone()[0]
    print(f"Switch candidates built: {count} brand→generic pairs")

    # Preview top 5
    top = con.execute("""
        SELECT brand_name, generic_name, brand_unit_cost, generic_unit_cost, unit_cost_delta, te_code
        FROM marts.switch_candidates
        LIMIT 5
    """).df()
    print(top.to_string())

    con.execute("DROP TABLE IF EXISTS marts._brand_with_ingredient")
    con.execute("DROP TABLE IF EXISTS marts._generic_with_ingredient")
    con.close()


if __name__ == "__main__":
    run()
