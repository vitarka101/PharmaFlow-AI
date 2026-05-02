"""
Generates synthetic payer claims from the switch_candidates mart.
Uses real NADAC drug names and costs; all member/prescriber IDs are fabricated.

Output: data/synthetic/claims.csv

Run directly:  python -m scripts.data.synthetic_generator
"""

from __future__ import annotations

import random
import string
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]
WAREHOUSE_PATH = BASE_DIR / "data" / "warehouse" / "pharmaflow.duckdb"
SYNTHETIC_DIR = BASE_DIR / "data" / "synthetic"
SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)

CLAIMS_PATH = SYNTHETIC_DIR / "claims.csv"

SEED = 42
N_CLAIMS = 500
N_MEMBERS = 220

AGE_BANDS = ["18-34", "35-44", "45-54", "55-64", "65-74", "75+"]
SEX_OPTS = ["M", "F"]
ZIP3_OPTS = [f"{z:03d}" for z in [100, 110, 200, 300, 400, 500, 600, 700, 800, 900]]
PLAN_IDS = ["PLAN-GOLD-001", "PLAN-SILVER-002", "PLAN-BRONZE-003"]
DIAGNOSIS_GROUPS = [
    "CARDIOVASCULAR", "DIABETES", "MENTAL_HEALTH", "RESPIRATORY",
    "MUSCULOSKELETAL", "GASTROINTESTINAL", "ONCOLOGY", "OTHER",
]
PHARMACY_IDS = [f"PHX-{i:04d}" for i in range(1, 21)]
PRESCRIBER_IDS = [f"NPI-{i:07d}" for i in range(1000001, 1000051)]


def _random_date(rng: random.Random, start_year: int = 2024) -> str:
    start = date(start_year, 1, 1)
    offset = rng.randint(0, 364)
    return (start + timedelta(days=offset)).isoformat()


def generate(n_claims: int = N_CLAIMS) -> pd.DataFrame:
    rng = random.Random(SEED)

    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    # Prefer oral solid drugs (tablet/capsule) for realistic demo claims.
    # Fall back to all candidates if not enough oral solids.
    candidates = con.execute("""
        SELECT brand_name, brand_ndc, brand_unit_cost, pricing_unit
        FROM marts.switch_candidates
        WHERE brand_name ILIKE '%TABLET%'
           OR brand_name ILIKE '%CAPSULE%'
        ORDER BY unit_cost_delta DESC
        LIMIT 40
    """).df()
    if len(candidates) < 10:
        candidates = con.execute("""
            SELECT brand_name, brand_ndc, brand_unit_cost, pricing_unit
            FROM marts.switch_candidates
            ORDER BY unit_cost_delta DESC
            LIMIT 40
        """).df()
    con.close()

    if candidates.empty:
        raise RuntimeError(
            "switch_candidates mart is empty — run the ingestion pipeline first."
        )

    members = [f"MBR-{i:05d}" for i in range(1, N_MEMBERS + 1)]
    member_attrs: dict[str, dict] = {}
    for mid in members:
        member_attrs[mid] = {
            "age_band": rng.choice(AGE_BANDS),
            "sex": rng.choice(SEX_OPTS),
            "zip3": rng.choice(ZIP3_OPTS),
            "plan_id": rng.choice(PLAN_IDS),
            "adherence_score": round(rng.uniform(0.4, 1.0), 2),
            "pharmacy_access_score": round(rng.uniform(0.3, 1.0), 2),
            "preferred_pharmacy_available": rng.choices([0, 1], weights=[0.25, 0.75])[0],
        }

    rows = []
    for i in range(1, n_claims + 1):
        drug_row = candidates.iloc[rng.randint(0, len(candidates) - 1)]
        member_id = rng.choice(members)
        attrs = member_attrs[member_id]

        quantity = rng.choice([30, 60, 90])
        days_supply = quantity  # 1 unit/day assumption
        unit_cost = float(drug_row["brand_unit_cost"])
        paid = round(unit_cost * quantity * rng.uniform(0.85, 1.15), 2)
        cost_share = round(paid * rng.uniform(0.05, 0.30), 2)
        diagnosis = rng.choice(DIAGNOSIS_GROUPS)

        # Simulate clinical risk from diagnosis and adherence.
        # ~15% of claims have prior switch failure flag to create Do Not Switch cases.
        prior_failure = 1 if rng.random() < 0.15 else 0
        # High-risk diagnoses get higher potential event costs
        if diagnosis in ("ONCOLOGY", "MENTAL_HEALTH"):
            event_cost = round(rng.uniform(1500, 8000), 2)
        else:
            event_cost = round(rng.uniform(200, 2500), 2)

        rows.append({
            "claim_id": f"CLM-{i:06d}",
            "member_id": member_id,
            "age_band": attrs["age_band"],
            "sex": attrs["sex"],
            "zip3": attrs["zip3"],
            "plan_id": attrs["plan_id"],
            "drug_name": str(drug_row["brand_name"]),
            "brand_generic_flag": "B",
            "ndc": str(drug_row["brand_ndc"]),
            "quantity": float(quantity),
            "days_supply": int(days_supply),
            "fill_date": _random_date(rng),
            "paid_amount": paid,
            "member_cost_share": cost_share,
            "pharmacy_id": rng.choice(PHARMACY_IDS),
            "prescriber_id": rng.choice(PRESCRIBER_IDS),
            "diagnosis_group": diagnosis,
            "adherence_score": attrs["adherence_score"],
            "prior_switch_failure_flag": prior_failure,
            "estimated_event_cost": event_cost,
            "preferred_pharmacy_available": attrs["preferred_pharmacy_available"],
            "pharmacy_access_score": attrs["pharmacy_access_score"],
        })

    df = pd.DataFrame(rows)
    df.to_csv(CLAIMS_PATH, index=False)
    print(f"Synthetic claims generated: {len(df)} rows → {CLAIMS_PATH}")
    return df


if __name__ == "__main__":
    generate()
