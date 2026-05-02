"""
Shared Pydantic schemas for all agents, services, and API responses.
All deterministic calculations flow through these types.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input: a single synthetic claim row
# ---------------------------------------------------------------------------

class ClaimRecord(BaseModel):
    claim_id: str
    member_id: str
    age_band: str
    sex: str
    zip3: str
    plan_id: str
    drug_name: str
    brand_generic_flag: str          # "B" or "G"
    ndc: str
    quantity: float
    days_supply: int
    fill_date: str
    paid_amount: float
    member_cost_share: float
    pharmacy_id: str
    prescriber_id: str
    diagnosis_group: str
    adherence_score: float           # 0–1; higher = more adherent
    prior_switch_failure_flag: int   # 0 or 1
    estimated_event_cost: float      # expected downstream cost if switch fails
    preferred_pharmacy_available: int  # 0 or 1
    pharmacy_access_score: float     # 0–1; higher = better access


# ---------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------

class DrugMapping(BaseModel):
    """Librarian Agent output."""
    source_drug: str
    candidate_alternative: str
    generic_ndc: str
    equivalence_type: str            # GENERIC_EQUIVALENT | THERAPEUTIC_ALTERNATIVE | NO_ALTERNATIVE
    te_code: Optional[str] = None
    dosage_form_route: Optional[str] = None
    strength: Optional[str] = None
    mapping_confidence: float        # 0–1
    mapping_reason: str
    reason_codes: list[str] = Field(default_factory=list)


class CostAnalysis(BaseModel):
    """Auditor Agent output."""
    current_unit_cost: float
    alternative_unit_cost: float
    pricing_unit: str
    normalized_quantity: float
    days_supply: int
    gross_savings: float
    spread_estimate: float           # synthetic PBM spread estimate
    audit_reason: str
    reason_codes: list[str] = Field(default_factory=list)


class ClinicalRisk(BaseModel):
    """Clinician Agent output."""
    clinical_risk_score: float       # 0–1; higher = riskier switch
    switch_failure_probability: float
    expected_medical_cost_delta: float
    risk_adjusted_savings: float
    credible_interval_low: float
    credible_interval_high: float
    clinical_reason_codes: list[str] = Field(default_factory=list)


class AccessRisk(BaseModel):
    """Social Navigator Agent output."""
    pharmacy_access_score: float     # 0–1; higher = better access
    adherence_risk_score: float      # 0–1; higher = more risk
    preferred_pharmacy_available: bool
    access_override: bool            # True if access risk blocks recommendation
    access_reason: str
    reason_codes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Aggregated recommendation
# ---------------------------------------------------------------------------

class Recommendation(BaseModel):
    """Full payer-facing switch opportunity record."""
    recommendation_id: str
    member_id: str
    claim_id: str

    # Drug identity
    current_drug: str
    candidate_alternative: str
    equivalence_type: str
    te_code: Optional[str] = None

    # Economics
    gross_savings: float
    risk_adjusted_savings: float
    current_unit_cost: float
    alternative_unit_cost: float
    pricing_unit: str

    # Risk
    clinical_risk_score: float
    access_risk_score: float
    switch_failure_probability: float
    credible_interval_low: float
    credible_interval_high: float

    # Classification
    recommendation_band: str         # Recommend | Review | Do Not Switch
    reason_codes: list[str]

    # Explanation (deterministic text, not LLM)
    explanation: str

    # Agent sub-outputs for detail panel
    mapping: DrugMapping
    cost_analysis: CostAnalysis
    clinical_risk: ClinicalRisk
    access_risk: AccessRisk


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

class DashboardSummary(BaseModel):
    """Portfolio-level executive summary cards."""
    total_gross_savings: float
    total_risk_adjusted_savings: float
    opportunity_count: int
    recommend_count: int
    review_count: int
    do_not_switch_count: int
    avg_gross_savings_per_opportunity: float
    avg_risk_adjusted_savings_per_opportunity: float
    data_disclaimer: str = (
        "All member data is synthetic and generated for demonstration purposes only. "
        "Drug pricing is sourced from CMS NADAC (April 2026). "
        "This tool is not clinical decision support and must not be used for real patient care."
    )
