"""
Pricing service: NADAC unit cost lookup and quantity normalization.

Pricing units from NADAC: EA (each/tablet/capsule), ML (milliliter), GM (gram).
All unit costs are NADAC Per Unit — already normalized to the pricing unit.
Quantity normalization converts claim quantity to the NADAC pricing unit basis.
"""

from __future__ import annotations

from scripts.services.data_service import get_connection


# Pricing unit multipliers for normalizing to a per-claim cost basis.
# NADAC prices are already per unit (EA=tablet, ML=mL, GM=gram).
# For EA drugs: normalized_quantity = quantity (tablets/capsules as dispensed).
# For ML/GM drugs: quantity on the claim is typically in the pricing unit directly.
_UNIT_MULTIPLIERS: dict[str, float] = {
    "EA": 1.0,
    "ML": 1.0,
    "GM": 1.0,
}


def get_unit_cost(ndc: str, drug_name: str = "") -> tuple[float, str]:
    """
    Return (nadac_per_unit, pricing_unit) for a drug.
    Tries NDC first, falls back to ingredient-key name match.
    Returns (0.0, 'EA') if not found.
    """
    con = get_connection()
    try:
        row = con.execute("""
            SELECT nadac_per_unit, pricing_unit
            FROM raw_nadac.nadac_prices
            WHERE ndc = ?
              AND nadac_per_unit IS NOT NULL
            LIMIT 1
        """, [ndc.strip()]).fetchone()

        if row is None and drug_name:
            ingredient_key = drug_name.strip().split()[0].upper() + "%"
            row = con.execute("""
                SELECT nadac_per_unit, pricing_unit
                FROM raw_nadac.nadac_prices
                WHERE upper(ndc_description) LIKE ?
                  AND nadac_per_unit IS NOT NULL
                  AND classification IN ('B', 'B-ANDA', 'B-BIO')
                ORDER BY nadac_per_unit ASC
                LIMIT 1
            """, [ingredient_key]).fetchone()
    finally:
        con.close()

    if row is None:
        return 0.0, "EA"
    return float(row[0]), str(row[1]).strip().upper()


def get_generic_unit_cost(generic_ndc: str, ingredient_key: str = "") -> tuple[float, str]:
    """Return (nadac_per_unit, pricing_unit) for a generic drug."""
    con = get_connection()
    try:
        row = con.execute("""
            SELECT nadac_per_unit, pricing_unit
            FROM raw_nadac.nadac_prices
            WHERE ndc = ?
              AND nadac_per_unit IS NOT NULL
            LIMIT 1
        """, [generic_ndc.strip()]).fetchone()

        if row is None and ingredient_key:
            key = ingredient_key.strip().upper() + "%"
            row = con.execute("""
                SELECT nadac_per_unit, pricing_unit
                FROM raw_nadac.nadac_prices
                WHERE upper(ndc_description) LIKE ?
                  AND nadac_per_unit IS NOT NULL
                  AND classification = 'G'
                ORDER BY nadac_per_unit ASC
                LIMIT 1
            """, [key]).fetchone()
    finally:
        con.close()

    if row is None:
        return 0.0, "EA"
    return float(row[0]), str(row[1]).strip().upper()


def normalize_quantity(quantity: float, days_supply: int, pricing_unit: str) -> float:
    """
    Normalize claim quantity to the NADAC pricing unit.
    For most oral solids (EA): quantity is tablet count — use directly.
    """
    multiplier = _UNIT_MULTIPLIERS.get(pricing_unit.upper(), 1.0)
    return max(quantity * multiplier, 1.0)
