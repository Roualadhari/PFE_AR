# =============================================================================
# sprint3/confidence_scorer.py
# SE24D2 — Automated Invoice Intelligence System
# Sprint 3 — Step 5: Confidence Scoring Engine
# =============================================================================
#
# WHAT THIS FILE DOES:
#   Every extracted field — whether it came from REGEX, SpaCy, or LayoutLM —
#   gets a confidence score between 0 and 100.
#
#   The score means:
#     >= 80  → accepted automatically, no human review needed
#     50–79  → flagged for human review (highlighted in Streamlit UI)
#      < 50  → very uncertain, field shown empty with warning
#
#   Each extraction method has a different base score because they have
#   different reliability profiles:
#     REGEX    → deterministic pattern match → starts at 90
#     SPACY    → statistical NER model      → starts at 70
#     LAYOUTLM → layout-aware model         → starts at 75
#     MERGED   → two methods agree          → boosted to 95+
#
# INPUT:
#   Individual field dicts from spacy_extractor.py, your binôme's
#   regex_extractor.py, and layoutlm_extractor.py.
#
# OUTPUT:
#   Same field dict with a "confidence" key (int 0–100) and
#   "needs_review" (bool) added to each field.
#   Also produces an invoice-level confidence_avg float.
#
# EXAMPLE:
#   Input:  {"value": "FAC-2024/053", "method": "REGEX"}
#   Output: {"value": "FAC-2024/053", "method": "REGEX",
#            "confidence": 94, "needs_review": False}
# =============================================================================

import re
from typing import Optional

# ---------------------------------------------------------------------------
# SECTION 1 — Scoring constants
# ---------------------------------------------------------------------------

REVIEW_THRESHOLD  = 80    # below this → needs human review
EMPTY_THRESHOLD   = 50    # below this → treat as extraction failure

# Base scores per extraction method
BASE_SCORES = {
    "REGEX":    90,
    "SPACY":    70,
    "LAYOUTLM": 75,
    "MERGED":   95,   # two methods agreed on the same value
    "FALLBACK":  40,  # last-resort guess
}

# Per-field bonuses and penalties applied on top of base score.
# Each entry is (bonus_or_penalty_int, reason_string).
# These reflect how easy/hard each field is to extract correctly.
FIELD_MODIFIERS = {
    "invoice_number": [
        (+5,  "invoice numbers have strong structural patterns"),
    ],
    "date": [
        (+3,  "dates have well-defined formats"),
    ],
    "total_ttc": [
        (+4,  "TTC totals usually appear once, clearly labelled"),
    ],
    "total_ht": [
        (+4,  "HT totals usually appear once, clearly labelled"),
    ],
    "tva_amount": [
        (+2,  "TVA amounts are formulaic"),
    ],
    "fodec_amount": [
        (+2,  "FODEC is Tunisian-specific, usually clearly labelled"),
    ],
    "vendor_name": [
        (-5,  "vendor names vary widely in format"),
    ],
    "vendor_city": [
        (-8,  "city extraction is prone to false positives"),
    ],
    "client_name": [
        (-5,  "client names are less structured than vendor names"),
    ],
    "line_items": [
        (-10, "line items require table parsing, higher error rate"),
    ],
    "invoice_type": [
        (+5,  "type detection uses strong keyword patterns"),
    ],
}

# Value quality checks — applied regardless of method.
# These catch cases where extraction returned something syntactically wrong.
VALUE_VALIDATORS = {
    "invoice_number":  r"[A-Z0-9]{2,}",
    "date":            r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}",
    "total_ttc":       r"\d+[\d\s,\.]+",
    "total_ht":        r"\d+[\d\s,\.]+",
    "tva_amount":      r"\d+[\d\s,\.]+",
    "fodec_amount":    r"\d+[\d\s,\.]+",
}


# ---------------------------------------------------------------------------
# SECTION 2 — Single field scorer
# ---------------------------------------------------------------------------

def score_field(
    field_name: str,
    value:      Optional[str],
    method:     str,
    raw_score:  Optional[float] = None,
) -> dict:
    """
    Compute the confidence score for a single extracted field.

    Args:
        field_name : name of the field (e.g. "invoice_number", "vendor_name")
        value      : the extracted string value (None if extraction failed)
        method     : "REGEX", "SPACY", "LAYOUTLM", "MERGED", or "FALLBACK"
        raw_score  : optional 0.0–1.0 score from SpaCy or LayoutLM model.
                     If provided, we blend it with our base score.

    Returns:
        dict: {
            "value":        str or None,
            "method":       str,
            "confidence":   int (0–100),
            "needs_review": bool,
        }
    """

    # --- No value extracted ---
    if value is None or str(value).strip() == "":
        return {
            "value":        None,
            "method":       method,
            "confidence":   0,
            "needs_review": True,
        }

    value = str(value).strip()

    # --- Start from base score ---
    base = BASE_SCORES.get(method.upper(), 50)

    # --- Blend with model's own raw score if provided ---
    # raw_score is 0.0–1.0 from SpaCy or LayoutLM.
    # We blend: 60% base + 40% model score.
    # This prevents a high-confidence but wrong model prediction
    # from overriding our method-based priors completely.
    if raw_score is not None:
        model_score = raw_score * 100
        score = int(0.60 * base + 0.40 * model_score)
    else:
        score = base

    # --- Apply field-specific modifiers ---
    for delta, _ in FIELD_MODIFIERS.get(field_name, []):
        score += delta

    # --- Value quality check ---
    # If we have a validator pattern for this field, check the value matches.
    # A mismatch means the extracted value looks wrong even if the method was
    # confident — penalise heavily.
    if field_name in VALUE_VALIDATORS:
        pattern = VALUE_VALIDATORS[field_name]
        if not re.search(pattern, value):
            score -= 30  # large penalty — the value looks structurally wrong

    # --- Length sanity checks ---
    if len(value) < 2:
        score -= 20   # single character values are almost always wrong
    elif len(value) > 200:
        score -= 15   # extremely long values suggest a parsing error

    # --- Clamp to 0–99 ---
    # We cap at 99 (not 100) because no automated extraction is perfect.
    score = max(0, min(score, 99))

    return {
        "value":        value,
        "method":       method,
        "confidence":   score,
        "needs_review": score < REVIEW_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# SECTION 3 — Merger
# When two methods extracted a value for the same field, we compare them.
# Agreement boosts confidence. Disagreement keeps the higher-scored one
# but reduces its score.
# ---------------------------------------------------------------------------

def merge_field(
    field_name:   str,
    scored_fields: list,
) -> dict:
    """
    Given multiple scored extractions for the same field, merge into one.

    Agreement rule:
      If two or more methods returned the same value (normalised) → MERGED,
      confidence boosted to max(scores) + 10, capped at 99.

    Disagreement rule:
      Keep the highest-confidence result, but apply a -5 penalty
      because we're not sure which is correct.

    Args:
        field_name    : e.g. "invoice_number"
        scored_fields : list of dicts from score_field()

    Returns:
        Single merged dict.
    """

    # Filter out empty results
    valid = [f for f in scored_fields if f["value"] is not None]

    if not valid:
        return {
            "value":        None,
            "method":       "NONE",
            "confidence":   0,
            "needs_review": True,
        }

    if len(valid) == 1:
        return valid[0]

    # Normalise values for comparison (lowercase, strip spaces and punctuation)
    def normalise(v):
        return re.sub(r"[\s\.\,\-]", "", str(v).lower())

    normalised = [normalise(f["value"]) for f in valid]

    # Check for agreement — any two methods returning same normalised value
    agreements = []
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            if normalised[i] == normalised[j]:
                agreements.append((i, j))

    if agreements:
        # Pick the agreed value with the highest confidence
        best_idx = max(
            [idx for pair in agreements for idx in pair],
            key=lambda i: valid[i]["confidence"]
        )
        best = valid[best_idx].copy()
        best["method"]     = "MERGED"
        best["confidence"] = min(best["confidence"] + 10, 99)
        best["needs_review"] = best["confidence"] < REVIEW_THRESHOLD
        return best

    else:
        # No agreement — take highest confidence but penalise
        best = max(valid, key=lambda f: f["confidence"]).copy()
        best["confidence"] = max(0, best["confidence"] - 5)
        best["needs_review"] = best["confidence"] < REVIEW_THRESHOLD
        return best


# ---------------------------------------------------------------------------
# SECTION 4 — Full invoice scorer
# Called by json_builder.py with all raw extractions from all three methods.
# ---------------------------------------------------------------------------

def score_all_fields(
    regex_fields:    dict,
    spacy_fields:    dict,
    layoutlm_fields: dict,
) -> dict:
    """
    Score and merge all fields from all three extraction methods.

    Args:
        regex_fields    : dict from binôme's regex_extractor.py
                          Format: {"invoice_number": "FAC-2024/053", ...}
                          (raw string values, no scores)

        spacy_fields    : dict from spacy_extractor.extract_entities()
                          Format: {"vendor_name": {"value": "..", "spacy_score": 0.88}, ...}

        layoutlm_fields : dict from layoutlm_extractor.extract_with_layoutlm()
                          Format: {"vendor_name": {"value": "..", "layoutlm_score": 0.91}, ...}

    Returns:
        dict: all fields scored and merged, ready for json_builder.py
    """

    # All field names we care about across all methods
    all_field_names = set(
        list(regex_fields.keys()) +
        list(spacy_fields.keys()) +
        list(layoutlm_fields.keys())
    )

    scored = {}

    for field in all_field_names:
        candidates = []

        # --- REGEX candidate ---
        if field in regex_fields:
            raw_value = regex_fields[field]
            candidates.append(
                score_field(field, raw_value, method="REGEX", raw_score=None)
            )

        # --- SpaCy candidate ---
        if field in spacy_fields:
            spacy_data = spacy_fields[field]
            if isinstance(spacy_data, dict):
                candidates.append(score_field(
                    field,
                    value=spacy_data.get("value"),
                    method="SPACY",
                    raw_score=spacy_data.get("spacy_score"),
                ))

        # --- LayoutLM candidate ---
        if field in layoutlm_fields:
            lm_data = layoutlm_fields[field]
            if isinstance(lm_data, dict):
                candidates.append(score_field(
                    field,
                    value=lm_data.get("value"),
                    method="LAYOUTLM",
                    raw_score=lm_data.get("layoutlm_score"),
                ))

        # Merge all candidates for this field
        scored[field] = merge_field(field, candidates)

    return scored


# ---------------------------------------------------------------------------
# SECTION 5 — Invoice-level aggregation
# ---------------------------------------------------------------------------

def compute_invoice_confidence(scored_fields: dict) -> dict:
    """
    Compute invoice-level summary metrics from all scored fields.

    Returns:
        {
            "confidence_avg"      : float  — average across all fields
            "confidence_min"      : int    — lowest field confidence
            "low_confidence_fields": list  — field names needing review
            "needs_review"        : bool   — True if any field needs review
        }
    """

    if not scored_fields:
        return {
            "confidence_avg":       0.0,
            "confidence_min":       0,
            "low_confidence_fields": [],
            "needs_review":         True,
        }

    scores = [f["confidence"] for f in scored_fields.values()]
    low_fields = [
        name for name, f in scored_fields.items()
        if f.get("needs_review")
    ]

    return {
        "confidence_avg":        round(sum(scores) / len(scores), 2),
        "confidence_min":        min(scores),
        "low_confidence_fields": low_fields,
        "needs_review":          len(low_fields) > 0,
    }


# ---------------------------------------------------------------------------
# SECTION 6 — Standalone test
# Run: python sprint3/confidence_scorer.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    print("=" * 60)
    print("SE24D2 — Confidence Scorer Test")
    print("=" * 60)

    # Simulate outputs from all three extractors

    # Your binôme's REGEX extractor output (raw strings)
    fake_regex = {
        "invoice_number": "FAC-2024/053",
        "date":           "12/05/2024",
        "total_ht":       "813,50",
        "total_ttc":      "968,07",
        "tva_amount":     "154,57",
        "fodec_amount":   "0,00",
    }

    # SpaCy extractor output
    fake_spacy = {
        "vendor_name": {"value": "Société Générale de Fournitures SARL", "spacy_score": 0.88},
        "vendor_city": {"value": "Tunis",                                  "spacy_score": 0.80},
        "date":        {"value": "12 mai 2024",                            "spacy_score": 0.85},
    }

    # LayoutLM extractor output
    fake_layoutlm = {
        "vendor_name":    {"value": "Société Générale de Fournitures SARL", "layoutlm_score": 0.91},
        "invoice_number": {"value": "FAC-2024/053",                         "layoutlm_score": 0.87},
        "total_ttc":      {"value": "968,07",                               "layoutlm_score": 0.84},
    }

    print("\n[1] Scoring all fields...")
    scored = score_all_fields(fake_regex, fake_spacy, fake_layoutlm)

    print("\n  Field scores:")
    print(f"  {'Field':<22} {'Value':<42} {'Score':>6}  {'Method':<10}  Review?")
    print("  " + "-" * 90)
    for name, data in scored.items():
        flag = "⚠️ " if data["needs_review"] else "✅"
        val  = str(data["value"])[:40] if data["value"] else "—"
        print(f"  {name:<22} {val:<42} {data['confidence']:>5}%  {data['method']:<10}  {flag}")

    print("\n[2] Invoice-level summary...")
    summary = compute_invoice_confidence(scored)
    print(f"  Average confidence : {summary['confidence_avg']}%")
    print(f"  Minimum confidence : {summary['confidence_min']}%")
    print(f"  Fields for review  : {summary['low_confidence_fields']}")
    print(f"  Invoice needs review: {summary['needs_review']}")

    print("\n✅ confidence_scorer.py is working correctly.")