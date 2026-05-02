# PharmaFlow AI — Deployment Guide

---

## Local Development

```bash
# Clone and set up
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the app (warehouse + synthetic data built automatically on first run)
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# Open in browser
open http://localhost:8000

# Run tests
pytest evals/ -q
```

On first boot, the app will:
1. Ingest Orange Book files → DuckDB
2. Ingest NADAC.csv → DuckDB
3. Build therapeutic equivalence marts
4. Build switch candidates
5. Generate 250 synthetic claims
6. Compute 250 recommendations

Subsequent boots load the cached DuckDB warehouse (< 1 second).

---

## Cloud Run Deployment

### Prerequisites

```bash
export GCP_PROJECT_ID=<your-project-id>
export GCP_REGION=us-central1
export CLOUD_RUN_SERVICE=pharmaflow-ai

gcloud config set project $GCP_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com logging.googleapis.com
```

### Option 1: Cloud Build (recommended)

```bash
gcloud builds submit --config cloudbuild.yaml
```

### Option 2: Manual Docker

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

### Validate Deployment

```bash
SERVICE_URL=$(gcloud run services describe $CLOUD_RUN_SERVICE \
  --region $GCP_REGION --format='value(status.url)')

curl "$SERVICE_URL/health"           # → {"status":"ok"}
curl "$SERVICE_URL/api/dashboard"    # → summary JSON
curl "$SERVICE_URL/api/recommendations" | python3 -m json.tool | head -30
```

---

## Environment Variables

See `.env.example` for all variables. Critical ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_MODE` | `synthetic` | Always `synthetic` for demo |
| `USE_LLM` | `false` | Keep false — no LLM call needed |
| `PORT` | `8080` | Cloud Run sets this automatically |
| `ANTHROPIC_API_KEY` | (empty) | Only needed if USE_LLM=true |

---

## Troubleshooting

**Cold start takes > 30s on Cloud Run:** The DuckDB build runs on first boot. Set Cloud Run minimum instances to 1 to keep warm, or pre-build and mount the DuckDB file.

**`No switch candidates found`:** Orange Book or NADAC files are missing from the image. Check the Dockerfile COPY steps.

**Dashboard loads but table is empty:** Check `/api/recommendations` directly — if it returns an empty list, the switch_candidates mart may have zero rows. Re-run `python -m src.transform.build_equivalence_map` locally to debug.

**Cloud Run logs:**
```bash
gcloud run services logs read $CLOUD_RUN_SERVICE \
  --region $GCP_REGION --limit 100
```
