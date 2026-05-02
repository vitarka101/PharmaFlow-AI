# PharmaFlow AI — Scoring Methodology

All formulas are deterministic Python. Source: `scripts/services/scoring_service.py`.

---

## Formulas

### Gross Pharmacy Savings

```
gross_savings = max((current_unit_cost - alternative_unit_cost) × normalized_quantity, 0)
```

- `current_unit_cost`: NADAC Per Unit for the brand drug ($/unit)
- `alternative_unit_cost`: NADAC Per Unit for the generic alternative ($/unit)
- `normalized_quantity`: claim quantity in NADAC pricing units (EA/ML/GM)
- Negative gross savings are floored to 0 (never report negative gross)
- Missing or zero unit costs produce 0 gross savings (flagged in reason codes)

### Expected Medical Cost Delta

```
expected_medical_cost_delta = switch_failure_probability × estimated_event_cost
```

- `switch_failure_probability`: deterministic lookup by diagnosis group + prior failure flag
- `estimated_event_cost`: synthetic field on the claim; represents expected downstream cost if switch fails

### Expected Adherence Penalty

```
expected_adherence_penalty = (1 - adherence_score) × $150
```

- `adherence_score`: synthetic member-level field (0–1); higher = more adherent
- `$150`: documented assumption for per-fill adherence cost impact (label: `adherence_cost_default`)
- Source: `THRESHOLDS["adherence_cost_default"] = 150.0` in `scoring_service.py`

### Risk-Adjusted Savings

```
risk_adjusted_savings = gross_savings - expected_medical_cost_delta - expected_adherence_penalty
```

Can be negative. Negative risk-adjusted savings → "Do Not Switch" band.

### Synthetic PBM Spread Estimate

```
spread_estimate = gross_savings × 0.08
```

Represents a synthetic 8% PBM spread. Reported for audit transparency. Not subtracted from savings in the main formula (gross and risk-adjusted are pre-spread).

---

## Recommendation Band Classification

All thresholds are in `THRESHOLDS` dict in `scoring_service.py` — never duplicated elsewhere.

| Band | Conditions |
|------|-----------|
| **Recommend** | `risk_adjusted_savings > 0` AND `clinical_risk_score < 0.30` AND `pharmacy_access_score > 0.60` |
| **Review** | `risk_adjusted_savings > 0` AND (clinical_risk_score ≥ 0.30 OR pharmacy_access_score ≤ 0.60) |
| **Do Not Switch** | `risk_adjusted_savings ≤ 0` OR access_override flag |

Access override (from Social Navigator Agent) can escalate a "Recommend" to "Review".

---

## Switch Failure Probability Table

Source: `scripts/agents/clinician_agent.py`. Synthetic deterministic assumptions — not clinical evidence.

| Diagnosis Group | Base Rate | With Prior Failure (×2.5) |
|----------------|-----------|--------------------------|
| CARDIOVASCULAR | 12% | 30% |
| DIABETES | 10% | 25% |
| MENTAL_HEALTH | 22% | 55% |
| RESPIRATORY | 14% | 35% |
| MUSCULOSKELETAL | 8% | 20% |
| GASTROINTESTINAL | 9% | 22.5% |
| ONCOLOGY | 28% | 70% |
| OTHER | 10% | 25% |

TE code modifier:
- AB-rated: × 0.85 (lower failure expected for FDA-verified equivalents)
- BX-rated: × 1.20 (higher uncertainty)

Probability is capped at 0.95.

---

## Credible Interval

```
CI_low  = risk_adjusted_savings × 0.70
CI_high = risk_adjusted_savings × 1.30
```

±30% of the point estimate. Represents modeling uncertainty, not a statistical confidence interval.

---

## Reason Code Reference

| Code | Meaning |
|------|---------|
| `LOWER_NADAC_COST` | Generic has lower NADAC unit cost than brand |
| `GENERIC_EQUIVALENT` | Orange Book AB-rated generic equivalent |
| `THERAPEUTIC_ALTERNATIVE` | Same ingredient, different form or non-AB TE code |
| `LOW_MAPPING_CONFIDENCE` | No TE code available; ingredient-only match |
| `HIGH_CLINICAL_RISK` | Switch failure probability ≥ 20% |
| `MODERATE_CLINICAL_RISK` | Switch failure probability ≥ 10% |
| `PRIOR_SWITCH_FAILURE` | Member has prior switch failure flag |
| `CLINICAL_REVIEW_REQUIRED` | Therapeutic alternative requires clinical sign-off |
| `NEGATIVE_RISK_ADJUSTED_SAVINGS` | Risk-adjusted savings ≤ 0 |
| `LOW_PHARMACY_ACCESS` | Pharmacy access score < 0.40 |
| `MODERATE_ACCESS_RISK` | Pharmacy access score < 0.60 |
| `PREFERRED_PHARMACY_UNAVAILABLE` | Generic not at member's preferred pharmacy |
| `ACCESS_REVIEW_REQUIRED` | Access risk overrides recommendation band |
| `HIGH_ADHERENCE_RISK` | Adherence risk score > 0.50 |
| `MISSING_BRAND_NADAC_PRICE` | Brand unit cost not found in NADAC |
| `MISSING_GENERIC_NADAC_PRICE` | Generic unit cost not found in NADAC |
