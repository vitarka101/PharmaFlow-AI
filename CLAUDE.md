# CLAUDE.md

This file is the working constitution for Claude Code in this repository. Keep it short, practical, and focused on what the agent must do correctly for **PharmaFlow AI**.

PharmaFlow AI is a capstone/demo project for payer-side pharmacy benefit analysis. The system identifies clinically reasonable, risk-adjusted drug-switch opportunities using synthetic payer claims data, RxNorm/FDA-style drug mapping, NADAC-style pricing, formulary assumptions, adherence/access signals, and agentic analysis.

This is **not** a medical device, not clinical decision support for live patient care, and must never process real PHI unless the repository is explicitly upgraded for compliance.

---

## Project Goal

Build a deployed payer dashboard that helps an insurance company answer:

> “Where can we reduce pharmacy spend without increasing total cost of care or harming adherence?”

The demo should prioritize:

1. A clear ROI story for insurers.
2. Safe drug-alternative reasoning.
3. Transparent assumptions and traceable calculations.
4. Synthetic but realistic payer-style data.
5. Reproducible local and deployed runs.
6. A simple, convincing UI over unnecessary backend complexity.
7. A Cloud Run deployment that works from a clean checkout.

---

## Non-Negotiable Guardrails

### Healthcare Safety

- Treat all patient-level data in this repo as synthetic unless explicitly documented otherwise.
- Do not introduce, request, store, or display real PHI, real insurance member IDs, names, addresses, phone numbers, MRNs, clinical notes, or real claims tied to identifiable people.
- Do not present recommendations as final medical advice.
- Always phrase outputs as payer-facing review suggestions, for example:
  - “Potential switch candidate for pharmacist/clinician review.”
  - “Estimated savings opportunity with clinical risk flags.”
- If clinical equivalence is uncertain, surface uncertainty instead of forcing a recommendation.
- Preserve the distinction between:
  - generic equivalent,
  - therapeutic alternative,
  - formulary alternative,
  - lower-cost NDC/package,
  - clinically risky switch.
- Never say a patient “should switch immediately.” Use “Recommend,” “Review,” or “Do Not Switch” bands for payer review.

### Data Integrity

- Synthetic data is allowed and expected, but label it clearly in the code, UI, README, and docs.
- Do not fabricate source-backed claims inside code, UI, or README.
- Every savings number shown in the UI must be traceable to a deterministic formula or transformation in code.
- If public data is unavailable, use a deterministic fixture and clearly mark it as fallback/demo data.
- Never hide whether a savings estimate is gross, net, or risk-adjusted.
- Do not use LLM text to overwrite deterministic calculations.

### Agent Behavior

- Agents must be modular and narrow.
- Prefer typed Python functions, Pydantic schemas, and deterministic services over vague LLM reasoning.
- LLMs may summarize, explain, and rank opportunities, but the following must be deterministic Python:
  - drug/cost normalization,
  - gross savings calculation,
  - risk-adjusted savings calculation,
  - recommendation band classification,
  - API response validation.
- Any agent output used in the UI must include:
  - recommendation,
  - estimated gross savings,
  - estimated risk-adjusted savings,
  - uncertainty or confidence,
  - reason codes,
  - safety/access flags.

---

## Intended Product Flow

The demo should feel like a payer workflow:

1. User opens the PharmaFlow dashboard.
2. Dashboard loads synthetic payer claims and drug-pricing fixtures.
3. Backend computes candidate switch opportunities.
4. Agents add structured reasoning around mapping, cost, clinical risk, and access risk.
5. Dashboard displays portfolio-level savings and member/claim-level opportunities.
6. User can inspect why an opportunity is recommended, review-only, or blocked.
7. App can be deployed to Google Cloud Run and accessed through a live URL.

Expected dashboard sections:

- Executive summary cards:
  - total gross savings,
  - total risk-adjusted savings,
  - number of opportunities,
  - number requiring clinical review,
  - number blocked by safety/access risk.
- Opportunity table:
  - member ID or synthetic member key,
  - current drug,
  - candidate alternative,
  - equivalence type,
  - gross savings,
  - risk-adjusted savings,
  - clinical risk,
  - access risk,
  - recommendation band,
  - reason codes.
- Detail panel or expandable row:
  - cost formula inputs,
  - mapping confidence,
  - clinical/access flags,
  - explanation suitable for payer/pharmacist review.
- Synthetic data disclaimer.

---

## Preferred Architecture

Prefer the same simple architecture as the reference project: **one FastAPI service that serves both the API and the static dashboard UI**.

```text
Browser Dashboard
        |
FastAPI app
        |
+----------------------+----------------------+----------------------+----------------------+
| Librarian Agent      | Auditor Agent        | Clinician Agent      | Social Navigator     |
| Drug mapping         | Cost/spread analysis | Risk-adjusted TCOC   | Access/adherence     |
+----------------------+----------------------+----------------------+----------------------+
        |
Synthetic + Public/Fallback Data Layer
```

Do not create a separate React/Vite/Next frontend unless the repo already contains one and the user explicitly wants it preserved.

---

## Preferred Repository Layout

Use this layout unless the existing repo already differs. If the repo differs, inspect the tree first and preserve the existing structure.

```text
.
├── app.py                         # root import target for uvicorn: app:app
├── scripts/
│   ├── __init__.py
│   ├── app.py                     # main FastAPI routes and app wiring
│   ├── agents/
│   │   ├── librarian_agent.py
│   │   ├── auditor_agent.py
│   │   ├── clinician_agent.py
│   │   └── social_navigator_agent.py
│   ├── services/
│   │   ├── data_service.py
│   │   ├── drug_mapping_service.py
│   │   ├── pricing_service.py
│   │   ├── scoring_service.py
│   │   └── recommendation_service.py
│   ├── models/
│   │   └── schemas.py
│   └── data/
│       └── synthetic_generator.py
├── frontend/
│   ├── templates/
│   │   ├── index.html
│   │   └── dashboard.html
│   └── static/
│       ├── css/
│       │   └── styles.css
│       └── js/
│           └── dashboard.js
├── data/
│   ├── synthetic/
│   ├── raw/
│   └── processed/
├── artifacts/
├── evals/
│   └── test_deterministic.py
├── docs/
│   ├── data.md
│   ├── deployment.md
│   ├── scoring.md
│   └── agents.md
├── Dockerfile
├── cloudbuild.yaml
├── .dockerignore
├── .gcloudignore
├── .env.example
├── requirements.txt or pyproject.toml
├── README.md
├── AGENTS.md
└── CLAUDE.md
```

### Root `app.py`

The root `app.py` should stay minimal:

```python
from scripts.app import app
```

This allows Cloud Run and uvicorn to start the app with:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

---

## FastAPI Rules

- Use FastAPI for all routes.
- Use Pydantic models for request/response schemas.
- Keep route handlers thin.
- Put business logic in `scripts/services/`.
- Put agent orchestration in a service or small orchestrator function.
- Mount static assets from `frontend/static`.
- Serve HTML from `frontend/templates` using `FileResponse` unless using a template engine already present.
- Add CORS only if needed. For a backend-served UI, avoid unnecessary CORS complexity.

Expected route pattern:

```text
GET  /                         -> serve dashboard HTML
GET  /health                   -> health check
GET  /api/dashboard            -> summary metrics payload
GET  /api/recommendations      -> list of switch opportunities
GET  /api/recommendations/{id} -> detail for one opportunity, if useful
POST /api/analyze              -> optional analysis endpoint
POST /refresh                  -> optional synthetic/public data refresh job
GET  /refresh/{job_id}         -> optional refresh status polling
```

The health endpoint must return:

```json
{
  "status": "ok"
}
```

---

## UI Rules

Use a simple static dashboard served by FastAPI.

Preferred frontend files:

```text
frontend/templates/index.html
frontend/static/css/styles.css
frontend/static/js/dashboard.js
```

Rules:

- Keep the UI demo-ready and payer-facing.
- Do not introduce `npm`, React, Vite, or a frontend build step unless `package.json` already exists.
- Do not use unexplained “AI score” values.
- Every recommendation card/table row should show:
  - current drug,
  - candidate alternative,
  - equivalence type,
  - gross savings,
  - risk-adjusted savings,
  - clinical risk,
  - access risk,
  - recommendation band,
  - reason codes.
- Add filters for:
  - recommendation band,
  - equivalence type,
  - minimum risk-adjusted savings,
  - clinical/access risk.
- Add a visible synthetic data disclaimer.
- Use clear language for insurance/payer stakeholders.
- Avoid visual complexity that risks breaking the demo.

Good UI language:

```text
Potential switch candidate for pharmacist/clinician review.
Estimated savings opportunity with clinical and access risk flags.
Risk-adjusted savings after expected downstream cost and adherence penalty.
```

Bad UI language:

```text
Switch this patient immediately.
The AI guarantees this drug is better.
This is medically equivalent because it is cheaper.
```

---

## Agent Responsibilities

### Librarian Agent

Responsible for drug identity and mapping.

Use for:

- RxNorm/RxCUI-style mapping.
- Brand-to-generic mapping.
- Ingredient, strength, route, and dose-form matching.
- FDA Orange Book/DailyMed-style metadata when available.
- Distinguishing true generic equivalents from broader therapeutic alternatives.

Avoid:

- Recommending a switch only because names look similar.
- Treating different strengths, routes, or dose forms as interchangeable without flags.

Expected output fields:

```text
source_drug
candidate_alternative
equivalence_type
rxcui
ndc
ingredient
strength
dose_form
mapping_confidence
mapping_reason
```

### Auditor Agent

Responsible for price and payer economics.

Use for:

- NADAC-style unit cost comparison.
- Unit and package normalization.
- Synthetic PBM spread estimation.
- Formulary tier analysis.
- Gross savings calculation.
- Audit-readiness explanation.

Avoid:

- Assuming rebate amounts are known unless present in synthetic data.
- Hiding whether savings are gross, net, or risk-adjusted.

Expected output fields:

```text
current_unit_cost
alternative_unit_cost
normalized_quantity
days_supply
gross_savings
spread_estimate
net_savings_assumption
audit_reason
```

### Clinician Agent

Responsible for risk-adjusted total cost of care.

Use for:

- Switch failure probability.
- Expected downstream medical event cost.
- Prior authorization or contraindication-style synthetic flags.
- Bayesian/probabilistic uncertainty ranges when useful.

Avoid:

- Making real diagnosis or treatment claims.
- Removing clinical risk flags just to improve ROI.

Expected output fields:

```text
clinical_risk_score
switch_failure_probability
expected_medical_cost_delta
risk_adjusted_savings
credible_interval_low
credible_interval_high
clinical_reason_codes
```

### Social Navigator Agent

Responsible for access and adherence feasibility.

Use for:

- Pharmacy access score.
- Distance or pharmacy desert proxy.
- Refill friction.
- Preferred pharmacy availability.
- Adherence risk flags.

Avoid:

- Recommending a lower-cost drug that is inaccessible to the member.
- Treating theoretical savings as realized savings when access risk is high.

Expected output fields:

```text
pharmacy_access_score
adherence_risk_score
preferred_pharmacy_available
access_override
access_reason
```

---

## Core Calculation Rules

Separate deterministic calculations from LLM narration.

### Gross Pharmacy Savings

Use this default structure unless a better documented formula exists:

```text
gross_savings =
    (current_unit_cost - alternative_unit_cost) * normalized_quantity
```

Where:

- unit cost must be normalized to comparable units,
- package size differences must be handled explicitly,
- quantity and days supply must be validated,
- negative or missing costs must be flagged, not silently accepted.

### Expected Medical Cost Delta

```text
expected_medical_cost_delta =
    switch_failure_probability * estimated_downstream_event_cost
```

### Expected Adherence Penalty

```text
expected_adherence_penalty =
    adherence_risk_score * estimated_adherence_cost
```

If `estimated_adherence_cost` is unavailable, use a documented deterministic default from config and label it as an assumption.

### Risk-Adjusted Savings

```text
risk_adjusted_savings =
    gross_savings
    - expected_medical_cost_delta
    - expected_adherence_penalty
```

### Recommendation Bands

Default bands:

```text
Recommend       risk_adjusted_savings > 0 and clinical/access risk is low
Review          savings positive but clinical/access uncertainty is meaningful
Do Not Switch   risk_adjusted_savings <= 0 or safety/access flags are high
```

Do not hard-code thresholds in multiple places. Put them in one config or scoring module.

Example reason codes:

```text
LOWER_NADAC_COST
GENERIC_EQUIVALENT
THERAPEUTIC_ALTERNATIVE
FORMULARY_TIER_IMPROVEMENT
HIGH_CLINICAL_RISK
MODERATE_ACCESS_RISK
LOW_MAPPING_CONFIDENCE
CLINICAL_REVIEW_REQUIRED
ACCESS_REVIEW_REQUIRED
NEGATIVE_RISK_ADJUSTED_SAVINGS
```

---

## Data Rules

### Synthetic Payer Claims Data

Synthetic data should include enough fields to support realistic analysis:

```text
member_id
age_band
sex
zip3
plan_id
claim_id
drug_name
brand_generic_flag
ndc
rxcui
quantity
days_supply
fill_date
paid_amount
member_cost_share
pharmacy_id
prescriber_id
diagnosis_group
adherence_score
prior_switch_failure_flag
estimated_event_cost
preferred_pharmacy_available
pharmacy_access_score
```

Rules:

- Use stable random seeds.
- Keep member identifiers synthetic.
- Prefer `SYN-MEMBER-0001` style IDs.
- Put generated data under `data/synthetic/` or generate at startup.
- Document schemas in `docs/data.md`.

### Public Drug / Price Data

Use public data when feasible, such as:

- RxNav/RxNorm-style mappings.
- FDA Orange Book-style equivalence concepts.
- DailyMed-style metadata.
- NADAC-style unit cost data.
- CMS-style utilization data.

If public APIs/downloads are unavailable during development, create a small deterministic fixture that mirrors the expected schema.

### Data Storage

For a class demo, prefer simple local files:

```text
data/synthetic/claims.csv
data/synthetic/drug_prices.csv
data/synthetic/formulary.csv
data/synthetic/drug_mappings.csv
```

Use DuckDB or SQLite only if it makes the dashboard simpler or faster. Do not add a complex database unless needed.

### Optional GCS Data Push

If the project needs to push generated synthetic data or artifacts to GCP, use Google Cloud Storage.

Environment variables:

```bash
GCS_BUCKET=pharmaflow-ai
GCS_PREFIX=demo
SYNC_DATA_TO_GCS=false
```

Rules:

- Only upload synthetic/demo-safe data.
- Never upload secrets or real PHI.
- Keep upload logic in a script or service, not route handlers.
- Document the command in README or `docs/deployment.md`.

Example command:

```bash
gsutil -m cp -r data/synthetic gs://$GCS_BUCKET/$GCS_PREFIX/data/
```

---

## LLM Rules

Default local/demo mode should work with `USE_LLM=false`.

When LLMs are enabled:

- Keep prompts short and task-specific.
- Prefer structured JSON outputs with Pydantic validation.
- If an LLM response fails validation, retry once with the validation error.
- If it fails again, return a deterministic fallback explanation.
- LLM summaries must cite structured fields from deterministic outputs.
- LLMs must not invent drug facts, savings values, patient history, or clinical equivalence.

Good agent output:

```json
{
  "recommendation": "Review",
  "reason": "Alternative has lower unit cost, but member has moderate adherence risk and limited pharmacy access.",
  "gross_savings": 420.50,
  "risk_adjusted_savings": 175.25,
  "confidence": "medium",
  "reason_codes": ["LOWER_NADAC_COST", "MODERATE_ACCESS_RISK", "CLINICAL_REVIEW_REQUIRED"]
}
```

Bad agent output:

```json
{
  "recommendation": "Switch immediately",
  "reason": "The generic is cheaper and should work."
}
```

---

## Local Development Commands

Before changing commands, inspect `pyproject.toml`, `uv.lock`, `requirements.txt`, `Makefile`, and README.

### If `uv.lock` exists

Prefer `uv`:

```bash
uv sync
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000
uv run pytest -q
```

### If `requirements.txt` exists without `uv.lock`

Use pip:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
pytest -q
```

### Frontend

Do not run frontend package commands unless `package.json` exists.

Preferred static UI workflow:

```bash
# No separate frontend install required.
# Start FastAPI and open http://localhost:8000
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

---

## Testing Expectations

Add or update tests when changing:

- savings formulas,
- unit normalization,
- risk scoring,
- drug mapping,
- recommendation thresholds,
- API response schemas,
- synthetic data generation,
- GCS upload/download utilities.

Minimum useful tests:

- brand-to-generic mapping works for known fixtures,
- dosage form/strength mismatch is flagged,
- unit cost normalization is correct,
- gross savings formula is correct,
- risk-adjusted savings subtracts downstream cost and adherence penalty,
- high clinical risk blocks automatic recommendation,
- low pharmacy access creates review/override behavior,
- API returns valid response schema,
- `/health` returns `{"status": "ok"}`.

Preferred test command:

```bash
pytest -q
```

If using `uv`:

```bash
uv run pytest -q
```

---

## Deployment Rules

Use Google Cloud Platform for the capstone deployment. Prefer Docker + Cloud Build + Cloud Run because this matches the reference project and is reproducible from a clean checkout.

### Default GCP Target

Use these defaults unless the user or repo specifies otherwise:

```bash
GCP_PROJECT_ID=<your-project-id>
GCP_REGION=us-central1
CLOUD_RUN_SERVICE=pharmaflow-ai
```

Enable required services:

```bash
gcloud config set project $GCP_PROJECT_ID

gcloud services enable run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  logging.googleapis.com \
  storage.googleapis.com
```

### Dockerfile Rules

The app must listen on the Cloud Run `PORT` environment variable.

Good Dockerfile command:

```dockerfile
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

If using `uv`:

```dockerfile
CMD ["sh", "-c", "uv run --no-sync uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

Avoid hard-coding only port `8000` or only port `8080` in production startup.

### Preferred `cloudbuild.yaml`

Use this as the default Cloud Build pattern:

```yaml
steps:
  - name: "gcr.io/cloud-builders/docker"
    args: ["build", "-t", "gcr.io/$PROJECT_ID/pharmaflow-ai", "."]

  - name: "gcr.io/cloud-builders/docker"
    args: ["push", "gcr.io/$PROJECT_ID/pharmaflow-ai"]

  - name: "gcr.io/cloud-builders/gcloud"
    args:
      - "run"
      - "deploy"
      - "pharmaflow-ai"
      - "--image=gcr.io/$PROJECT_ID/pharmaflow-ai"
      - "--region=us-central1"
      - "--allow-unauthenticated"
      - "--port=8080"
      - "--memory=2Gi"
      - "--update-env-vars=DATA_MODE=synthetic,USE_LLM=false,SYNC_DATA_TO_GCS=false"

images:
  - "gcr.io/$PROJECT_ID/pharmaflow-ai"
```

Use `--allow-unauthenticated` for the capstone demo unless the user explicitly wants private access.

### Manual Build + Deploy

```bash
gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/pharmaflow-ai

gcloud run deploy $CLOUD_RUN_SERVICE \
  --image gcr.io/$GCP_PROJECT_ID/pharmaflow-ai \
  --region $GCP_REGION \
  --allow-unauthenticated \
  --port 8080 \
  --memory 2Gi \
  --set-env-vars DATA_MODE=synthetic,USE_LLM=false,SYNC_DATA_TO_GCS=false
```

### Deployment Validation

After every deploy, verify:

```bash
SERVICE_URL=$(gcloud run services describe $CLOUD_RUN_SERVICE \
  --region $GCP_REGION \
  --format='value(status.url)')

curl "$SERVICE_URL/health"
curl "$SERVICE_URL/api/dashboard"
curl "$SERVICE_URL/api/recommendations"
```

Then open the service URL in a browser and confirm the dashboard loads.

### GCP Troubleshooting

If deployment fails:

- Check the active project:

```bash
gcloud config get-value project
```

- Check Cloud Run logs:

```bash
gcloud run services logs read $CLOUD_RUN_SERVICE \
  --region $GCP_REGION \
  --limit 100
```

- Confirm:
  - app starts with `uvicorn app:app`,
  - app listens on `0.0.0.0:$PORT`,
  - `requirements.txt`, `pyproject.toml`, or Dockerfile includes runtime dependencies,
  - static files are copied into the image,
  - synthetic data files are copied into the image or generated at startup,
  - `/health` exists,
  - no real secrets are committed.

For advanced deployment troubleshooting, create or read `docs/deployment.md`. Keep the main path simple.

---

## Environment Variables

Document expected variables in `.env.example`.

Recommended defaults:

```bash
DATA_MODE=synthetic
USE_LLM=false
MODEL_NAME=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
CORS_ORIGINS=*
GCS_BUCKET=pharmaflow-ai
GCS_PREFIX=demo
SYNC_DATA_TO_GCS=false
```

Rules:

- Default local development must work with `USE_LLM=false` and synthetic fixtures.
- Never commit real API keys.
- Use Secret Manager or Cloud Run environment configuration for secrets.
- Do not require a paid LLM call for the app to demo successfully.

---

## Documentation Requirements

Keep this file high-level. Do not turn it into a full manual.

Use focused docs:

```text
docs/data.md        -> datasets, schemas, synthetic generation, NADAC/RxNorm notes
docs/scoring.md     -> savings formulas, risk adjustment, thresholds
docs/agents.md      -> agent responsibilities, prompts, schemas
docs/deployment.md  -> Cloud Run, Cloud Build, GCS, troubleshooting
```

The README should include:

- project overview,
- target user,
- problem statement,
- architecture diagram or text architecture,
- setup instructions,
- local run commands,
- deployment URL,
- GCP deployment commands,
- data sources,
- synthetic data disclaimer,
- agent descriptions,
- scoring methodology,
- class concepts used with file references,
- known limitations,
- demo script.

---

## Demo / Capstone Priorities

For the capstone deadline, prioritize in this order:

1. End-to-end dashboard works locally.
2. Cloud Run deployment works.
3. Synthetic data is realistic and clearly documented.
4. Dashboard clearly explains payer savings and risk.
5. Scoring formulas are deterministic and testable.
6. Agents produce structured, inspectable outputs.
7. README explains setup, live URL, architecture, class concepts, and limitations.
8. Optional GCS upload works only for synthetic/demo-safe data.

Avoid spending time on:

- perfect clinical modeling,
- large-scale infrastructure,
- Kubernetes/Terraform,
- complex PDF parsing unless needed for the demo,
- excessive agent autonomy,
- unsupported compliance claims,
- fragile multi-service deployment.

---

## Code Style

- Make code boring, readable, and testable.
- Prefer small functions over large agent scripts.
- Avoid hidden global state.
- Avoid notebook-only logic for production paths.
- Use explicit types for public functions.
- Use Pydantic schemas for API contracts.
- Keep deterministic logic pure where possible.
- Use meaningful names:
  - `normalize_unit_cost`
  - `calculate_gross_savings`
  - `calculate_risk_adjusted_savings`
  - `classify_recommendation`
  - `generate_synthetic_claims`
- Avoid vague names:
  - `process`
  - `magic_score`
  - `run_ai`
  - `final_output`

---

## Safe Implementation Defaults

When making implementation choices, prefer:

- single FastAPI service,
- static HTML/CSS/JS dashboard,
- deterministic synthetic data,
- local CSV/JSON fixtures,
- optional DuckDB/SQLite only if helpful,
- Docker + Cloud Build + Cloud Run,
- `USE_LLM=false` fallback,
- clear disclaimers,
- tests for formulas and API schemas.

Do not add:

- real PHI workflows,
- authentication complexity unless required,
- a separate frontend build system unless already present,
- a production database unless necessary,
- background workers unless the UI needs refresh polling,
- uncontrolled LLM recommendations.

---

## When Unsure

Follow this order:

1. Preserve healthcare safety.
2. Preserve deterministic calculations.
3. Preserve synthetic-data clarity.
4. Preserve demo reliability.
5. Preserve simple deployment.
6. Preserve concise documentation.

If a requested change makes the demo less safe, less traceable, or less reproducible, implement a safer alternative and explain the tradeoff.

---

## AGENTS.md Sync

Keep `AGENTS.md` synchronized with this file for compatibility with other AI coding tools.

When updating this file:

- update `AGENTS.md` with the same agent-facing rules,
- avoid tool-specific instructions unless necessary,
- keep both files concise,
- do not duplicate long docs that belong in `docs/`.
