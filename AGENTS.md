# AGENTS.md — PharmaFlow AI Agent Rules

This file is synchronized with CLAUDE.md for compatibility with other AI coding tools.

---

## Project Context

PharmaFlow AI is a payer-side pharmacy benefit analysis dashboard.
It identifies clinically reasonable drug-switch opportunities using:
- Synthetic payer claims data
- CMS NADAC pricing (real, April 2026)
- FDA Orange Book therapeutic equivalence data (real, May 2026)

**Not a medical device. Not clinical decision support for live patient care.**

---

## Four Agents

### Librarian Agent (`scripts/agents/librarian_agent.py`)
- Maps brand drugs to generic alternatives using Orange Book + NADAC
- Classifies equivalence: GENERIC_EQUIVALENT (AB-rated) or THERAPEUTIC_ALTERNATIVE
- Reports mapping confidence and TE code
- Never recommends a switch based on name similarity alone

### Auditor Agent (`scripts/agents/auditor_agent.py`)
- Computes gross pharmacy savings from NADAC unit costs
- Normalizes quantity to NADAC pricing unit (EA/ML/GM)
- Always labels savings as gross (pre-rebate, pre-cost-share)
- Reports synthetic PBM spread estimate (8%) for audit transparency

### Clinician Agent (`scripts/agents/clinician_agent.py`)
- Computes risk-adjusted savings = gross - medical_delta - adherence_penalty
- Uses deterministic switch failure probability table (by diagnosis group + prior failure)
- Reports credible interval (±30%)
- Never removes clinical risk flags to improve ROI

### Social Navigator Agent (`scripts/agents/social_navigator_agent.py`)
- Assesses pharmacy access and adherence risk
- Sets access_override=True when pharmacy_access_score < 0.40
- Access override escalates any band to "Review"

---

## Non-Negotiable Rules

1. **LLMs may not invent drug facts, savings values, or clinical equivalence claims.**
2. **All savings numbers must trace to deterministic Python formulas.**
3. **Recommendation band classifications must use the single THRESHOLDS dict** in `scoring_service.py`.
4. **Outputs must include:** recommendation, gross_savings, risk_adjusted_savings, confidence, reason_codes, safety/access flags.
5. **Never say a patient should switch immediately.** Use "Recommend", "Review", or "Do Not Switch" for payer review.
6. **USE_LLM=false must produce a fully working demo** — no paid API call required.

---

## Phrasing Guide

**Good:**
> "Potential switch candidate for pharmacist/clinician review."
> "Estimated savings opportunity with clinical risk flags."
> "Risk-adjusted savings after expected downstream cost and adherence penalty."

**Bad:**
> "Switch this patient immediately."
> "The AI guarantees this drug is better."
> "This is medically equivalent because it is cheaper."

---

## Data Rules

- All member IDs are synthetic (`SYN-MEMBER-XXXX`).
- NADAC and Orange Book data are real public datasets — label clearly in UI.
- Every savings number shown must be traceable to a formula in `scoring_service.py`.
- Never use LLM text to overwrite deterministic calculations.

See `docs/agents.md` for full agent output schemas.
See `docs/scoring.md` for formula details.
