# PharmaFlow AI

**Payer-side pharmacy benefit analysis dashboard** — a capstone demo for payer/PBM drug-switch opportunity identification.

> ⚠️ **Synthetic Data Notice:** All member identifiers and claims are synthetically generated. Drug pricing is sourced from CMS NADAC (April 2026). Drug equivalence data is from the FDA Orange Book. This tool is not clinical decision support and must not be used for real patient care or coverage decisions.

---

## Problem Statement

Insurance payers spend billions annually on brand drugs when FDA-approved generic equivalents exist at a fraction of the cost. Identifying which switches are clinically safe, economically justified, and accessible to members requires combining drug equivalence data, real pricing, and member-level risk signals — a multi-signal analysis that currently happens manually or not at all.

**PharmaFlow AI answers:** *"Where can we reduce pharmacy spend without increasing total cost of care or harming adherence?"*

---

## Live Demo

> Deployed URL: *(add Cloud Run URL after deployment)*

---

## Architecture

```
Browser Dashboard
      |
FastAPI (scripts/app.py) — serves API + static HTML
      |
Recommendation Service — orchestrates 4 agents per claim
      |
+-------------+-------------+-------------+-------------------+
| Librarian   | Auditor     | Clinician   | Social Navigator  |
| OB mapping  | NADAC cost  | Risk TCOC   | Access/adherence  |
+-------------+-------------+-------------+-------------------+
      |
DuckDB warehouse (data/warehouse/pharmaflow.duckdb)
      |
FDA Orange Book   +   CMS NADAC   +   Synthetic Claims
```

---

## Setup & Local Run

**Requirements:** Python 3.11+ (tested on 3.13)

```bash
git clone <repo>
cd Assignment_3

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start (warehouse + synthetic data built automatically on first run)
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Open dashboard
open http://localhost:8000

# Run tests (25 tests)
pytest evals/ -q
```

First boot takes ~10s to build the DuckDB warehouse. Subsequent boots are instant.

---

## GCP Deployment

```bash
export GCP_PROJECT_ID=<your-project-id>

# Cloud Build + Cloud Run (one command)
gcloud builds submit --config cloudbuild.yaml

# Validate
SERVICE_URL=$(gcloud run services describe pharmaflow-ai \
  --region us-central1 --format='value(status.url)')
curl "$SERVICE_URL/health"
```

See `docs/deployment.md` for full instructions and troubleshooting.

---

## Data Sources

| Source | Description | Status |
|--------|-------------|--------|
| CMS NADAC (April 2026) | Drug unit pricing (30,292 rows) | Real public data |
| FDA Orange Book (May 2026) | Therapeutic equivalence, brand vs. generic (48,083 products) | Real public data |
| Synthetic claims | 250 member claims, seeded from real NADAC drugs | Synthetic (`SYN-MEMBER-XXXX`) |

---

## Scoring Methodology

All calculations are deterministic Python (no LLM involvement by default).

```
gross_savings          = (brand_cost - generic_cost) × quantity
medical_cost_delta     = switch_failure_prob × event_cost
adherence_penalty      = (1 - adherence_score) × $150
risk_adjusted_savings  = gross_savings - medical_cost_delta - adherence_penalty
```

Recommendation bands:
- **Recommend** — risk_adj_savings > 0, clinical risk < 30%, pharmacy access > 60%
- **Review** — savings positive but clinical or access uncertainty
- **Do Not Switch** — risk_adj_savings ≤ 0 or high access risk

Full details: `docs/scoring.md`

---

## Agents

| Agent | Responsibility | Key Output |
|-------|---------------|-----------|
| Librarian | Drug mapping via Orange Book + NADAC | equivalence_type, te_code, mapping_confidence |
| Auditor | NADAC unit cost comparison | gross_savings, spread_estimate |
| Clinician | Risk-adjusted TCOC | clinical_risk_score, risk_adjusted_savings, credible_interval |
| Social Navigator | Pharmacy access + adherence | pharmacy_access_score, access_override |

See `docs/agents.md` and `AGENTS.md` for details.

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard HTML |
| `GET /health` | `{"status": "ok"}` |
| `GET /api/dashboard` | Portfolio summary cards |
| `GET /api/recommendations` | Switch opportunities (filterable) |
| `GET /api/recommendations/{id}` | Single opportunity detail |

Filter params on `/api/recommendations`: `band`, `equivalence_type`, `min_risk_adjusted_savings`, `max_clinical_risk`, `max_access_risk`.

---

## Class Concepts Used

| Concept | Where |
|---------|-------|
| Agentic AI — multi-agent pipeline | `scripts/agents/` + `scripts/services/recommendation_service.py` |
| Deterministic vs. LLM reasoning | `scripts/services/scoring_service.py` (pure Python) vs. optional LLM summary |
| Pydantic schemas for agent I/O | `scripts/models/schemas.py` |
| DuckDB data warehouse | `data/warehouse/pharmaflow.duckdb`, `src/ingest/`, `src/transform/` |
| FastAPI + static frontend | `scripts/app.py`, `frontend/` |
| Cloud Run deployment | `Dockerfile`, `cloudbuild.yaml` |
| Real public data integration | CMS NADAC CSV + FDA Orange Book tilde-delimited files |

---

## Known Limitations

- Drug-name matching uses first-word ingredient heuristic; complex trade names may not resolve. OB trade_name lookup improves accuracy.
- Strength mismatches (e.g., 300 mg brand → 25 mg generic) are not dose-normalized; the Clinician agent flags these as requiring review.
- No rebate or net cost modeling — all savings are gross NADAC deltas.
- Adherence penalty ($150/fill) and failure probability table are synthetic assumptions, not evidence-based.
- No real member data, PHI, or live claims integration.

---

## Demo Script

1. Open `http://localhost:8000`
2. Note the **Synthetic Data disclaimer** at the top
3. Review the **Executive Summary cards** — $600K gross savings, $500K risk-adjusted across 250 opportunities
4. Filter by **Band = Recommend** — 141 high-confidence switches
5. Click any row **expand arrow** to see the Detail Panel:
   - Librarian: drug mapping confidence, TE code (AB = FDA-approved equivalent)
   - Auditor: exact NADAC unit costs (traceable to CMS public data)
   - Clinician: switch failure probability, risk-adjusted savings with CI
   - Social Navigator: pharmacy access score, adherence risk
6. Filter by **Band = Do Not Switch** — 10 cases where risk outweighs savings
7. Show `/api/dashboard` and `/api/recommendations` JSON directly for technical reviewers
