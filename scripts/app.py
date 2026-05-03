"""
FastAPI application: serves dashboard UI, members history, and chat pages + API.

Routes:
  GET  /                         → Prescription Advisor (chat) HTML  ← primary landing page
  GET  /dashboard                → payer dashboard HTML
  GET  /members                  → members history HTML
  GET  /chat                     → redirect alias → /
  GET  /health                   → {"status": "ok"}
  GET  /api/dashboard            → DashboardSummary JSON
  GET  /api/recommendations      → list[Recommendation] JSON
  GET  /api/recommendations/{id} → single Recommendation JSON
  GET  /api/members              → member-level aggregates
  GET  /api/members/{member_id}  → all recommendations for one member
  POST /api/chat/analyze         → analyze uploaded CSV or drug name query
  GET  /api/documents/{id}       → download 4-PDF switch package as zip
"""

from __future__ import annotations

import io
import csv
import json
import os
import re
import random
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()  # load .env before any os.getenv calls

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"

_recommendations: list = []
_chat_sessions: dict[str, list] = {}  # session_id → last-5 message dicts


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _recommendations
    from scripts.services.data_service import ensure_warehouse
    ensure_warehouse()
    from scripts.services.recommendation_service import get_all_recommendations
    _recommendations = get_all_recommendations()
    print(f"Loaded {len(_recommendations)} recommendations.")
    yield


app = FastAPI(
    title="PharmaFlow AI",
    description="Payer-side pharmacy benefit analysis dashboard (synthetic demo data).",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    ico = STATIC_DIR / "favicon.ico"
    if ico.exists():
        return FileResponse(str(ico))
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_chat() -> FileResponse:
    return FileResponse(str(TEMPLATES_DIR / "chat.html"))


@app.get("/dashboard", include_in_schema=False)
async def serve_dashboard() -> FileResponse:
    return FileResponse(str(TEMPLATES_DIR / "index.html"))


# ---------------------------------------------------------------------------
# Runtime config check
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def get_config():
    return {
        "use_llm": os.getenv("USE_LLM", "false"),
        "model_name": os.getenv("MODEL_NAME", ""),
        "data_mode": os.getenv("DATA_MODE", "synthetic"),
        "recommendations_loaded": len(_recommendations),
    }


@app.get("/members", include_in_schema=False)
async def serve_members() -> FileResponse:
    return FileResponse(str(TEMPLATES_DIR / "members.html"))


@app.get("/chat", include_in_schema=False)
async def serve_chat_alias() -> RedirectResponse:
    return RedirectResponse(url="/")


# ---------------------------------------------------------------------------
# API: health + existing dashboard/recommendations
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/dashboard")
async def get_dashboard():
    from scripts.services.recommendation_service import get_dashboard_summary
    summary = get_dashboard_summary(_recommendations)
    return summary.model_dump()


@app.get("/api/recommendations")
async def get_recommendations(
    band: Optional[str] = Query(None),
    equivalence_type: Optional[str] = Query(None),
    min_risk_adjusted_savings: Optional[float] = Query(None),
    max_clinical_risk: Optional[float] = Query(None),
    max_access_risk: Optional[float] = Query(None),
    member_id: Optional[str] = Query(None),
):
    recs = _recommendations

    if member_id:
        recs = [r for r in recs if r.member_id == member_id]
    if band:
        recs = [r for r in recs if r.recommendation_band.lower() == band.lower()]
    if equivalence_type:
        recs = [r for r in recs if r.equivalence_type.lower() == equivalence_type.lower()]
    if min_risk_adjusted_savings is not None:
        recs = [r for r in recs if r.risk_adjusted_savings >= min_risk_adjusted_savings]
    if max_clinical_risk is not None:
        recs = [r for r in recs if r.clinical_risk_score <= max_clinical_risk]
    if max_access_risk is not None:
        recs = [r for r in recs if r.access_risk_score <= max_access_risk]

    return [r.model_dump() for r in recs]


@app.get("/api/recommendations/{recommendation_id}")
async def get_recommendation_detail(recommendation_id: str):
    for r in _recommendations:
        if r.recommendation_id == recommendation_id:
            return r.model_dump()
    raise HTTPException(status_code=404, detail="Recommendation not found.")


# ---------------------------------------------------------------------------
# API: members history
# ---------------------------------------------------------------------------

@app.get("/api/members")
async def get_members():
    """Return one summary row per member, aggregated from all their recommendations."""
    by_member: dict[str, dict] = {}
    for r in _recommendations:
        mid = r.member_id
        if mid not in by_member:
            by_member[mid] = {
                "member_id": mid,
                "claim_count": 0,
                "total_gross_savings": 0.0,
                "total_risk_adjusted_savings": 0.0,
                "recommend_count": 0,
                "review_count": 0,
                "do_not_switch_count": 0,
                "drugs": [],
                "bands": [],
            }
        m = by_member[mid]
        m["claim_count"] += 1
        m["total_gross_savings"] += r.gross_savings
        m["total_risk_adjusted_savings"] += r.risk_adjusted_savings
        if r.recommendation_band == "Recommend":
            m["recommend_count"] += 1
        elif r.recommendation_band == "Review":
            m["review_count"] += 1
        else:
            m["do_not_switch_count"] += 1
        if r.current_drug not in m["drugs"]:
            m["drugs"].append(r.current_drug)
        m["bands"].append(r.recommendation_band)

    members = []
    for m in by_member.values():
        m["total_gross_savings"] = round(m["total_gross_savings"], 2)
        m["total_risk_adjusted_savings"] = round(m["total_risk_adjusted_savings"], 2)
        m["drug_count"] = len(m["drugs"])
        # Overall band: worst band wins
        if m["do_not_switch_count"] > 0:
            m["overall_band"] = "Do Not Switch"
        elif m["review_count"] > 0:
            m["overall_band"] = "Review"
        else:
            m["overall_band"] = "Recommend"
        members.append(m)

    members.sort(key=lambda x: x["total_risk_adjusted_savings"], reverse=True)
    return members


@app.get("/api/members/{member_id}")
async def get_member_detail(member_id: str):
    """Return all recommendations for a specific member."""
    recs = [r.model_dump() for r in _recommendations if r.member_id == member_id]
    if not recs:
        raise HTTPException(status_code=404, detail="Member not found.")
    return {
        "member_id": member_id,
        "recommendations": recs,
        "total_gross_savings": round(sum(r["gross_savings"] for r in recs), 2),
        "total_risk_adjusted_savings": round(sum(r["risk_adjusted_savings"] for r in recs), 2),
    }


# ---------------------------------------------------------------------------
# API: chat / upload analysis
# ---------------------------------------------------------------------------

@app.post("/api/chat/analyze")
async def chat_analyze(
    file: Optional[UploadFile] = File(None),
    drug_query: Optional[str] = Form(None),
    member_context: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    history: Optional[str] = Form(None),
):
    """
    Analyze an uploaded claims CSV or a free-text drug name query.
    session_id: client-generated UUID for chat memory
    history: JSON array of {role, content} dicts (last 5 messages from client)
    """
    from scripts.services.recommendation_service import build_recommendation, _coerce_claim
    from scripts.services.drug_mapping_service import map_drug

    # ── Restore / parse chat history ──────────────────────────────────────
    chat_history: list = []
    if session_id and session_id in _chat_sessions:
        chat_history = _chat_sessions[session_id]
    elif history:
        try:
            parsed = json.loads(history)
            if isinstance(parsed, list):
                chat_history = parsed[-5:]
        except (json.JSONDecodeError, ValueError):
            pass

    results = []
    mode = "unknown"

    # ── Mode 1: CSV file upload ────────────────────────────────────────────
    if file and file.filename and file.filename.lower().endswith(".csv"):
        mode = "csv"
        content = await file.read()
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)

        if not rows:
            return _chat_error("Uploaded CSV is empty.")

        col_keys = {k.strip().lower() for k in rows[0].keys()}
        if "drug_name" not in col_keys:
            return _chat_error(
                "CSV must have a 'drug_name' column. "
                "Optional columns: ndc, quantity, days_supply, member_id, diagnosis_group, "
                "adherence_score, prior_switch_failure_flag, estimated_event_cost, "
                "preferred_pharmacy_available, pharmacy_access_score."
            )

        for i, row in enumerate(rows[:50]):
            row = {k.strip().lower(): v.strip() for k, v in row.items()}
            try:
                claim_data = {
                    "claim_id": row.get("claim_id", f"UPLOAD-{i+1:04d}"),
                    "member_id": row.get("member_id", "UPLOAD-MEMBER"),
                    "age_band": row.get("age_band", "45-54"),
                    "sex": row.get("sex", "F"),
                    "zip3": row.get("zip3", "100"),
                    "plan_id": row.get("plan_id", "UPLOADED-PLAN"),
                    "drug_name": row["drug_name"],
                    "brand_generic_flag": row.get("brand_generic_flag", "B"),
                    "ndc": row.get("ndc", ""),
                    "quantity": float(row.get("quantity", 30) or 30),
                    "days_supply": int(float(row.get("days_supply", 30) or 30)),
                    "fill_date": row.get("fill_date", "2024-01-01"),
                    "paid_amount": float(row.get("paid_amount", 0) or 0),
                    "member_cost_share": float(row.get("member_cost_share", 0) or 0),
                    "pharmacy_id": row.get("pharmacy_id", "PHX-UPLOAD"),
                    "prescriber_id": row.get("prescriber_id", "NPI-UPLOAD"),
                    "diagnosis_group": row.get("diagnosis_group", "OTHER"),
                    "adherence_score": float(row.get("adherence_score", 0.80) or 0.80),
                    "prior_switch_failure_flag": int(float(row.get("prior_switch_failure_flag", 0) or 0)),
                    "estimated_event_cost": float(row.get("estimated_event_cost", 500) or 500),
                    "preferred_pharmacy_available": int(float(row.get("preferred_pharmacy_available", 1) or 1)),
                    "pharmacy_access_score": float(row.get("pharmacy_access_score", 0.75) or 0.75),
                }
                claim = _coerce_claim(claim_data)
                rec = build_recommendation(claim)
                if rec:
                    results.append(rec.model_dump())
            except Exception as e:
                results.append({
                    "error": str(e),
                    "drug_name": row.get("drug_name", "unknown"),
                    "skipped": True,
                })

    # ── Mode 2: Drug name text query ───────────────────────────────────────
    elif drug_query and drug_query.strip():
        raw_query = drug_query.strip()
        lowered = raw_query.lower()

        # Out-of-context guard
        if lowered.strip() in {"hello", "hi", "hey", "thanks", "help", "bye"}:
            return _chat_out_of_context()

        # Extract actual drug names from natural-language questions.
        # e.g. "Can I switch to tadalafil instead of cialis 20mg?" → ["tadalafil", "cialis"]
        drug_names = _extract_drug_names(raw_query)
        if not drug_names:
            return _chat_out_of_context()

        mode = "query"

        from scripts.models.schemas import ClaimRecord
        from scripts.agents.auditor_agent import run as auditor_run
        from scripts.agents.clinician_agent import run as clinician_run
        from scripts.agents.social_navigator_agent import run as navigator_run
        from scripts.services.scoring_service import classify_recommendation

        for drug_name in drug_names[:10]:
            try:
                mapping = map_drug(drug_name, "", chat_history=chat_history)
                if mapping.equivalence_type == "NO_ALTERNATIVE":
                    results.append({
                        "drug_name": drug_name,
                        "no_alternative": True,
                        "message": mapping.mapping_reason,
                    })
                else:
                    # Use drug-name-seeded defaults so different drugs give different outputs.
                    # Keeps results deterministic per drug but varied across drugs.
                    rng = random.Random(abs(hash(drug_name.upper())) % 10_000)
                    claim = ClaimRecord(
                        claim_id="QUERY-0001",
                        member_id=member_context or "QUERY-MEMBER",
                        age_band=rng.choice(["35-44", "45-54", "55-64", "65-74"]),
                        sex=rng.choice(["M", "F"]),
                        zip3=rng.choice(["100", "200", "300", "400", "500"]),
                        plan_id="QUERY-PLAN",
                        drug_name=drug_name, brand_generic_flag="B", ndc="",
                        quantity=rng.choice([30.0, 60.0, 90.0]),
                        days_supply=rng.choice([30, 60, 90]),
                        fill_date="2025-01-01", paid_amount=0.0, member_cost_share=0.0,
                        pharmacy_id="PHX-0001", prescriber_id="NPI-0001",
                        diagnosis_group=rng.choice(["CARDIOVASCULAR", "DIABETES", "RESPIRATORY", "OTHER"]),
                        adherence_score=round(rng.uniform(0.65, 0.98), 2),
                        prior_switch_failure_flag=0,
                        estimated_event_cost=round(rng.uniform(300.0, 1500.0), 2),
                        preferred_pharmacy_available=rng.choice([0, 1, 1, 1]),
                        pharmacy_access_score=round(rng.uniform(0.55, 0.95), 2),
                    )
                    cost = auditor_run(claim, mapping)
                    clinical = clinician_run(claim, mapping, cost)
                    access = navigator_run(claim)
                    band = classify_recommendation(
                        clinical.risk_adjusted_savings,
                        clinical.clinical_risk_score,
                        access.pharmacy_access_score,
                    )
                    results.append({
                        "drug_name": drug_name,
                        "alternative": mapping.candidate_alternative,
                        "equivalence_type": mapping.equivalence_type,
                        "te_code": mapping.te_code,
                        "mapping_confidence": mapping.mapping_confidence,
                        "mapping_reason": mapping.mapping_reason,
                        "current_unit_cost": cost.current_unit_cost,
                        "alternative_unit_cost": cost.alternative_unit_cost,
                        "pricing_unit": cost.pricing_unit,
                        "gross_savings_per_30_day": cost.gross_savings,
                        "risk_adjusted_savings": clinical.risk_adjusted_savings,
                        "clinical_risk_score": clinical.clinical_risk_score,
                        "recommendation_band": band,
                        "reason_codes": mapping.reason_codes + cost.reason_codes,
                    })
            except Exception as exc:
                results.append({
                    "drug_name": drug_name,
                    "no_alternative": True,
                    "message": f"Analysis error for '{drug_name}': {exc}",
                })
    else:
        return _chat_error("Please upload a CSV file or enter drug names to query.")

    # ── Build chat response ────────────────────────────────────────────────
    valid = [r for r in results if not r.get("skipped") and not r.get("no_alternative")]
    no_alt = [r for r in results if r.get("no_alternative")]
    skipped = [r for r in results if r.get("skipped")]

    total_gross = sum(r.get("gross_savings", r.get("gross_savings_per_30_day", 0)) for r in valid)
    total_risk_adj = sum(r.get("risk_adjusted_savings", 0) for r in valid)
    band_counts: dict[str, int] = {}
    for r in valid:
        b = r.get("recommendation_band", "")
        band_counts[b] = band_counts.get(b, 0) + 1

    summary = _build_summary_text(mode, valid, no_alt, total_gross, total_risk_adj, band_counts)

    # ── Persist session history (last 5) ──────────────────────────────────
    if session_id:
        prev = _chat_sessions.get(session_id, [])
        prev.append({"role": "user", "content": drug_query or (file.filename if file else "csv")})
        prev.append({"role": "assistant", "content": summary})
        _chat_sessions[session_id] = prev[-5:]

    return {
        "mode": mode,
        "analyzed": len(valid),
        "no_alternative_count": len(no_alt),
        "skipped_count": len(skipped),
        "total_gross_savings": round(total_gross, 2),
        "total_risk_adjusted_savings": round(total_risk_adj, 2),
        "band_counts": band_counts,
        "results": results,
        "summary_text": summary,
    }


_QUESTION_PREFIXES = re.compile(
    r"^(can\s+i|should\s+i|could\s+i|is\s+it\s+ok\s+to|what\s+(is|are|about|can)|"
    r"how\s+(about|do\s+i)|tell\s+me\s+about|compare|check|look\s+up|find|"
    r"is\s+there\s+a|are\s+there|do\s+you\s+know|help\s+me\s+(with|find))\s+",
    re.I,
)
# Words/phrases that are never drug names — all lowercase for case-insensitive matching
_STOP_WORDS: set[str] = {
    # question words
    "what", "which", "who", "where", "when", "why", "how",
    # demonstratives / indefinite pronouns
    "that", "this", "these", "those", "something", "anything", "nothing",
    "some", "any", "all", "both", "each", "every", "other", "another",
    # modals / auxiliaries
    "can", "could", "should", "would", "will", "shall", "may", "might", "must",
    # verb forms
    "be", "been", "being", "is", "are", "was", "were",
    "have", "has", "had", "do", "does", "did",
    "get", "got", "use", "used", "using", "take", "taking",
    "replace", "replaced", "replacing", "switch", "switched", "switching",
    "give", "find", "want", "need", "know", "show", "help",
    # connectors / prepositions
    "instead", "with", "without", "of", "in", "at", "by", "about", "into", "than",
    "instead of", "switch to", "switch from", "replace with", "rather than",
    "compared to", "vs", "versus",
    # articles / pronouns
    "or", "and", "the", "a", "an", "my", "me", "i", "it", "its",
    "he", "she", "they", "we", "you", "his", "her", "their", "our",
    # adjectives that appear in drug queries
    "cheaper", "cheap", "less", "expensive", "affordable", "cost", "costly",
    "safe", "safer", "better", "good", "best", "similar", "same",
    "possible", "available", "ok", "okay", "effective",
    # misc
    "on", "for", "from", "to", "also", "just", "only", "not", "no",
    "please", "thanks", "thank", "yes", "yeah", "nope",
    # domain stop words
    "drug", "drugs", "medicine", "medicines", "medication", "medications",
    "pill", "pills", "tablet", "tablets", "capsule", "capsules",
    "generic", "brand", "alternative", "alternatives", "equivalent",
}
_DRUG_TOKEN = re.compile(r"\b([A-Za-z][A-Za-z0-9\-]{2,}(?:\s+\d+\s*(?:mg|mcg|ml|g|iu|units?|tabs?|caps?))?\b)")


def _is_plausible_drug_name(token: str) -> bool:
    """Return True if the token starts a known drug name in NADAC or Orange Book.

    Uses a prefix match (LIKE 'KEY%') so common English words that happen to
    appear as substrings inside drug descriptions (e.g. THAT, SOMETHING) are
    rejected unless they actually start a drug name.
    """
    from scripts.services.data_service import get_connection
    try:
        con = get_connection()
        key = token.strip().split()[0].upper()
        if len(key) < 4:  # single short words are almost never drug names
            return False
        # Prefix match: drug name must START with the token word
        row = con.execute(
            "SELECT 1 FROM nadac WHERE UPPER(ndc_description) LIKE ? LIMIT 1",
            [f"{key}%"]
        ).fetchone()
        if row:
            return True
        row = con.execute(
            "SELECT 1 FROM orange_book WHERE UPPER(trade_name) LIKE ? LIMIT 1",
            [f"{key}%"]
        ).fetchone()
        return row is not None
    except Exception:
        return True  # fail open — let map_drug() decide


def _extract_drug_names(text: str) -> list[str]:
    """
    Extract drug-like tokens from a natural-language question.

    Strategy:
    1. Strip leading question phrases.
    2. Remove connector phrases (switch to, replace with, etc.).
    3. If commas/semicolons exist, split on those directly.
    4. Otherwise use regex to extract word tokens.
    5. Drop stop words and validate each token against the drug database.
    """
    cleaned = _QUESTION_PREFIXES.sub("", text.strip())
    # Remove connector phrases (including inflected forms)
    cleaned = re.sub(
        r"\b(instead\s+of|switch(?:ed|ing)?\s+to|switch(?:ed|ing)?\s+from|"
        r"replace[sd]?\s+with|rather\s+than|compared\s+to|vs\.?|versus)\b",
        " ", cleaned, flags=re.I,
    )

    # Comma/semicolon-separated list: split directly
    if re.search(r"[,;]", cleaned):
        parts = re.split(r"[,;]+", cleaned)
        candidates = [p.strip() for p in parts if p.strip()]
    else:
        candidates = _DRUG_TOKEN.findall(cleaned)

    results: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        c = c.strip()
        if c.lower() in _STOP_WORDS:
            continue
        if len(c) < 3:
            continue
        key = c.upper()
        if key in seen:
            continue
        if not _is_plausible_drug_name(c):
            continue  # not found in NADAC or Orange Book — drop silently
        seen.add(key)
        results.append(c)

    return results


def _chat_error(msg: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": msg})


def _chat_out_of_context() -> JSONResponse:
    return JSONResponse(status_code=200, content={
        "mode": "out_of_context",
        "analyzed": 0,
        "no_alternative_count": 0,
        "skipped_count": 0,
        "total_gross_savings": 0,
        "total_risk_adjusted_savings": 0,
        "band_counts": {},
        "results": [],
        "summary_text": (
            "I'm specialized for pharmacy benefit analysis. "
            "Please enter a brand drug name (e.g. 'Provigil, Abilify') "
            "or upload a claims CSV to find generic alternatives and savings estimates."
        ),
    })


def _build_summary_text(mode, valid, no_alt, total_gross, total_risk_adj, band_counts) -> str:
    if not valid and not no_alt:
        return "No drugs could be analyzed. Please check your input format."

    parts = []
    if mode == "csv":
        parts.append(f"Analyzed {len(valid)} claim(s) from your uploaded file.")
    else:
        parts.append(f"Looked up {len(valid) + len(no_alt)} drug(s).")

    if valid:
        parts.append(
            f"Found generic alternatives for {len(valid)} drug(s) with "
            f"estimated gross savings of ${total_gross:,.0f} and "
            f"risk-adjusted savings of ${total_risk_adj:,.0f} per fill cycle."
        )
        rec = band_counts.get("Recommend", 0)
        rev = band_counts.get("Review", 0)
        dns = band_counts.get("Do Not Switch", 0)
        if rec:
            parts.append(f"{rec} opportunity/ies flagged as Recommend (low clinical and access risk).")
        if rev:
            parts.append(f"{rev} flagged as Review (clinical or access uncertainty — pharmacist review suggested).")
        if dns:
            parts.append(f"{dns} flagged as Do Not Switch (risk-adjusted savings negative or access barrier).")

    if no_alt:
        names = ", ".join(r["drug_name"] for r in no_alt[:5])
        parts.append(f"No generic alternative found in current data for: {names}.")

    parts.append(
        "All savings are gross NADAC-based estimates. "
        "This is not clinical advice — refer all switch decisions to a pharmacist or clinician."
    )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# API: CSV export
# ---------------------------------------------------------------------------

@app.get("/api/export/opportunities.csv")
async def export_opportunities_csv():
    """Download all recommendations as a CSV spreadsheet."""
    output = io.StringIO()
    fieldnames = [
        "recommendation_id", "member_id", "current_drug", "candidate_alternative",
        "equivalence_type", "te_code", "gross_savings", "risk_adjusted_savings",
        "clinical_risk_score", "access_risk_score", "recommendation_band",
        "switch_failure_probability", "credible_interval_low", "credible_interval_high",
        "reason_codes",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for r in _recommendations:
        d = r.model_dump()
        d["reason_codes"] = "|".join(d.get("reason_codes") or [])
        writer.writerow({k: d.get(k, "") for k in fieldnames})
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pharmaflow_opportunities.csv"},
    )


# ---------------------------------------------------------------------------
# API: document package download
# ---------------------------------------------------------------------------

@app.get("/api/documents/{recommendation_id}")
async def download_switch_package(recommendation_id: str):
    """
    Generate and download a 4-document switch package (zipped PDFs) for one recommendation.
    recommendation_id is the index (0-based) or the recommendation_id string.
    """
    rec = None
    # Try numeric index first, then string ID
    try:
        idx = int(recommendation_id)
        if 0 <= idx < len(_recommendations):
            rec = _recommendations[idx]
    except ValueError:
        for r in _recommendations:
            if r.recommendation_id == recommendation_id:
                rec = r
                break

    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")

    try:
        from scripts.services.document_service import generate_switch_package
        zip_bytes = generate_switch_package(rec)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Document generation failed: {exc}")

    safe_id = recommendation_id.replace("/", "_")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=switch_package_{safe_id}.zip"},
    )
