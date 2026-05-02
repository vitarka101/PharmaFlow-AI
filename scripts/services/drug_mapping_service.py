"""
Drug mapping service: finds generic alternatives for brand drugs using the
Orange Book + NADAC equivalence map (marts.switch_candidates).

Equivalence types:
  GENERIC_EQUIVALENT   — same ingredient, DF/route, strength, AB TE code
  THERAPEUTIC_ALT      — same ingredient, different form/strength
  NO_ALTERNATIVE       — no match found in switch_candidates

Search order (6 steps):
  1. Exact NDC match in switch_candidates
  2. Brand name LIKE '{first_word}%' in switch_candidates
  3. Ingredient key exact match in switch_candidates
  4. Substring match in Orange Book trade names → re-query switch_candidates
  5. Substring match in NADAC ndc_description directly
  6. LLM fallback (when USE_LLM=True and all DB steps fail)
"""

from __future__ import annotations

import json
import os
from scripts.models.schemas import DrugMapping
from scripts.services.data_service import get_connection


def map_drug(drug_name: str, ndc: str, chat_history: list | None = None) -> DrugMapping:
    """
    Find the lowest-cost generic alternative for a brand drug.
    chat_history: optional list of prior message dicts for LLM context.
    """
    con = get_connection()
    row = None
    try:
        # 1. Exact NDC lookup
        if ndc.strip():
            row = con.execute("""
                SELECT brand_name, brand_ndc, brand_unit_cost, pricing_unit,
                       generic_name, generic_ndc, generic_unit_cost,
                       te_code, dosage_form_route, strength, unit_cost_delta
                FROM marts.switch_candidates
                WHERE brand_ndc = ?
                LIMIT 1
            """, [ndc.strip()]).fetchone()

        # 2. Brand name LIKE match (handles "Provigil" → "PROVIGIL 200 MG TABLET")
        if row is None:
            brand_like = drug_name.strip().split()[0].upper() + "%"
            row = con.execute("""
                SELECT brand_name, brand_ndc, brand_unit_cost, pricing_unit,
                       generic_name, generic_ndc, generic_unit_cost,
                       te_code, dosage_form_route, strength, unit_cost_delta
                FROM marts.switch_candidates
                WHERE upper(brand_name) LIKE ?
                ORDER BY unit_cost_delta DESC
                LIMIT 1
            """, [brand_like]).fetchone()

        # 3. Ingredient key exact match (handles generic name input, e.g. "aripiprazole")
        if row is None:
            ingredient_key = drug_name.strip().split()[0].upper()
            row = con.execute("""
                SELECT brand_name, brand_ndc, brand_unit_cost, pricing_unit,
                       generic_name, generic_ndc, generic_unit_cost,
                       te_code, dosage_form_route, strength, unit_cost_delta
                FROM marts.switch_candidates
                WHERE upper(ingredient_key) = ?
                ORDER BY unit_cost_delta DESC
                LIMIT 1
            """, [ingredient_key]).fetchone()

        # 4. Substring match in Orange Book trade names → re-query switch_candidates
        # Handles partial names like "Dolo" → "DOLOBID", "tylenol" → "TYLENOL WITH CODEINE"
        if row is None:
            keyword = "%" + drug_name.strip().split()[0].upper() + "%"
            ob_match = con.execute("""
                SELECT trade_name
                FROM raw_fda.orange_book_products
                WHERE upper(trade_name) LIKE ?
                LIMIT 1
            """, [keyword]).fetchone()
            if ob_match:
                ob_trade = ob_match[0].strip().split()[0].upper() + "%"
                row = con.execute("""
                    SELECT brand_name, brand_ndc, brand_unit_cost, pricing_unit,
                           generic_name, generic_ndc, generic_unit_cost,
                           te_code, dosage_form_route, strength, unit_cost_delta
                    FROM marts.switch_candidates
                    WHERE upper(brand_name) LIKE ?
                    ORDER BY unit_cost_delta DESC
                    LIMIT 1
                """, [ob_trade]).fetchone()

        # 5. Substring match in NADAC ndc_description directly
        if row is None:
            nadac_like = "%" + drug_name.strip().split()[0].upper() + "%"
            nadac_hit = con.execute("""
                SELECT ndc_description
                FROM raw_nadac.nadac_prices
                WHERE upper(ndc_description) LIKE ?
                  AND classification IN ('G')
                LIMIT 1
            """, [nadac_like]).fetchone()
            if nadac_hit:
                first_word = nadac_hit[0].strip().split()[0].upper() + "%"
                row = con.execute("""
                    SELECT brand_name, brand_ndc, brand_unit_cost, pricing_unit,
                           generic_name, generic_ndc, generic_unit_cost,
                           te_code, dosage_form_route, strength, unit_cost_delta
                    FROM marts.switch_candidates
                    WHERE upper(generic_name) LIKE ?
                    ORDER BY unit_cost_delta DESC
                    LIMIT 1
                """, [first_word]).fetchone()

    finally:
        con.close()

    # 6. LLM fallback when all DB steps fail
    if row is None:
        use_llm = os.getenv("USE_LLM", "false").lower() in ("true", "1", "yes")
        if use_llm:
            return _llm_fallback(drug_name, chat_history or [])
        return DrugMapping(
            source_drug=drug_name,
            candidate_alternative="",
            generic_ndc="",
            equivalence_type="NO_ALTERNATIVE",
            te_code=None,
            mapping_confidence=0.0,
            mapping_reason="No generic alternative found in NADAC/Orange Book data.",
            reason_codes=["NO_ALTERNATIVE_FOUND"],
        )

    (brand_name, brand_ndc, brand_cost, pricing_unit,
     generic_name, generic_ndc, generic_cost,
     te_code, dosage_form_route, strength, delta) = row

    te = (te_code or "").strip().upper()
    if te.startswith("AB"):
        equiv_type = "GENERIC_EQUIVALENT"
        confidence = 0.95
        reason = (
            f"Orange Book AB-rated generic equivalent. "
            f"Same ingredient, dosage form/route ({dosage_form_route}), strength ({strength}). "
            f"NADAC unit cost delta: ${delta:.4f}/unit."
        )
        codes = ["LOWER_NADAC_COST", "GENERIC_EQUIVALENT"]
    elif te:
        equiv_type = "THERAPEUTIC_ALTERNATIVE"
        confidence = 0.75
        reason = (
            f"Orange Book TE code {te}. "
            f"Same ingredient; verify dosage form/route and strength before switch."
        )
        codes = ["LOWER_NADAC_COST", "THERAPEUTIC_ALTERNATIVE"]
    else:
        equiv_type = "THERAPEUTIC_ALTERNATIVE"
        confidence = 0.60
        reason = (
            "Matched on ingredient name; no TE code available. "
            "Clinical review required before switch."
        )
        codes = ["LOWER_NADAC_COST", "THERAPEUTIC_ALTERNATIVE", "LOW_MAPPING_CONFIDENCE"]

    return DrugMapping(
        source_drug=str(brand_name),
        candidate_alternative=str(generic_name),
        generic_ndc=str(generic_ndc),
        equivalence_type=equiv_type,
        te_code=te or None,
        dosage_form_route=str(dosage_form_route) if dosage_form_route else None,
        strength=str(strength) if strength else None,
        mapping_confidence=confidence,
        mapping_reason=reason,
        reason_codes=codes,
    )


def _llm_fallback(drug_name: str, history: list) -> DrugMapping:
    """
    Call the configured LLM via litellm to identify a generic alternative.
    Returns a DrugMapping with LOW_MAPPING_CONFIDENCE + LLM_ASSISTED_MATCH codes.
    On any failure, returns NO_ALTERNATIVE with a friendly message.
    """
    model = os.getenv("MODEL_NAME", "")
    if not model:
        return _no_alternative(drug_name, "LLM not configured (MODEL_NAME unset).")

    try:
        import litellm  # type: ignore
    except ImportError:
        return _no_alternative(drug_name, "litellm not installed — run: pip install litellm")

    system_prompt = (
        "You are a pharmacy benefit management assistant. "
        "When given a brand drug name, respond ONLY with a JSON object (no markdown) with these keys:\n"
        '  "generic_name": string — the generic drug name and typical strength/form\n'
        '  "active_ingredient": string — the active ingredient\n'
        '  "equivalence_type": "GENERIC_EQUIVALENT" or "THERAPEUTIC_ALTERNATIVE"\n'
        '  "te_code": string or null — FDA Orange Book TE code if known (e.g. "AB")\n'
        '  "confidence": float 0.0–1.0\n'
        '  "reason": string — one sentence explanation\n'
        "If no generic exists, set generic_name to empty string and confidence to 0.0."
    )
    user_msg = f"Find a generic alternative for: {drug_name}"

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    # Include trimmed conversation history for context
    for h in history[-5:]:
        if isinstance(h, dict) and "role" in h and "content" in h:
            messages.append({"role": h["role"], "content": str(h["content"])})
    messages.append({"role": "user", "content": user_msg})

    for attempt in range(2):
        try:
            resp = litellm.completion(model=model, messages=messages, max_tokens=300)
            raw = resp.choices[0].message.content or ""
            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw.strip())

            generic_name = str(data.get("generic_name", "")).strip()
            if not generic_name:
                return _no_alternative(drug_name, "LLM found no known generic alternative.")

            te = str(data.get("te_code") or "").strip().upper()
            confidence = float(data.get("confidence", 0.50))
            equiv_type = str(data.get("equivalence_type", "THERAPEUTIC_ALTERNATIVE"))
            reason = str(data.get("reason", "LLM-assisted generic identification."))

            return DrugMapping(
                source_drug=drug_name,
                candidate_alternative=generic_name,
                generic_ndc="",
                equivalence_type=equiv_type,
                te_code=te or None,
                dosage_form_route=None,
                strength=None,
                mapping_confidence=min(confidence, 0.65),
                mapping_reason=(
                    f"[LLM-assisted] {reason} "
                    "Note: pricing data unavailable — savings estimate uses NADAC averages. "
                    "Verify with pharmacist before switch."
                ),
                reason_codes=["LLM_ASSISTED_MATCH", "LOW_MAPPING_CONFIDENCE"],
            )

        except (json.JSONDecodeError, KeyError, ValueError):
            if attempt == 0:
                # Retry once with explicit JSON reminder
                messages.append({
                    "role": "user",
                    "content": "Your response was not valid JSON. Please respond ONLY with the JSON object, no other text."
                })
            else:
                return _no_alternative(drug_name, "LLM returned an unparseable response.")
        except Exception as exc:
            return _no_alternative(drug_name, f"LLM lookup unavailable: {exc}")

    return _no_alternative(drug_name, "LLM lookup failed after retries.")


def _no_alternative(drug_name: str, reason: str) -> DrugMapping:
    return DrugMapping(
        source_drug=drug_name,
        candidate_alternative="",
        generic_ndc="",
        equivalence_type="NO_ALTERNATIVE",
        te_code=None,
        mapping_confidence=0.0,
        mapping_reason=reason,
        reason_codes=["NO_ALTERNATIVE_FOUND"],
    )
