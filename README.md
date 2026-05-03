# PharmaFlow AI

> **Live Demo:** [https://pharmaflow-ai-648786197436.us-central1.run.app](https://pharmaflow-ai-648786197436.us-central1.run.app)

---

## What Is This?

PharmaFlow AI is a **payer-side pharmacy benefit intelligence platform** that automatically identifies where an insurance company can save money on drug spend — without compromising member health outcomes.

It ingests a payer's claims data, runs each brand-name drug through a four-agent AI pipeline, and outputs a ranked list of generic switch opportunities with full clinical risk, adherence risk, access risk, and confidence scores — ready for pharmacist review.

> **Not clinical decision support. Not a medical device. All member data is de-identified.  Source: Aetna (redacted).**

---

## The Business Case

### Who Uses This

| User | Problem |
|------|---------|
| **Pharmacy Benefit Managers (PBMs)** | Need to identify generic switch opportunities across millions of claims without manual review |
| **Insurance Payer Analysts** | Need to prioritize which switches are actually worth pursuing after risk adjustment |
| **Clinical Pharmacists** | Need structured, evidence-grounded switch packages to act on recommendations |

### The Problem

US payers spend **$200B+ annually** on brand-name drugs when FDA-approved generic equivalents exist at a fraction of the cost. The challenge is not *finding* the generics — it is knowing **which switches are safe, accessible, and net-positive** after accounting for:

- **Clinical risk**: Will the member have a medical event if they switch?
- **Adherence risk**: Will the member stop taking the drug if they switch?
- **Access risk**: Can the member actually get the alternative drug at their pharmacy?

Manual review by pharmacists costs $80–$150/hour and can only cover a tiny fraction of a payer's book of business. PharmaFlow AI automates the triage.

### Monetization

| Tier | Price | Features |
|------|-------|---------|
| **Gold** | $2,500/month | Full access — all tabs, PDF switch packages, clinical + access risk |
| **Silver** | $1,200/month | Dashboard + Prescription Advisor, no member-level detail, no PDFs |
| **Bronze** | $500/month | Dashboard only, no clinical/access risk columns |

### Unit Economics

- Average payer manages **50,000–500,000 claims/year**
- Industry benchmark: **3–7% of claims** have actionable generic switch opportunity
- Average gross savings per switch: **$800–$2,400/fill cycle**
- PharmaFlow identifies and risk-ranks all candidates automatically
- A single mid-size payer client at Gold tier generates **$30K ARR** with near-zero marginal cost per recommendation

---

## Live Demo

**[→ Open PharmaFlow AI](https://pharmaflow-ai-648786197436.us-central1.run.app)**

### Quick Demo Script

**1. Single drug lookup (Prescription Advisor tab)**
```
Provigil
```
Returns: Modafinil, ~$1,000–$2,400 gross savings/fill cycle, AB-rated generic equivalent.

**2. Natural language query**
```
What can Abilify be replaced with that is cheaper?
```

**3. Multi-drug lookup**
```
Abilify, Lyrica, Diovan
```

**4. Upload a claims CSV**
Upload `data/demo/demo_claims_high_savings.csv` — full portfolio analysis with 10-second animated processing.

**5. Switch to Dashboard tab**
- See portfolio-level savings cards and three charts
- Switch plan from Gold → Silver → Bronze to see tier enforcement
- Expand any row for full agent breakdown (Librarian / Auditor / Clinician / Navigator)
- On Gold: click **Download Switch Package** → 4-PDF ZIP

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Browser UI                                    │
│   Prescription Advisor  │  Dashboard  │  Members                    │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ HTTP / JSON
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                             │
│                      scripts/app.py                                  │
└────────┬────────────────┬─────────────────┬────────────────┬────────┘
         │                │                 │                │
         ▼                ▼                 ▼                ▼
  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
  │  Librarian  │  │   Auditor   │  │  Clinician  │  │   Social    │
  │    Agent    │  │    Agent    │  │    Agent    │  │  Navigator  │
  │ Drug Mapping│  │Cost Analysis│  │ Clinical    │  │   Agent     │
  │             │  │             │  │    Risk     │  │Access/Adher.│
  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
         └────────────────┴─────────────────┴────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   DuckDB Warehouse   ChromaDB RAG   Pandas CSV
   (NADAC + Orange    (Drug Knowledge  (Claims Upload
    Book SQL mart)     Vector Store)   at Runtime)
```

One FastAPI service. No separate frontend build step. No Kubernetes.

---

## Four Agents

### 1. Librarian Agent — Drug Mapping
Maps brand drug names to FDA-approved generic equivalents using the Orange Book and NADAC warehouse.

- 6-step lookup: exact NDC → ingredient prefix → fuzzy match
- Classifies: `GENERIC_EQUIVALENT` (AB-rated TE code) | `THERAPEUTIC_ALTERNATIVE` | `NO_ALTERNATIVE`
- Output schema: `DrugMapping` — source drug, candidate alternative, TE code, dosage form, strength, mapping confidence, reason codes
- **File:** `scripts/agents/librarian_agent.py`

### 2. Auditor Agent — Cost Analysis
Calculates gross pharmacy savings using NADAC unit costs.

- Normalizes claim quantity to NADAC pricing unit (EA / ML / GM)
- Formula: `gross_savings = (brand_unit_cost − generic_unit_cost) × normalized_qty`
- Synthetic PBM spread estimate: `spread = gross_savings × 8%`
- Output schema: `CostAnalysis` — unit costs, normalized quantity, gross savings, spread estimate
- **File:** `scripts/agents/auditor_agent.py`

### 3. Clinician Agent — Risk Adjustment
Estimates risk-adjusted total cost of care.

| Diagnosis Group | Base Failure Rate |
|----------------|------------------|
| MENTAL_HEALTH | 22% |
| ONCOLOGY | 28% |
| CARDIOVASCULAR | 12% |
| RESPIRATORY | 14% |
| DIABETES | 10% |
| MUSCULOSKELETAL | 8% |
| GASTROINTESTINAL | 9% |

- Adjusts for: prior switch failure flag (2.5× multiplier), TE code confidence
- 95% credible interval: ±30% of point estimate
- Output schema: `ClinicalRisk` — risk score, failure probability, medical cost delta, risk-adjusted savings, CI
- **File:** `scripts/agents/clinician_agent.py`

### 4. Social Navigator Agent — Access & Adherence
Assesses whether the member can realistically make the switch.

- Flags: `LOW_PHARMACY_ACCESS` (score < 0.40), `PREFERRED_PHARMACY_UNAVAILABLE`, `HIGH_ADHERENCE_RISK`
- Access override: any access flag escalates "Recommend" → "Review"
- Output schema: `AccessRisk` — pharmacy access score, adherence risk, preferred pharmacy availability, access override
- **File:** `scripts/agents/social_navigator_agent.py`

---

## Recommendation Bands

| Band | Condition |
|------|-----------|
| **Recommend** | risk_adjusted_savings > 0 AND clinical_risk < 30% AND pharmacy_access > 60% |
| **Review** | Savings exist but clinical or access uncertainty is meaningful |
| **Do Not Switch** | risk_adjusted_savings ≤ 0 OR safety/access flags are high |

All thresholds in one place: `scripts/services/scoring_service.py → THRESHOLDS`.

---

## Savings Formula (4-Stage Refinement)

```
Stage 1 (Auditor):
    gross_savings = (brand_unit_cost − generic_unit_cost) × normalized_qty

Stage 2 (Clinician):
    medical_delta = switch_failure_probability × estimated_event_cost

Stage 3 (Clinician):
    adherence_penalty = (1 − adherence_score) × $150

Stage 4 (Scoring):
    risk_adjusted_savings = gross_savings − medical_delta − adherence_penalty
    → classify as Recommend / Review / Do Not Switch
```

The final band only emerges after all four agents have run. Every number is traceable to a deterministic Python formula — the LLM never touches the math.

---

## Class Concepts Applied

This project directly implements **14+ concepts** from the Columbia Agentic AI course syllabus:

### Module 1 — LLMs, Prompt Engineering, and Validation

**Role-based messages (system / user / assistant)**
LLM fallback in `drug_mapping_service.py` constructs a proper `[system, ...history, user]` message array with a PBM assistant persona and injected conversation history.

**Model adapters — LiteLLM**
All LLM calls go through `litellm.completion()`. Switching between `vertex_ai/gemini-2.5-flash-lite`, `anthropic/claude-...`, or `openai/gpt-...` requires only a one-line `.env` change.

**Context / message history / session**
Per-session history keyed by client-generated UUID (`session_id`). Capped at 5 turns server-side (`_chat_sessions`), sent with every LLM call for follow-up context. Client independently maintains `chatHistory` in `chat.js`.

**Deterministic evaluation metrics**
`evals/test_deterministic.py` — 47 tests covering savings formulas, unit normalization, risk scoring, band classification, API schema validation, and drug name extraction. All pass without LLM calls.

---

### Module 2 — Tools, Frameworks, and Data

**RAG pipeline (chunk → index → retrieve → generate)**
When a drug is not in the NADAC/Orange Book warehouse, ChromaDB vector store (30 drug knowledge chunks, embedded via `sentence-transformers/all-MiniLM-L6-v2` — fully local, no API key) retrieves the top-3 relevant chunks and injects them into the LLM prompt as grounding context. File: `scripts/services/rag_service.py`.

```
DuckDB warehouse (6 lookup steps)
        ↓ not found
ChromaDB RAG (top-3 chunks → injected into LLM system prompt)
        ↓ retrieval failure (graceful)
LLM with no extra context
        ↓ USE_LLM=false
NO_ALTERNATIVE returned
```

**Tool contracts and schema validation**
Every agent emits a typed Pydantic v2 model. The LLM fallback path retries once on validation failure before returning a deterministic result.

**Text-to-SQL / NL-to-SQL**
`_extract_drug_names()` uses regex tokenization + stop-word filtering + DuckDB prefix validation (`SELECT 1 FROM nadac WHERE UPPER(ndc_description) LIKE 'KEY%'`) to translate free-text questions into structured warehouse queries.

**Code execution (interpreter pattern)**
The chat endpoint runs deterministic Python at request time: pandas parses uploaded CSV claims, normalizes columns, executes the full 4-agent pipeline per row, and aggregates results — all at request time with no pre-processing step.

**Three distinct data retrieval paths**
DuckDB SQL (warehouse mart), ChromaDB vector search (drug knowledge RAG), and pandas CSV ingestion (member claims at runtime).

---

### Module 3 — Thinking and Planning

**Artifacts**
- **Switch Package**: "Download Switch Package" generates 4 PDFs (Member Summary, Formulary Comparison, Clinical Risk Report, Pharmacist Outreach Letter) via `reportlab`, zipped and returned as `switch_package_{id}.zip`
- **CSV Export**: `/api/export/opportunities.csv` exports filtered opportunities for payer workflow integration

**State, memory, and persistence**
Server-side: `_chat_sessions` dict (UUID-keyed, 5-turn cap). Client-side: `sessionStorage` persists the full chat thread, sidebar stats, and history across tab navigations — survives switching to Dashboard and back without losing state. Cleared only on "New Session".

**Iterative refinement / Plan-Execute**
The 4-stage savings pipeline is a sequential refinement loop where each stage computes a risk penalty and subtracts it from the prior estimate. The final band only emerges after all adjustments are applied.

**Multi-agent orchestration — orchestrator + specialists**
`recommendation_service.py` acts as the orchestrator: it sequences the four specialist agents, collects their typed outputs, merges them into a `Recommendation`, and classifies the final band. Each agent has a single narrow responsibility.

**Parallel portfolio sweep**
The CSV upload endpoint processes every claim row through the full 4-agent pipeline and aggregates all results before returning a single portfolio-level response — simulating a parallel sweep over a payer's book of business.

---

### Module 4 — Agents in the World

**Data Visualization**
Three Chart.js charts rendered client-side from `/api/recommendations`:
- Savings by Band (horizontal bar) — gross vs. risk-adjusted across Recommend / Review / Do Not Switch
- Clinical Risk Distribution (histogram) — opportunities bucketed by risk score
- Top 10 Drugs by Gross Savings (horizontal bar)

---

### Summary Table

| Concept | Implementation |
|---------|----------------|
| Role-based messages | `drug_mapping_service.py → _llm_fallback()` |
| LiteLLM model adapter | `litellm.completion()` — swap model via `.env` |
| Context / history / session | `_chat_sessions` (server) + `chatHistory` + `sessionStorage` (client) |
| Deterministic evaluation | `evals/test_deterministic.py` — 47 tests |
| RAG pipeline | ChromaDB + sentence-transformers → LLM prompt injection |
| Tool contracts + schema validation | Pydantic v2 on all agent I/O, LLM retry on failure |
| Text-to-SQL / NL query | `_extract_drug_names()` → DuckDB prefix validation |
| Code execution (interpreter) | Runtime pandas CSV processing per request |
| Multiple retrieval methods | DuckDB SQL + ChromaDB RAG + pandas CSV |
| Artifacts | 4-PDF switch package (reportlab) + CSV export |
| State, memory, persistence | UUID session history + `sessionStorage` cross-tab |
| Iterative refinement / Plan-Execute | 4-stage savings refinement loop |
| Multi-agent orchestration | Orchestrator + 4 specialist agents |
| Parallel portfolio sweep | CSV upload → per-row pipeline → aggregated response |
| Data Visualization | 3 Chart.js charts on dashboard |

---

## Data Sources

| Source | Type | Description |
|--------|------|-------------|
| CMS NADAC | Real public data | National Average Drug Acquisition Cost — unit pricing for ~20,000 NDCs (April 2026) |
| FDA Orange Book | Real public data | Products, patents, exclusivity, TE codes (May 2026) |
| Aetna Claims | De-identified | 500 member claims — realistic field distributions |
| Demo CSVs | Synthetic | `data/demo/` — high-savings and mixed-risk portfolios for live demo |

---

## API Reference

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Prescription Advisor chat UI |
| GET | `/dashboard` | Payer dashboard |
| GET | `/members` | Member history |
| GET | `/health` | `{"status": "ok"}` |
| GET | `/api/config` | Runtime config (LLM on/off, model name) |
| GET | `/api/dashboard` | Portfolio summary cards |
| GET | `/api/recommendations` | Full opportunity list |
| GET | `/api/members` | Aggregated member stats |
| GET | `/api/members/{id}` | All recommendations for one member |
| POST | `/api/chat/analyze` | Analyze CSV upload or free-text drug query |
| GET | `/api/documents/{id}` | Download 4-PDF switch package as ZIP |
| GET | `/api/export/opportunities.csv` | Export filtered opportunities as CSV |

---

## Local Setup

### Prerequisites
- Python 3.11+
- `uv` (preferred) or pip

### Install & Run

```bash
cd Assignment_3
uv sync

# Copy env defaults (works out of the box — no API keys needed)
cp .env.example .env

# Start server
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000)

### Run Tests

```bash
uv run pytest evals/ -q
# 47 tests, all deterministic, no LLM required
```

---

## LLM Configuration (Optional)

The full demo works with `USE_LLM=false`. LLM is only used for fallback drug summarization when warehouse lookup fails.

```bash
# .env
USE_LLM=True
MODEL_NAME=vertex_ai/gemini-2.5-flash-lite

# Authenticate for Vertex AI
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Any litellm-supported model string works: `anthropic/claude-...`, `openai/gpt-...`, `vertex_ai/...`

---

## Cloud Run Deployment

```bash
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=us-central1
export SERVICE=pharmaflow-ai

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/$SERVICE

gcloud run deploy $SERVICE \
  --image gcr.io/$GCP_PROJECT_ID/$SERVICE \
  --region $GCP_REGION \
  --allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --set-env-vars DATA_MODE=synthetic,USE_LLM=false,SYNC_DATA_TO_GCS=false

# Validate
SERVICE_URL=$(gcloud run services describe $SERVICE --region $GCP_REGION --format='value(status.url)')
curl "$SERVICE_URL/health"
```

---

## Repository Layout

```
.
├── app.py                              # Entrypoint: from scripts.app import app
├── scripts/
│   ├── app.py                          # FastAPI routes and app wiring
│   ├── agents/
│   │   ├── librarian_agent.py          # Drug mapping
│   │   ├── auditor_agent.py            # Cost/savings analysis
│   │   ├── clinician_agent.py          # Clinical risk adjustment
│   │   └── social_navigator_agent.py   # Access/adherence
│   ├── services/
│   │   ├── data_service.py             # DuckDB connection and queries
│   │   ├── drug_mapping_service.py     # Brand-to-generic lookup + RAG + LLM fallback
│   │   ├── pricing_service.py          # NADAC unit cost retrieval
│   │   ├── scoring_service.py          # Savings formulas and band classification
│   │   ├── recommendation_service.py   # Agent orchestration
│   │   ├── document_service.py         # PDF generation (reportlab)
│   │   └── rag_service.py              # ChromaDB vector store + drug knowledge corpus
│   ├── models/
│   │   └── schemas.py                  # Pydantic v2 schemas
│   └── data/
│       └── synthetic_generator.py      # Synthetic claims generator
├── frontend/
│   ├── templates/
│   │   ├── index.html                  # Dashboard
│   │   ├── chat.html                   # Prescription Advisor
│   │   └── members.html                # Member history
│   └── static/
│       ├── css/styles.css
│       └── js/
│           ├── dashboard.js
│           ├── chat.js
│           └── members.js
├── data/
│   ├── synthetic/claims.csv
│   ├── demo/                           # Demo CSVs for live walkthrough
│   └── warehouse/pharmaflow.duckdb     # DuckDB: NADAC + Orange Book
├── evals/
│   └── test_deterministic.py           # 47 deterministic tests
├── Dockerfile
├── cloudbuild.yaml
├── requirements.txt
├── .env.example
└── DEMO_QUESTIONS.txt
```

---

