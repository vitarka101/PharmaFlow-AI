"""
Auditor Agent: price and payer economics.

Computes gross savings from NADAC unit costs and reports whether savings are
gross, net, or risk-adjusted. Spread estimate is a synthetic PBM proxy.
"""

from scripts.models.schemas import ClaimRecord, DrugMapping, CostAnalysis
from scripts.services.pricing_service import get_unit_cost, get_generic_unit_cost, normalize_quantity
from scripts.services.scoring_service import (
    calculate_gross_savings,
    calculate_spread_estimate,
)


def run(claim: ClaimRecord, mapping: DrugMapping) -> CostAnalysis:
    current_cost, pricing_unit = get_unit_cost(claim.ndc, claim.drug_name)
    alt_cost, _ = get_generic_unit_cost(
        mapping.generic_ndc,
        mapping.candidate_alternative.split()[0] if mapping.candidate_alternative else "",
    )

    norm_qty = normalize_quantity(claim.quantity, claim.days_supply, pricing_unit)
    gross = calculate_gross_savings(current_cost, alt_cost, norm_qty)
    spread = calculate_spread_estimate(gross)

    reason_codes = []
    if gross > 0:
        reason_codes.append("LOWER_NADAC_COST")
    if current_cost <= 0:
        reason_codes.append("MISSING_BRAND_NADAC_PRICE")
    if alt_cost <= 0:
        reason_codes.append("MISSING_GENERIC_NADAC_PRICE")

    audit_reason = (
        f"Brand NADAC: ${current_cost:.4f}/{pricing_unit}. "
        f"Generic NADAC: ${alt_cost:.4f}/{pricing_unit}. "
        f"Quantity: {norm_qty:.1f} units. "
        f"Gross savings (gross, not net of rebates or cost-share): ${gross:.2f}. "
        f"Synthetic PBM spread estimate (8% of gross): ${spread:.2f}."
    )

    return CostAnalysis(
        current_unit_cost=current_cost,
        alternative_unit_cost=alt_cost,
        pricing_unit=pricing_unit,
        normalized_quantity=norm_qty,
        days_supply=claim.days_supply,
        gross_savings=round(gross, 2),
        spread_estimate=round(spread, 2),
        audit_reason=audit_reason,
        reason_codes=reason_codes,
    )
