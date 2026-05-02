"""
Scoring service: deterministic savings formulas and recommendation band classifier.

ALL thresholds live in THRESHOLDS — never scattered across agents or routes.

Formulas:
    gross_savings = (current_unit_cost - alt_unit_cost) * normalized_quantity
    expected_medical_cost_delta = switch_failure_probability * estimated_event_cost
    expected_adherence_penalty = adherence_risk_score * THRESHOLDS["adherence_cost_default"]
    risk_adjusted_savings = gross_savings - expected_medical_cost_delta - expected_adherence_penalty

Recommendation bands:
    Recommend    — risk_adj_savings > 0 AND clinical_risk < 0.3 AND access_score > 0.6
    Review       — savings positive but clinical or access uncertainty is meaningful
    Do Not Switch — risk_adj_savings <= 0 OR safety/access flag is high
"""

THRESHOLDS: dict = {
    "recommend_clinical_max": 0.30,   # clinical_risk_score must be below this
    "recommend_access_min": 0.60,     # pharmacy_access_score must be above this
    "do_not_switch_savings_max": 0.0, # risk_adj_savings at or below → block
    "adherence_cost_default": 150.0,  # $ per-fill adherence penalty assumption (documented)
    "spread_rate": 0.08,              # synthetic PBM spread: 8% of gross savings
}


def calculate_gross_savings(
    current_unit_cost: float,
    alternative_unit_cost: float,
    normalized_quantity: float,
) -> float:
    """Gross pharmacy savings for a single claim fill."""
    if current_unit_cost <= 0 or alternative_unit_cost <= 0:
        return 0.0
    return max((current_unit_cost - alternative_unit_cost) * normalized_quantity, 0.0)


def calculate_expected_medical_delta(
    switch_failure_probability: float,
    estimated_event_cost: float,
) -> float:
    """Expected downstream medical cost if the switch fails."""
    return max(switch_failure_probability, 0.0) * max(estimated_event_cost, 0.0)


def calculate_adherence_penalty(
    adherence_risk_score: float,
    adherence_cost: float = THRESHOLDS["adherence_cost_default"],
) -> float:
    """
    Expected cost of adherence degradation after switch.
    adherence_risk_score: 0 = no risk, 1 = full risk.
    """
    return max(adherence_risk_score, 0.0) * adherence_cost


def calculate_risk_adjusted_savings(
    gross_savings: float,
    expected_medical_delta: float,
    adherence_penalty: float,
) -> float:
    """Net risk-adjusted savings after downstream cost and adherence penalty."""
    return gross_savings - expected_medical_delta - adherence_penalty


def calculate_spread_estimate(gross_savings: float) -> float:
    """Synthetic PBM spread estimate (8% of gross savings, for audit transparency)."""
    return gross_savings * THRESHOLDS["spread_rate"]


def classify_recommendation(
    risk_adjusted_savings: float,
    clinical_risk_score: float,
    access_risk_score: float,
) -> str:
    """
    Classify into Recommend / Review / Do Not Switch.
    access_risk_score here is pharmacy_access_score (higher = better access).
    """
    if risk_adjusted_savings <= THRESHOLDS["do_not_switch_savings_max"]:
        return "Do Not Switch"

    clinical_ok = clinical_risk_score < THRESHOLDS["recommend_clinical_max"]
    access_ok = access_risk_score > THRESHOLDS["recommend_access_min"]

    if clinical_ok and access_ok:
        return "Recommend"
    return "Review"
