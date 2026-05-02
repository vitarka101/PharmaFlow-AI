# PharmaFlow AI — Agent Descriptions

All agents run deterministically (USE_LLM=false). Each agent takes typed Pydantic inputs and returns a typed Pydantic output. No LLM call is made in the default configuration.

---

## Librarian Agent (`scripts/agents/librarian_agent.py`)

**Responsibility:** Drug identity and mapping.

Delegates to `drug_mapping_service.map_drug()` which queries `marts.switch_candidates` (a DuckDB view joining Orange Book + NADAC).

**Lookup order:**
1. Exact brand NDC match in `switch_candidates`
2. Fuzzy match: first word of drug name against ingredient key

**Equivalence classification:**
- `GENERIC_EQUIVALENT`: Orange Book AB-rated (TE code starts with "AB") — high confidence (0.95)
- `THERAPEUTIC_ALTERNATIVE`: TE code present but not AB, or ingredient-only match — medium confidence (0.60–0.75)
- `NO_ALTERNATIVE`: no match found — agent pipeline stops, claim is skipped

**Output:** `DrugMapping` (source_drug, candidate_alternative, generic_ndc, equivalence_type, te_code, dosage_form_route, strength, mapping_confidence, mapping_reason, reason_codes)

---

## Auditor Agent (`scripts/agents/auditor_agent.py`)

**Responsibility:** Price and payer economics.

Queries `raw_nadac.nadac_prices` for unit costs of both brand and generic. Calls `scoring_service.calculate_gross_savings()`.

**Normalizes quantity** via `pricing_service.normalize_quantity()` (EA/ML/GM multipliers).

**Reports transparently:**
- gross savings is pre-rebate, pre-cost-share
- PBM spread estimate (8% of gross) is synthetic and labeled as such
- Flags missing NADAC prices as reason codes rather than silently using 0

**Output:** `CostAnalysis` (current_unit_cost, alternative_unit_cost, pricing_unit, normalized_quantity, days_supply, gross_savings, spread_estimate, audit_reason, reason_codes)

---

## Clinician Agent (`scripts/agents/clinician_agent.py`)

**Responsibility:** Risk-adjusted total cost of care.

Uses a deterministic lookup table for switch failure probability, keyed on:
- `diagnosis_group` (base rate)
- `prior_switch_failure_flag` (×2.5 multiplier if True)
- `te_code` quality (×0.85 for AB, ×1.20 for BX)

Calculates:
```
risk_adjusted_savings = gross_savings - (failure_prob × event_cost) - (adherence_risk × $150)
```

Credible interval: ±30% of point estimate.

**Clinical guardrails:**
- Never removes risk flags to improve ROI
- ONCOLOGY and MENTAL_HEALTH always have elevated base rates
- Prior failure flag always increases failure probability

**Output:** `ClinicalRisk` (clinical_risk_score, switch_failure_probability, expected_medical_cost_delta, risk_adjusted_savings, credible_interval_low/high, clinical_reason_codes)

---

## Social Navigator Agent (`scripts/agents/social_navigator_agent.py`)

**Responsibility:** Pharmacy access and adherence feasibility.

Uses claim fields:
- `pharmacy_access_score` (0–1): synthetic proxy for member's pharmacy access
- `preferred_pharmacy_available` (0/1): whether generic is at member's preferred pharmacy
- `adherence_score` (0–1): member's historical adherence

**Access override:** if `pharmacy_access_score < 0.40`, sets `access_override = True`, which escalates the recommendation band from Recommend → Review regardless of savings.

**Does not recommend a switch** when access is critically low, even if savings are high.

**Output:** `AccessRisk` (pharmacy_access_score, adherence_risk_score, preferred_pharmacy_available, access_override, access_reason, reason_codes)

---

## Orchestration (`scripts/services/recommendation_service.py`)

```python
mapping  = librarian_agent.run(claim)         # drug identity
cost     = auditor_agent.run(claim, mapping)   # cost analysis
clinical = clinician_agent.run(claim, mapping, cost)  # risk adjustment
access   = navigator_agent.run(claim)          # access/adherence
band     = classify_recommendation(clinical.risk_adjusted_savings,
                                   clinical.clinical_risk_score,
                                   access.pharmacy_access_score)
if access.access_override:
    band = "Review"
```

Reason codes are merged from all 4 agents (deduplicated, order preserved).
