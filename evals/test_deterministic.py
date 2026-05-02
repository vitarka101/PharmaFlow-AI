"""
Deterministic tests for PharmaFlow AI.

Run: pytest evals/ -q
"""

import sys
from pathlib import Path

# Make root importable without installation
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Scoring formula tests ─────────────────────────────────────────────────

from scripts.services.scoring_service import (
    calculate_gross_savings,
    calculate_expected_medical_delta,
    calculate_adherence_penalty,
    calculate_risk_adjusted_savings,
    classify_recommendation,
    THRESHOLDS,
)


def test_gross_savings_basic():
    result = calculate_gross_savings(10.0, 2.0, 30.0)
    assert result == pytest.approx(240.0, rel=1e-3)


def test_gross_savings_no_negative():
    # Generic more expensive than brand → 0, not negative
    result = calculate_gross_savings(2.0, 10.0, 30.0)
    assert result == 0.0


def test_gross_savings_zero_costs():
    assert calculate_gross_savings(0.0, 0.0, 30.0) == 0.0
    assert calculate_gross_savings(-1.0, 1.0, 30.0) == 0.0


def test_expected_medical_delta():
    result = calculate_expected_medical_delta(0.2, 1000.0)
    assert result == pytest.approx(200.0, rel=1e-3)


def test_adherence_penalty_default():
    # adherence_risk=0.5 → 0.5 * 150 = 75
    result = calculate_adherence_penalty(0.5)
    assert result == pytest.approx(75.0, rel=1e-3)


def test_risk_adjusted_savings():
    gross = 240.0
    medical = 50.0
    adherence = 30.0
    result = calculate_risk_adjusted_savings(gross, medical, adherence)
    assert result == pytest.approx(160.0, rel=1e-3)


def test_risk_adjusted_savings_can_be_negative():
    result = calculate_risk_adjusted_savings(10.0, 200.0, 50.0)
    assert result < 0


# ── Band classification tests ─────────────────────────────────────────────

def test_classify_recommend():
    band = classify_recommendation(
        risk_adjusted_savings=200.0,
        clinical_risk_score=0.10,
        access_risk_score=0.80,
    )
    assert band == "Recommend"


def test_classify_review_high_clinical_risk():
    band = classify_recommendation(
        risk_adjusted_savings=200.0,
        clinical_risk_score=0.50,  # above recommend_clinical_max (0.30)
        access_risk_score=0.80,
    )
    assert band == "Review"


def test_classify_review_low_access():
    band = classify_recommendation(
        risk_adjusted_savings=200.0,
        clinical_risk_score=0.10,
        access_risk_score=0.40,  # below recommend_access_min (0.60)
    )
    assert band == "Review"


def test_classify_do_not_switch_negative_savings():
    band = classify_recommendation(
        risk_adjusted_savings=-50.0,
        clinical_risk_score=0.10,
        access_risk_score=0.90,
    )
    assert band == "Do Not Switch"


def test_classify_do_not_switch_zero_savings():
    band = classify_recommendation(
        risk_adjusted_savings=0.0,
        clinical_risk_score=0.10,
        access_risk_score=0.90,
    )
    assert band == "Do Not Switch"


def test_thresholds_single_source():
    # All thresholds must come from THRESHOLDS dict
    assert "recommend_clinical_max" in THRESHOLDS
    assert "recommend_access_min" in THRESHOLDS
    assert "adherence_cost_default" in THRESHOLDS
    assert THRESHOLDS["adherence_cost_default"] == 150.0


# ── Orange Book ingest tests ──────────────────────────────────────────────

import pandas as pd

OB_DIR = Path(__file__).resolve().parents[1] / "Orange_book_data_files"


def test_products_txt_parseable():
    df = pd.read_csv(OB_DIR / "products.txt", sep="~", dtype=str, encoding="latin1",
                     keep_default_na=False)
    assert len(df) > 100
    assert "Appl_Type" in df.columns
    assert "TE_Code" in df.columns


def test_products_appl_types():
    df = pd.read_csv(OB_DIR / "products.txt", sep="~", dtype=str, encoding="latin1",
                     keep_default_na=False)
    types = set(df["Appl_Type"].str.strip().str.upper().unique())
    assert "N" in types  # NDA brands
    assert "A" in types  # ANDA generics


def test_products_has_ab_te_codes():
    df = pd.read_csv(OB_DIR / "products.txt", sep="~", dtype=str, encoding="latin1",
                     keep_default_na=False)
    te_codes = df["TE_Code"].str.strip().str.upper()
    assert te_codes.str.startswith("AB").any()


# ── NADAC CSV tests ───────────────────────────────────────────────────────

NADAC_PATH = Path(__file__).resolve().parents[1] / "NADAC.csv"


def test_nadac_parseable():
    df = pd.read_csv(NADAC_PATH, dtype=str, keep_default_na=False, nrows=100)
    assert len(df) > 0
    assert "NADAC Per Unit" in df.columns
    assert "Classification for Rate Setting" in df.columns


def test_nadac_unit_costs_positive():
    df = pd.read_csv(NADAC_PATH, keep_default_na=False, nrows=500)
    df["NADAC Per Unit"] = pd.to_numeric(df["NADAC Per Unit"], errors="coerce")
    valid = df["NADAC Per Unit"].dropna()
    assert (valid > 0).all(), "All NADAC unit costs should be positive"


def test_nadac_has_brand_and_generic():
    df = pd.read_csv(NADAC_PATH, dtype=str, keep_default_na=False)
    classes = set(df["Classification for Rate Setting"].str.strip().str.upper().unique())
    assert "B" in classes
    assert "G" in classes


# ── Social navigator agent tests ──────────────────────────────────────────

from scripts.models.schemas import ClaimRecord


def _make_claim(**kwargs) -> ClaimRecord:
    defaults = dict(
        claim_id="CLM-000001", member_id="SYN-MEMBER-0001",
        age_band="45-54", sex="F", zip3="100", plan_id="PLAN-GOLD-001",
        drug_name="ABILIFY 10 MG TABLET", brand_generic_flag="B",
        ndc="59148000813", quantity=30.0, days_supply=30,
        fill_date="2024-06-01", paid_amount=500.0, member_cost_share=50.0,
        pharmacy_id="PHX-0001", prescriber_id="NPI-1000001",
        diagnosis_group="CARDIOVASCULAR", adherence_score=0.85,
        prior_switch_failure_flag=0, estimated_event_cost=500.0,
        preferred_pharmacy_available=1, pharmacy_access_score=0.80,
    )
    defaults.update(kwargs)
    return ClaimRecord(**defaults)


def test_social_navigator_low_access_sets_override():
    from scripts.agents.social_navigator_agent import run
    claim = _make_claim(pharmacy_access_score=0.25, preferred_pharmacy_available=0)
    result = run(claim)
    assert result.access_override is True
    assert "LOW_PHARMACY_ACCESS" in result.reason_codes


def test_social_navigator_high_access_no_override():
    from scripts.agents.social_navigator_agent import run
    claim = _make_claim(pharmacy_access_score=0.90, preferred_pharmacy_available=1)
    result = run(claim)
    assert result.access_override is False


def test_clinician_prior_failure_increases_risk():
    from scripts.agents.clinician_agent import run as clinician_run
    from scripts.models.schemas import DrugMapping
    mapping = DrugMapping(
        source_drug="ABILIFY", candidate_alternative="ARIPIPRAZOLE",
        generic_ndc="12345", equivalence_type="GENERIC_EQUIVALENT",
        te_code="AB", mapping_confidence=0.95, mapping_reason="AB-rated",
        reason_codes=["GENERIC_EQUIVALENT"],
    )
    from scripts.agents.clinician_agent import run as clin_run
    from scripts.models.schemas import CostAnalysis

    cost = CostAnalysis(
        current_unit_cost=18.0, alternative_unit_cost=0.10,
        pricing_unit="EA", normalized_quantity=30.0, days_supply=30,
        gross_savings=536.97, spread_estimate=42.96,
        audit_reason="test", reason_codes=[],
    )

    claim_no_failure = _make_claim(prior_switch_failure_flag=0, diagnosis_group="CARDIOVASCULAR")
    claim_prior_fail = _make_claim(prior_switch_failure_flag=1, diagnosis_group="CARDIOVASCULAR")

    result_no_fail = clin_run(claim_no_failure, mapping, cost)
    result_prior   = clin_run(claim_prior_fail, mapping, cost)

    assert result_prior.switch_failure_probability > result_no_fail.switch_failure_probability


# ── API integration tests ─────────────────────────────────────────────────

import pytest

try:
    from fastapi.testclient import TestClient
    _has_testclient = True
except ImportError:
    _has_testclient = False


@pytest.mark.skipif(not _has_testclient, reason="httpx not installed")
def test_health_endpoint():
    from scripts.app import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.skipif(not _has_testclient, reason="httpx not installed")
def test_recommendations_schema():
    from scripts.app import app
    client = TestClient(app)
    resp = client.get("/api/recommendations")
    assert resp.status_code == 200
    recs = resp.json()
    assert isinstance(recs, list)
    if recs:
        r = recs[0]
        assert "recommendation_id" in r
        assert "gross_savings" in r
        assert "risk_adjusted_savings" in r
        assert "recommendation_band" in r
        assert r["recommendation_band"] in ("Recommend", "Review", "Do Not Switch")


@pytest.mark.skipif(not _has_testclient, reason="httpx not installed")
def test_dashboard_schema():
    from scripts.app import app
    client = TestClient(app)
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    s = resp.json()
    assert "total_gross_savings" in s
    assert "opportunity_count" in s
    assert isinstance(s["total_gross_savings"], (int, float))


@pytest.mark.skipif(not _has_testclient, reason="httpx not installed")
def test_document_download_zip():
    import zipfile, io
    from scripts.app import app
    with TestClient(app) as client:
        # Get a real recommendation ID
        recs = client.get("/api/recommendations").json()
        assert recs, "No recommendations loaded"
        rec_id = recs[0]["recommendation_id"]

        resp = client.get(f"/api/documents/{rec_id}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        assert resp.headers["content-type"] == "application/zip"
        assert "attachment" in resp.headers.get("content-disposition", "")

        # Verify zip contains all 4 PDFs
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert "member_letter.pdf" in names
        assert "prescriber_letter.pdf" in names
        assert "pharmacy_notice.pdf" in names
        assert "internal_memo.pdf" in names

        # Each PDF must be non-empty and start with %PDF header
        for name in names:
            data = zf.read(name)
            assert len(data) > 100, f"{name} is suspiciously small"
            assert data[:4] == b"%PDF", f"{name} is not a valid PDF"


import pytest  # noqa: E402 — import at top needed for pytest.approx in module body
