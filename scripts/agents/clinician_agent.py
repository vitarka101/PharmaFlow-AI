"""
Clinician Agent: risk-adjusted total cost of care.

Deterministic: switch failure probability is derived from a lookup table
keyed on diagnosis_group and prior_switch_failure_flag. No LLM involved.

Outputs risk_adjusted_savings = gross - medical_delta - adherence_penalty.
Credible interval uses a ±30% width around the point estimate.
"""

from __future__ import annotations

from typing import Optional
from scripts.models.schemas import ClaimRecord, DrugMapping, ClinicalRisk, CostAnalysis
from scripts.services.scoring_service import (
    calculate_expected_medical_delta,
    calculate_adherence_penalty,
    calculate_risk_adjusted_savings,
    THRESHOLDS,
)

# Switch failure probability table by diagnosis group (base rate, prior failure multiplier).
# These are deterministic synthetic assumptions — not clinical evidence.
_FAILURE_BASE: dict[str, float] = {
    "CARDIOVASCULAR": 0.12,
    "DIABETES": 0.10,
    "MENTAL_HEALTH": 0.22,
    "RESPIRATORY": 0.14,
    "MUSCULOSKELETAL": 0.08,
    "GASTROINTESTINAL": 0.09,
    "ONCOLOGY": 0.28,
    "OTHER": 0.10,
}
_PRIOR_FAILURE_MULTIPLIER = 2.5
_TE_CODE_CONFIDENCE_BOOST = {
    "AB": 0.85,   # AB-rated: strong equivalence → lower failure rate
    "BX": 1.20,   # BX-rated: not yet evaluated → slightly higher
}
_CI_WIDTH = 0.30  # credible interval ±30% of point estimate


def run(claim: ClaimRecord, mapping: DrugMapping, cost: Optional[CostAnalysis] = None) -> ClinicalRisk:
    # Gross savings passed in from auditor; if not provided, zero it
    gross = cost.gross_savings if cost else 0.0

    base_rate = _FAILURE_BASE.get(claim.diagnosis_group.upper(), 0.10)
    failure_prob = base_rate * (_PRIOR_FAILURE_MULTIPLIER if claim.prior_switch_failure_flag else 1.0)

    # Adjust by TE code quality
    te = (mapping.te_code or "").upper()
    te_prefix = te[:2] if len(te) >= 2 else te
    te_factor = _TE_CODE_CONFIDENCE_BOOST.get(te_prefix, 1.0)
    failure_prob = min(failure_prob * te_factor, 0.95)

    medical_delta = calculate_expected_medical_delta(failure_prob, claim.estimated_event_cost)

    # Adherence risk = inverse of adherence score
    adherence_risk = max(1.0 - claim.adherence_score, 0.0)
    adherence_penalty = calculate_adherence_penalty(adherence_risk)

    risk_adj = calculate_risk_adjusted_savings(gross, medical_delta, adherence_penalty)

    # Credible interval: ±30% of point estimate
    ci_low = risk_adj * (1.0 - _CI_WIDTH)
    ci_high = risk_adj * (1.0 + _CI_WIDTH)

    # Clinical risk score: blend of failure probability and diagnosis severity
    clinical_risk_score = min(failure_prob, 1.0)

    reason_codes = []
    if failure_prob >= 0.20:
        reason_codes.append("HIGH_CLINICAL_RISK")
    elif failure_prob >= 0.10:
        reason_codes.append("MODERATE_CLINICAL_RISK")
    if claim.prior_switch_failure_flag:
        reason_codes.append("PRIOR_SWITCH_FAILURE")
    if mapping.equivalence_type == "THERAPEUTIC_ALTERNATIVE":
        reason_codes.append("CLINICAL_REVIEW_REQUIRED")
    if risk_adj <= 0:
        reason_codes.append("NEGATIVE_RISK_ADJUSTED_SAVINGS")

    return ClinicalRisk(
        clinical_risk_score=round(clinical_risk_score, 4),
        switch_failure_probability=round(failure_prob, 4),
        expected_medical_cost_delta=round(medical_delta, 2),
        risk_adjusted_savings=round(risk_adj, 2),
        credible_interval_low=round(ci_low, 2),
        credible_interval_high=round(ci_high, 2),
        clinical_reason_codes=reason_codes,
    )
