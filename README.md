# PharmaFlow AI

A payer-side pharmacy benefit analysis platform that identifies clinically sound, risk-adjusted drug-switch opportunities using real public drug pricing data and a four-agent AI pipeline.

**Target User:** Insurance payer analysts, pharmacy benefit managers (PBMs), and pharmacists.

**Problem Statement:** Insurers spend billions annually on brand-name drugs when FDA-approved generic equivalents exist at a fraction of the cost. The challenge is not finding the generics — it is determining which switches are safe, accessible, and worth acting on after accounting for clinical risk, adherence impact, and member access constraints. PharmaFlow AI automates that analysis.

> All member data is synthetic. Not clinical decision support. Not a medical device.

---

## Architecture

```
Browser (Dashboard / Prescription Advisor / Members)
                        │
                   FastAPI App
                        │
     ┌──────────────────┼──────────────┬──────────────────┐
     │                  │              │                  │
 Librarian           Auditor       Clinician       Social Navigator
   Agent              Agent          Agent              Agent
 (Mapping)          (Pricing)    (Clinical Risk)   (Access/Adherence)
     │                  │              │                  │
     └──────────────────┴──────────────┴──────────────────┘
                        │
           DuckDB Warehouse (pharmaflow.duckdb)
                        │
           ┌────────────┴────────────┐
       NADAC Pricing          FDA Orange Book
     (CMS, April 2026)    (Products, Patents,
                           Exclusivity — May 2026)
```

One FastAPI service serves both the API and the static dashboard UI. No separate frontend build step.

---

## Concepts from Class

### Structured Output
All four agents emit typed Pydantic v2 models (`DrugMapping`, `CostAnalysis`, `ClinicalRisk`, `AccessRisk`). These are merged into a final `Recommendation` schema that is validated end-to-end before reaching the API response. No free-form LLM strings are used in savings calculations or drug equivalence decisions.

### Second Data Retrieval Method
The system uses two distinct data retrieval methods:
1. **DuckDB SQL** — queries the `switch_candidates` mart (Orange Book + NADAC join) for drug equivalence lookups and unit cost retrieval
2. **Pandas CSV ingestion** — member claims files uploaded via the Chat UI are parsed with pandas, column-normalized, and run through the full agent pipeline row-by-row at request time

### Parallel Execution
The four agents (Librarian → Auditor → Clinician → Social Navigator) run as independent modules on each claim record. Their outputs are aggregated into the final `Recommendation` object by `recommendation_service.py`. The chat endpoint processes all rows in an uploaded claims CSV and aggregates results before returning a single portfolio-level response — simulating a parallel sweep over a payer's book of business.

### Artifacts
The system produces two categories of persistent artifacts:
- **Switch Package PDFs** — clicking "Download Switch Package" on a Recommend row generates four PDFs via `reportlab`: a Member Summary, Formulary Comparison, Clinical Risk Report, and a Pharmacist Outreach Letter. These are zipped and returned as a downloadable file (`switch_package_{id}.zip`).
- **CSV Export** — `/api/export/opportunities.csv` exports the full filtered opportunity set as a downloadable CSV for payer workflow integration.

### Data Visualization
The Dashboard includes three Chart.js charts rendered client-side from the `/api/recommendations` payload:
- **Savings by Band** (horizontal bar) — gross vs. risk-adjusted savings split across Recommend / Review / Do Not Switch bands
- **Clinical Risk Distribution** (histogram) — count of opportunities bucketed into 20-point clinical risk score ranges
- **Top 10 Drugs by Gross Savings** (horizontal bar) — identifies the highest-impact switch targets in the portfolio

### Code Execution
The Prescription Advisor chat endpoint runs deterministic Python at runtime to process user queries:
- `_extract_drug_names(text)` — NLP-lite extraction using regex tokenization, stop-word filtering, and DuckDB prefix validation to parse drug names out of natural-language questions like "What can Abilify be replaced with that is cheaper?"
- Claims CSV uploads are processed with pandas: column normalization, quantity/days-supply validation, and per-row agent pipeline execution — all at request time with no pre-processing step.

### RAG — Retrieval-Augmented Generation (ChromaDB)
When a drug query hits the chat endpoint and all six warehouse lookup steps fail (the drug is not in the NADAC/Orange Book database), the system falls back to the LLM path. Before calling the LLM, it first queries a **ChromaDB vector store** seeded with a 30-entry drug knowledge corpus:

- The drug name is embedded using `sentence-transformers` (`all-MiniLM-L6-v2`, runs fully locally — no API key)
- Top-3 most semantically relevant chunks are retrieved (drug class, mechanism, switch rationale, clinical cautions, typical savings range)
- Retrieved context is injected into the LLM system prompt as grounding material
- The LLM is explicitly instructed to prefer the retrieved context over its parametric memory

This means a drug like Humira (a biologic not in NADAC) gets a grounded, factual explanation of its biosimilar options rather than a hallucinated response. The ChromaDB collection is seeded in-memory at startup — no persistence file, no external server.

**File:** `scripts/services/rag_service.py`

**Fallback chain for unknown drugs:**
```
DuckDB warehouse (6 lookup steps)
        ↓ not found
ChromaDB RAG retrieval (top-3 chunks → injected into LLM prompt)
        ↓ retrieval failure (graceful)
LLM with no extra context
        ↓ LLM unavailable / USE_LLM=false
NO_ALTERNATIVE returned to user
```

RAG is completely non-blocking — any failure at any stage is caught and logged, and the system continues without it.

### Iterative Refinement
The savings calculation is a four-stage refinement loop where each stage adjusts the estimate downward based on new risk information:

```
Stage 1 (Auditor):    gross_savings      = (brand_cost − generic_cost) × normalized_qty
Stage 2 (Clinician):  − medical_delta    = failure_probability × estimated_event_cost
Stage 3 (Clinician):  − adherence_penalty = (1 − adherence_score) × $150
Stage 4 (Scoring):    risk_adjusted_savings = gross − medical_delta − adherence_penalty
                       → classify as Recommend / Review / Do Not Switch
```

The final band only emerges after all four agents have run and the compounded risk adjustment is complete. Starting from gross savings and refining toward net value is the core loop.

---

## Four Agents

### Librarian Agent — Drug Mapping
Maps brand drug names to FDA-approved generic equivalents using the Orange Book and NADAC warehouse.

- Exact NDC match → fuzzy ingredient match on first token
- Classifies: `GENERIC_EQUIVALENT` (AB-rated TE code) | `THERAPEUTIC_ALTERNATIVE` | `NO_ALTERNATIVE`
- Output: `DrugMapping` — source drug, candidate alternative, TE code, dosage form, strength, mapping confidence (0–1), reason codes
- File: `scripts/agents/librarian_agent.py`

### Auditor Agent — Cost Analysis
Calculates gross pharmacy savings using NADAC unit costs.

- Normalizes claim quantity to NADAC pricing unit (EA / ML / GM)
- Formula: `gross_savings = (brand_unit_cost − generic_unit_cost) × normalized_qty`
- Synthetic PBM spread estimate: `spread = gross_savings × 8%`
- Output: `CostAnalysis` — unit costs, normalized quantity, gross savings, spread estimate
- File: `scripts/agents/auditor_agent.py`

### Clinician Agent — Risk Adjustment
Estimates risk-adjusted total cost of care impact.

- Base switch failure rates by diagnosis group:

| Diagnosis Group | Base Failure Rate |
|----------------|------------------|
| MENTAL_HEALTH | 22% |
| ONCOLOGY | 28% |
| CARDIOVASCULAR | 12% |
| RESPIRATORY | 14% |
| DIABETES | 10% |
| MUSCULOSKELETAL | 8% |
| GASTROINTESTINAL | 9% |

- Adjusts for: prior switch failure flag (2.5× multiplier), TE code confidence (AB ×0.85, BX ×1.20)
- Outputs 95% credible interval (±30% of point estimate)
- Output: `ClinicalRisk` — clinical risk score, switch failure probability, expected medical cost delta, risk-adjusted savings, credible interval
- File: `scripts/agents/clinician_agent.py`

### Social Navigator Agent — Access & Adherence
Assesses pharmacy access and adherence feasibility.

- Flags: `LOW_PHARMACY_ACCESS` (score < 0.40), `PREFERRED_PHARMACY_UNAVAILABLE`, `HIGH_ADHERENCE_RISK`
- Access override: any access flag escalates a "Recommend" to "Review"
- Output: `AccessRisk` — pharmacy access score, adherence risk, preferred pharmacy availability, access override flag
- File: `scripts/agents/social_navigator_agent.py`

---

## Recommendation Bands

| Band | Condition |
|------|-----------|
| **Recommend** | risk_adjusted_savings > 0 AND clinical_risk < 30% AND pharmacy_access > 60% |
| **Review** | Savings exist but clinical or access uncertainty is meaningful |
| **Do Not Switch** | risk_adjusted_savings ≤ 0 OR safety/access flags are high |

All thresholds live in a single `THRESHOLDS` dict in `scripts/services/scoring_service.py` — no duplication.

---

## Plan / Cohort Tiers

The dashboard simulates a product packaging model showing how feature access can be tiered by plan level:

| Feature | Gold | Silver | Bronze |
|---------|------|--------|--------|
| All tabs (Dashboard, Prescription Advisor, Members) | Yes | Members hidden | Members hidden |
| Download Switch Package (4 PDFs) | Yes | No | No |
| Clinical Risk column in table | Yes | Yes | No |
| Access Risk column in table | Yes | Yes | No |
| Max Clinical Risk filter | Yes | Yes | No |

Tier enforcement is client-side JS in `frontend/static/js/dashboard.js → applyPlanTier()`. Gold is the default.

---

## Data Sources

| Source | Type | Description |
|--------|------|-------------|
| CMS NADAC | Real public data | National Average Drug Acquisition Cost — unit pricing for ~20,000 NDCs (April 2026) |
| FDA Orange Book | Real public data | Products, patents, exclusivity, TE codes (May 2026) |
| Synthetic Claims | Synthetic | 500 member claims generated with stable random seed — realistic field distributions |
| Demo CSVs | Synthetic | `data/demo/` — high-savings and mixed-risk portfolios for live walkthrough |

> Synthetic data disclaimer: member IDs, claim IDs, diagnosis groups, adherence scores, and pharmacy access scores are all computer-generated. No real PHI is stored or processed.

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
| GET | `/api/recommendations` | Full opportunity list (filterable by band, equiv type, savings, risk) |
| GET | `/api/recommendations/{id}` | Single opportunity detail |
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

### Install

```bash
cd Assignment_3
uv sync
# or: pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Defaults work with USE_LLM=false — no API keys needed for demo
```

### Run

```bash
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000

### Test

```bash
uv run pytest evals/ -q
```

---

## LLM Configuration (Optional)

The LLM is used only for fallback summarization when deterministic lookup cannot identify a drug. The full demo runs without it (`USE_LLM=false`).

To enable Vertex AI / Gemini:

```bash
# .env
USE_LLM=True
MODEL_NAME=vertex_ai/gemini-2.5-flash-lite

# Authenticate
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Any model string supported by litellm works (`anthropic/claude-...`, `openai/gpt-...`, `vertex_ai/...`).

---

## Cloud Run Deployment

```bash
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=us-central1
export SERVICE=pharmaflow-ai

# Enable required GCP services
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com

# Build and push image
gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/$SERVICE

# Deploy
gcloud run deploy $SERVICE \
  --image gcr.io/$GCP_PROJECT_ID/$SERVICE \
  --region $GCP_REGION \
  --allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --set-env-vars DATA_MODE=synthetic,USE_LLM=false,SYNC_DATA_TO_GCS=false

# Validate
SERVICE_URL=$(gcloud run services describe $SERVICE \
  --region $GCP_REGION --format='value(status.url)')
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
│   │   ├── drug_mapping_service.py     # Brand-to-generic lookup (+ RAG + LLM fallback)
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
├── src/ingest/
│   ├── ingest_nadac.py                 # NADAC → DuckDB
│   └── ingest_orange_book.py           # Orange Book → DuckDB
├── data/
│   ├── synthetic/claims.csv
│   ├── demo/                           # Demo CSVs for live walkthrough
│   ├── processed/                      # Orange Book parquet marts
│   └── warehouse/pharmaflow.duckdb
├── evals/
│   └── test_deterministic.py           # 47 deterministic tests
├── docs/
│   ├── agents.md
│   ├── scoring.md
│   ├── data.md
│   └── deployment.md
├── Dockerfile
├── cloudbuild.yaml
├── requirements.txt
├── .env.example
├── AGENTS.md
├── CLAUDE.md
└── DEMO_QUESTIONS.txt                  # Verified chat queries for demo
```

---

## Demo Script

**Step 1 — Single drug (Prescription Advisor tab)**
```
Provigil
```
Expected: Modafinil, ~$1,000–$2,400 gross savings/fill.

**Step 2 — Natural language**
```
What can Abilify be replaced with that is cheaper?
```

**Step 3 — Multi-drug**
```
Abilify, Lyrica, Diovan
```

**Step 4 — Upload demo CSV**
Upload `data/demo/demo_claims_high_savings.csv` — full portfolio analysis.

**Step 5 — Dashboard tab**
- Default: Gold Plan — all features visible
- Select Silver → Members tab disappears, Download button gone from detail rows
- Select Bronze → Clinical Risk + Access Risk columns also disappear
- Sort by Gross Savings descending
- Expand any row → detail panel (Librarian / Auditor / Clinician / Navigator breakdowns)
- On Gold: click Download Switch Package → downloads 4-PDF ZIP

See `DEMO_QUESTIONS.txt` for the full list of verified working chat queries.

---

## Known Limitations

- Savings are gross NADAC-based estimates (pre-rebate). Net savings after manufacturer rebates are not modeled.
- Clinical risk scores use a simplified diagnosis-group lookup table, not real longitudinal clinical history.
- Pharmacy access scores are synthetic proxies, not real geolocation or network data.
- The LLM (when enabled) is used only for natural-language summarization — never for savings calculations or drug equivalence classification.
- PDF switch packages are generated deterministically; content is illustrative only, not clinically reviewed.

---

## Class Concepts Applied

The following concepts from the Agentic AI for Analytics course syllabus are directly implemented in this project:

---

### Module 1 — LLMs, Prompt Engineering, and Validation

**Role-based formatting (system / user / assistant messages)**
The LLM fallback in `scripts/services/drug_mapping_service.py` constructs a proper message array: a `system` prompt defining the PBM assistant persona, injected conversation `history` (last 5 turns), and the `user` message with the drug name. This matches the role-based formatting pattern from Class 2.

**Model adapters (LiteLLM)**
All LLM calls go through `litellm.completion()` (`drug_mapping_service.py`). Switching between `vertex_ai/gemini-2.5-flash-lite`, `anthropic/claude-...`, or `openai/gpt-...` requires only a one-line `.env` change — no code changes. This is the LiteLLM adapter pattern from Class 2.

**Context vs. message history vs. session**
The chat endpoint (`scripts/app.py`) maintains per-session message history keyed by a client-generated UUID (`session_id`). History is capped at 5 messages server-side (`_chat_sessions`) and passed to the LLM for context continuity. The client (`frontend/static/js/chat.js`) independently tracks `chatHistory` and sends it with each request. This directly implements the context/history/session separation from Class 2.

**Evaluation — deterministic metrics**
`evals/test_deterministic.py` contains 47 tests covering savings formulas, unit normalization, risk scoring, band classification, API schema validation, natural-language drug extraction, and CSV parsing. All tests are deterministic (no LLM mocking required), matching the deterministic metrics evaluation pattern from Class 3.

---

### Module 2 — Tools, Frameworks, and Data

**Text-to-SQL / Natural Language to SQL**
The Prescription Advisor chat accepts free-text questions like "What can Abilify be replaced with that is cheaper?" The `_extract_drug_names()` function (`scripts/app.py`) uses regex tokenization + stop-word filtering + DuckDB prefix validation (`SELECT 1 FROM nadac WHERE UPPER(ndc_description) LIKE 'KEY%'`) to extract drug names and translate them into structured warehouse queries. This is the NL-to-SQL / schema-injection pattern from Class 7.

**Code execution (the code interpreter pattern)**
The chat endpoint runs deterministic Python at request time: it parses uploaded CSV claims with pandas, normalizes columns, executes the full 4-agent savings pipeline per row, and aggregates results before returning — all without a pre-processing step. This matches the code interpreter pattern from Class 7.

**Structured output with schema validation**
Every agent emits a typed Pydantic v2 model (`DrugMapping`, `CostAnalysis`, `ClinicalRisk`, `AccessRisk`). These are merged into a `Recommendation` schema validated end-to-end. The LLM fallback path retries once on validation failure before falling back to a deterministic result. This matches the tool contracts and schema validation pattern from Class 5.

**Retrieval-Augmented Generation (RAG) — ChromaDB**
When a drug is not found in the NADAC/Orange Book warehouse, the system queries a ChromaDB vector store (seeded with 30 drug knowledge chunks, embedded locally via `sentence-transformers`). The top-3 retrieved chunks are injected into the LLM system prompt as grounding context before generation. This is the naive RAG pipeline from Class 4: chunk → index → retrieve → generate, applied to drug knowledge rather than documents.

**Second data retrieval method (SQL + RAG + CSV — three distinct paths)**
The system uses three distinct retrieval methods: DuckDB SQL (warehouse mart queries), ChromaDB vector search (drug knowledge RAG), and pandas CSV ingestion (member claims uploaded at runtime). This exceeds the dual-retrieval requirement from Project 2.

---

### Module 3 — Thinking and Planning

**Artifacts**
The system generates two categories of persistent artifacts (Class 8):
- **Switch Package** — clicking "Download Switch Package" generates four PDFs (Member Summary, Formulary Comparison, Clinical Risk Report, Pharmacist Outreach Letter) via `reportlab`, zipped and returned as `switch_package_{id}.zip` (`scripts/services/document_service.py`)
- **CSV Export** — `/api/export/opportunities.csv` exports the filtered opportunity set for payer workflow integration

**State, memory, and persistence**
Session state is maintained server-side in `_chat_sessions` (a dict keyed by UUID) and client-side in `chatHistory` (capped at 10 entries). The LLM receives the trimmed history on every call so it can answer follow-up questions with prior drug context. This implements the episodic memory pattern from Class 8.

**Multi-agent orchestration**
Four specialist agents (Librarian, Auditor, Clinician, Social Navigator) run as independent modules per claim, each with a narrow, typed responsibility. `recommendation_service.py` acts as the orchestrator, sequencing their outputs and merging them into a final `Recommendation`. This is the orchestrator + specialist pattern from Class 10.

**Iterative refinement loop**
The savings pipeline is a four-stage refinement loop where each stage adjusts the prior estimate (Class 9 — Plan-Execute pattern):
```
Stage 1 (Auditor):    gross_savings      = (brand_cost − generic_cost) × normalized_qty
Stage 2 (Clinician):  − medical_delta    = failure_probability × estimated_event_cost
Stage 3 (Clinician):  − adherence_penalty = (1 − adherence_score) × $150
Stage 4 (Scoring):    risk_adjusted_savings → Recommend / Review / Do Not Switch
```

---

### Module 4 — Agents in the World

**Data Visualization**
The Dashboard renders three Chart.js charts client-side from the `/api/recommendations` payload (Class 7 / Class 11 — generative UI pattern):
- Savings by Band (horizontal bar) — gross vs. risk-adjusted across Recommend / Review / Do Not Switch
- Clinical Risk Distribution (histogram) — opportunities bucketed by risk score
- Top 10 Drugs by Gross Savings (horizontal bar)

**Parallel execution across a portfolio**
The chat endpoint processes every row in an uploaded claims CSV through the full 4-agent pipeline and aggregates all results before returning a single response, simulating a parallel sweep over a payer's book of business (Class 10 — multi-agent aggregation pattern).

---

### Summary Table

| Course Concept | Class | Where in This Project |
|----------------|-------|----------------------|
| Role-based messages (system/user/assistant) | Class 2 | `drug_mapping_service.py → _llm_fallback()` |
| Model adapters (LiteLLM) | Class 2 | `litellm.completion()` — swap model via `.env` |
| Context / message history / session | Class 2 | `_chat_sessions` (server) + `chatHistory` (client JS) |
| Deterministic evaluation metrics | Class 3 | `evals/test_deterministic.py` — 47 tests |
| Tool contracts and schema validation | Class 5 | Pydantic v2 schemas on all agent I/O |
| RAG pipeline (chunk → index → retrieve → generate) | Class 4 | ChromaDB + sentence-transformers → LLM prompt injection for unknown drugs |
| Text-to-SQL / NL query | Class 7 | `_extract_drug_names()` → DuckDB prefix validation |
| Code execution (interpreter pattern) | Class 7 | Runtime pandas CSV processing per request |
| Second data retrieval method | Project 2 | DuckDB SQL + ChromaDB RAG + pandas CSV (three distinct paths) |
| Artifacts | Class 8 | 4-PDF switch package (reportlab) + CSV export |
| State, memory, and persistence | Class 8 | Per-session chat history (UUID-keyed, capped at 5) |
| Iterative refinement / Plan-Execute | Class 9 | 4-stage savings refinement loop |
| Multi-agent orchestration | Class 10 | Orchestrator (`recommendation_service`) + 4 specialists |
| Parallel execution / aggregation | Class 10 | CSV portfolio sweep → aggregated single response |
| Data Visualization | Class 7/11 | Chart.js: 3 charts on dashboard |

---

*PharmaFlow AI — Columbia University Agentic AI Capstone · 2026 · Synthetic demo data only.*
