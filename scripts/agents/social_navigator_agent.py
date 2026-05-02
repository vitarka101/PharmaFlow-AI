"""
Social Navigator Agent: pharmacy access and adherence feasibility.

Uses pharmacy_access_score and preferred_pharmacy_available from the claim.
High access risk overrides a Recommend band to Review.
Never recommends a switch when access is critically low.
"""

from scripts.models.schemas import ClaimRecord, AccessRisk

_LOW_ACCESS_THRESHOLD = 0.40     # below this → access_override = True
_HIGH_ADHERENCE_RISK = 0.50      # adherence_risk_score above this → flag


def run(claim: ClaimRecord) -> AccessRisk:
    access_score = float(claim.pharmacy_access_score)
    adherence_risk = max(1.0 - float(claim.adherence_score), 0.0)
    preferred_avail = bool(claim.preferred_pharmacy_available)

    access_override = access_score < _LOW_ACCESS_THRESHOLD

    reason_codes: list[str] = []
    if not preferred_avail:
        reason_codes.append("PREFERRED_PHARMACY_UNAVAILABLE")
    if access_score < _LOW_ACCESS_THRESHOLD:
        reason_codes.append("LOW_PHARMACY_ACCESS")
        if not reason_codes or "PREFERRED_PHARMACY_UNAVAILABLE" not in reason_codes:
            reason_codes.append("ACCESS_REVIEW_REQUIRED")
    elif access_score < 0.60:
        reason_codes.append("MODERATE_ACCESS_RISK")
    if adherence_risk > _HIGH_ADHERENCE_RISK:
        reason_codes.append("HIGH_ADHERENCE_RISK")

    if access_score >= 0.80 and preferred_avail:
        access_reason = "Strong pharmacy access. Preferred pharmacy carries generic alternative."
    elif access_score >= 0.60:
        access_reason = "Adequate pharmacy access. Verify preferred pharmacy availability before switch."
    elif access_override:
        access_reason = (
            "Low pharmacy access score — alternative may not be accessible at member's usual pharmacy. "
            "Clinical pharmacist review required before any switch action."
        )
    else:
        access_reason = "Moderate pharmacy access. Review pharmacy network before switch."

    return AccessRisk(
        pharmacy_access_score=round(access_score, 4),
        adherence_risk_score=round(adherence_risk, 4),
        preferred_pharmacy_available=preferred_avail,
        access_override=access_override,
        access_reason=access_reason,
        reason_codes=reason_codes,
    )
