"""
Recommendation service: orchestrates all 4 agents for each claim,
then aggregates into portfolio-level summary.
"""

from __future__ import annotations

import hashlib
from scripts.models.schemas import ClaimRecord, Recommendation, DashboardSummary
from scripts.services.data_service import load_claims


def _build_recommendation_id(claim_id: str, member_id: str) -> str:
    raw = f"{claim_id}:{member_id}"
    return "REC-" + hashlib.md5(raw.encode()).hexdigest()[:8].upper()


def _coerce_claim(row: dict) -> ClaimRecord:
    return ClaimRecord(
        claim_id=str(row["claim_id"]),
        member_id=str(row["member_id"]),
        age_band=str(row["age_band"]),
        sex=str(row["sex"]),
        zip3=str(row["zip3"]),
        plan_id=str(row["plan_id"]),
        drug_name=str(row["drug_name"]),
        brand_generic_flag=str(row["brand_generic_flag"]),
        ndc=str(row["ndc"]),
        quantity=float(row["quantity"]),
        days_supply=int(row["days_supply"]),
        fill_date=str(row["fill_date"]),
        paid_amount=float(row["paid_amount"]),
        member_cost_share=float(row["member_cost_share"]),
        pharmacy_id=str(row["pharmacy_id"]),
        prescriber_id=str(row["prescriber_id"]),
        diagnosis_group=str(row["diagnosis_group"]),
        adherence_score=float(row["adherence_score"]),
        prior_switch_failure_flag=int(float(row["prior_switch_failure_flag"])),
        estimated_event_cost=float(row["estimated_event_cost"]),
        preferred_pharmacy_available=int(float(row["preferred_pharmacy_available"])),
        pharmacy_access_score=float(row["pharmacy_access_score"]),
    )


def build_recommendation(claim: ClaimRecord) -> Recommendation | None:
    """Run all 4 agents on a claim. Returns None if no alternative exists."""
    from scripts.agents.librarian_agent import run as librarian_run
    from scripts.agents.auditor_agent import run as auditor_run
    from scripts.agents.clinician_agent import run as clinician_run
    from scripts.agents.social_navigator_agent import run as navigator_run

    mapping = librarian_run(claim)
    if mapping.equivalence_type == "NO_ALTERNATIVE":
        return None

    cost = auditor_run(claim, mapping)
    clinical = clinician_run(claim, mapping, cost)
    access = navigator_run(claim)

    # Merge reason codes from all agents
    all_codes: list[str] = list(dict.fromkeys(
        mapping.reason_codes + cost.reason_codes +
        clinical.clinical_reason_codes + access.reason_codes
    ))

    band = clinical.risk_adjusted_savings  # from clinician (includes adherence)
    from scripts.services.scoring_service import classify_recommendation
    recommendation_band = classify_recommendation(
        clinical.risk_adjusted_savings,
        clinical.clinical_risk_score,
        access.pharmacy_access_score,
    )

    if access.access_override:
        recommendation_band = "Review"
        if "ACCESS_REVIEW_REQUIRED" not in all_codes:
            all_codes.append("ACCESS_REVIEW_REQUIRED")

    explanation = _build_explanation(mapping, cost, clinical, access, recommendation_band)

    return Recommendation(
        recommendation_id=_build_recommendation_id(claim.claim_id, claim.member_id),
        member_id=claim.member_id,
        claim_id=claim.claim_id,
        plan_id=claim.plan_id,
        current_drug=claim.drug_name,
        candidate_alternative=mapping.candidate_alternative,
        equivalence_type=mapping.equivalence_type,
        te_code=mapping.te_code,
        gross_savings=cost.gross_savings,
        risk_adjusted_savings=clinical.risk_adjusted_savings,
        current_unit_cost=cost.current_unit_cost,
        alternative_unit_cost=cost.alternative_unit_cost,
        pricing_unit=cost.pricing_unit,
        clinical_risk_score=clinical.clinical_risk_score,
        access_risk_score=1.0 - access.pharmacy_access_score,  # invert: higher = more risk
        switch_failure_probability=clinical.switch_failure_probability,
        credible_interval_low=clinical.credible_interval_low,
        credible_interval_high=clinical.credible_interval_high,
        recommendation_band=recommendation_band,
        reason_codes=all_codes,
        explanation=explanation,
        mapping=mapping,
        cost_analysis=cost,
        clinical_risk=clinical,
        access_risk=access,
    )


def _build_explanation(mapping, cost, clinical, access, band: str) -> str:
    parts = [
        f"{mapping.candidate_alternative} is a {mapping.equivalence_type.replace('_', ' ').lower()}",
    ]
    if mapping.te_code:
        parts.append(f"with Orange Book TE code {mapping.te_code}")
    parts.append(
        f"at ${cost.alternative_unit_cost:.4f}/{cost.pricing_unit} vs "
        f"${cost.current_unit_cost:.4f}/{cost.pricing_unit} for {mapping.source_drug}."
    )
    parts.append(
        f"Estimated gross savings: ${cost.gross_savings:.2f}. "
        f"Risk-adjusted savings: ${clinical.risk_adjusted_savings:.2f} "
        f"(95% CI: ${clinical.credible_interval_low:.2f}–${clinical.credible_interval_high:.2f})."
    )
    if band == "Recommend":
        parts.append("Potential switch candidate for pharmacist/clinician review.")
    elif band == "Review":
        parts.append("Estimated savings opportunity with clinical and access risk flags. Review recommended before switch.")
    else:
        parts.append("Switch not recommended. Risk-adjusted savings do not justify switch at this time.")
    return " ".join(parts)


def get_all_recommendations() -> list[Recommendation]:
    df = load_claims()
    results = []
    for _, row in df.iterrows():
        try:
            claim = _coerce_claim(row.to_dict())
            rec = build_recommendation(claim)
            if rec is not None:
                results.append(rec)
        except Exception:
            continue
    return results


def get_dashboard_summary(recommendations: list[Recommendation]) -> DashboardSummary:
    n = len(recommendations)
    if n == 0:
        return DashboardSummary(
            total_gross_savings=0.0,
            total_risk_adjusted_savings=0.0,
            opportunity_count=0,
            recommend_count=0,
            review_count=0,
            do_not_switch_count=0,
            avg_gross_savings_per_opportunity=0.0,
            avg_risk_adjusted_savings_per_opportunity=0.0,
        )

    total_gross = sum(r.gross_savings for r in recommendations)
    total_risk_adj = sum(r.risk_adjusted_savings for r in recommendations)
    by_band: dict[str, int] = {"Recommend": 0, "Review": 0, "Do Not Switch": 0}
    for r in recommendations:
        by_band[r.recommendation_band] = by_band.get(r.recommendation_band, 0) + 1

    return DashboardSummary(
        total_gross_savings=round(total_gross, 2),
        total_risk_adjusted_savings=round(total_risk_adj, 2),
        opportunity_count=n,
        recommend_count=by_band.get("Recommend", 0),
        review_count=by_band.get("Review", 0),
        do_not_switch_count=by_band.get("Do Not Switch", 0),
        avg_gross_savings_per_opportunity=round(total_gross / n, 2),
        avg_risk_adjusted_savings_per_opportunity=round(total_risk_adj / n, 2),
    )
