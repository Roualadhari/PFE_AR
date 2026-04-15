# =============================================================================
# sprint3/json_builder.py
# SE24D2 — Automated Invoice Intelligence System
# Sprint 3 — Step 6: Structured JSON Builder
# =============================================================================
#
# WHAT THIS FILE DOES:
#   This is the central assembly function of Sprint 3.
#   It takes outputs from ALL extractors and the scorer, and produces
#   one clean, standardised JSON that represents a fully processed invoice.
#
#   This JSON is the single source of truth that:
#     → Your Streamlit UI reads to display fields to the Accountant
#     → The DB injection (Sprint 4) reads to write to facture + lignefac
#     → The ERP validation compares against purchase orders
#
# CALL CHAIN (how this file fits in the pipeline):
#
#   Sprint 2 output (Header/Body/Footer dict)
#         ↓
#   invoice_type_detector.py   [binôme]  → invoice_type
#   regex_extractor.py         [binôme]  → regex_fields
#   spacy_extractor.py         [you]     → spacy_fields
#   layoutlm_extractor.py      [you]     → layoutlm_fields
#         ↓
#   confidence_scorer.py       [you]     → scored_fields + invoice_summary
#         ↓
#   json_builder.py            [you]     → FINAL INVOICE JSON  ← this file
#         ↓
#   Streamlit UI + DB injection + ERP validation
#
# OUTPUT SCHEMA:
#   {
#     "meta": { processing metadata },
#     "invoice_type": { value + confidence },
#     "header": { vendor, date, invoice_number, ... },
#     "body":   { line_items: [...] },
#     "footer": { totals, taxes },
#     "validation": { confidence summary, flags }
#   }
# =============================================================================

import json
import re
import uuid
from datetime import datetime
from typing import Optional

from matplotlib import image

# Sprint 3 imports — all modules we built
from sprint3.spacy_extractor     import extract_entities
from sprint3.layoutlm_extractor  import extract_with_layoutlm
from sprint3.confidence_scorer   import (
    score_all_fields,
    compute_invoice_confidence,
    score_field,
    REVIEW_THRESHOLD,
)
from sprint3.line_item_extractor import extract_line_items


# ---------------------------------------------------------------------------
# SECTION 1 — Invoice type detection
# This duplicates the logic your binôme wrote in invoice_type_detector.py
# as a fallback, so json_builder works standalone even before integration.
# In production, pass their result directly via the `invoice_type` parameter.
# ---------------------------------------------------------------------------

INVOICE_TYPE_PATTERNS = {
    "BON_COMMANDE": r"bon\s+de\s+commande|purchase\s+order|P\.?O\.?\s*n",
    "PROFORMA":     r"facture\s+pro.?forma|proforma",
    "AVOIR":        r"avoir|note\s+de\s+cr[eé]dit|credit\s+note",
    "FACTURE":      r"facture|invoice",
}

def _detect_type_fallback(header_text: str) -> dict:
    """Fallback type detection used when binôme's module is not yet integrated."""
    text = header_text.lower()
    for type_name, pattern in INVOICE_TYPE_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return {"value": type_name, "confidence": 95, "method": "REGEX"}
    return {"value": "UNKNOWN", "confidence": 0, "method": "REGEX"}


# ---------------------------------------------------------------------------
# SECTION 2 — Line item parser
# Parses the Body section to extract individual invoice lines.
# Each line maps directly to a lignefac row in your supervisor's DB schema.
# ---------------------------------------------------------------------------

# Pattern for a line item row:
# Captures: code, description, quantity, unit price
# Handles both comma and dot as decimal separator (Tunisian invoices use comma)
LINE_ITEM_PATTERN = re.compile(
    r"([A-Z]{2}\d{2,})\s+"          # Code like BA26, AG23
    r"(.+?)\s+"                      # Description (non-greedy)
    r"(\d+(?:[,\.]\d+)?)\s+"         # Quantity
    r"(\d+(?:[,\.]\d{1,6})?)\s*"     # Unit price (PrixVente)
    r"(\d+(?:[,\.]\d{1,6})?)?",      # Total line (optional)
    re.IGNORECASE
)

def _parse_line_items(body_text: str) -> list:
    """
    Extract line items from the Body section of the invoice.
    Returns a list of dicts matching the lignefac table columns.

    Each dict uses the exact column names from your supervisor's lignefac table
    so Sprint 4 DB injection requires zero transformation.
    """
    items = []

    for match in LINE_ITEM_PATTERN.finditer(body_text):
        code        = match.group(1).strip()
        description = match.group(2).strip()
        quantity    = _parse_number(match.group(3))
        prix_vente  = _parse_number(match.group(4))
        line_total  = _parse_number(match.group(5)) if match.group(5) else None

        # Skip obvious garbage matches
        if quantity == 0 and prix_vente == 0:
            continue

        item = {
            # lignefac column names — exact match to your supervisor's schema
            "Code":      code,
            "LibProd":   description,
            "Quantité":  quantity,
            "PrixVente": prix_vente,
            "TauxTVA":   0.0,       # filled later if found in footer
            "TauxFODEC": 0.0,       # filled later if found in footer
            "Remise":    0.0,       # discount — default 0
            # Computed fields
            "line_total":  line_total or round(quantity * prix_vente, 6),
            "confidence":  75,      # line items are harder to parse reliably
        }
        items.append(item)

    return items


def _parse_number(raw: Optional[str]) -> float:
    """
    Convert a raw number string to float.
    Handles both French format (1 200,50) and English format (1200.50).
    """
    if raw is None:
        return 0.0
    cleaned = raw.strip().replace(" ", "").replace(",", ".")
    try:
        return round(float(cleaned), 6)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# SECTION 3 — Field formatter
# Wraps a plain string value into the standard field dict format
# used throughout the JSON schema.
# ---------------------------------------------------------------------------

def _make_field(value, confidence: int, method: str) -> dict:
    """
    Create a standardised field dict.

    Every field in the output JSON has this exact shape:
      { "value": ..., "confidence": int, "method": str, "needs_review": bool }

    This consistency means Streamlit can render any field with the same
    component without special-casing individual fields.
    """
    return {
        "value":        value,
        "confidence":   confidence,
        "method":       method,
        "needs_review": confidence < REVIEW_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# SECTION 4 — Master builder
# ---------------------------------------------------------------------------

def build_invoice_json(
    parsed_sections:  dict,
    regex_fields:     dict,
    image=None,
    invoice_type:     Optional[dict] = None,
) -> dict:
    """
    Master function. Assembles the final structured invoice JSON.

    Args:
        parsed_sections : Sprint 2 output — {"header": str, "body": str, "footer": str}
        regex_fields    : binôme's regex_extractor output — {"invoice_number": str, ...}
        image           : PIL Image from Sprint 2 (optional, for LayoutLM).
                          Pass None to skip LayoutLM and use SpaCy + REGEX only.
        invoice_type    : binôme's type detection result — {"value": str, "confidence": int}
                          Pass None to use internal fallback detection.

    Returns:
        Complete invoice JSON dict (also printed + returned for Streamlit).
    """

    header_text = parsed_sections.get("header", "")
    body_text   = parsed_sections.get("body",   "")
    footer_text = parsed_sections.get("footer", "")

    # ------------------------------------------------------------------
    # Step A — Invoice type
    # ------------------------------------------------------------------
    if invoice_type is None:
        invoice_type = _detect_type_fallback(header_text)

    # ------------------------------------------------------------------
    # Step B — Run SpaCy extraction
    # ------------------------------------------------------------------
    spacy_fields = extract_entities(parsed_sections)

    # ------------------------------------------------------------------
    # Step C — Run LayoutLM extraction (optional, skipped if no image)
    # ------------------------------------------------------------------
    if image is not None:
        layoutlm_fields = extract_with_layoutlm(image)
    else:
        layoutlm_fields = {}

    # ------------------------------------------------------------------
    # Step D — Score and merge all fields
    # ------------------------------------------------------------------
    scored = score_all_fields(regex_fields, spacy_fields, layoutlm_fields)

    # ------------------------------------------------------------------
    # Step E — Parse line items from body
    # ------------------------------------------------------------------
   # Use bbox-based extractor if image available, fall back to REGEX parser
    if image is not None:
        line_items = extract_line_items(image, debug=False)
    else:
        line_items = _parse_line_items(body_text)

# Apply TVA and FODEC from footer to all line items

    # Apply TVA and FODEC rates from regex_fields to each line item
    tva_rate    = _parse_number(regex_fields.get("tva_rate",    "0"))
    fodec_rate  = _parse_number(regex_fields.get("fodec_rate",  "0"))
    for item in line_items:
        item["TauxTVA"]   = tva_rate
        item["TauxFODEC"] = fodec_rate

    # ------------------------------------------------------------------
    # Step F — Invoice-level confidence summary
    # ------------------------------------------------------------------
    summary = compute_invoice_confidence(scored)

    # ------------------------------------------------------------------
    # Step G — Assemble final JSON
    # ------------------------------------------------------------------
    invoice_json = {

        # --- Meta ---
        "meta": {
            "processing_id":  str(uuid.uuid4()),
            "processed_at":   datetime.now().isoformat(),
            "pipeline_version": "Sprint3-SE24D2",
            "has_layoutlm":   image is not None,
        },

        # --- Invoice type ---
        "invoice_type": {
            "value":      invoice_type.get("value", "UNKNOWN"),
            "confidence": invoice_type.get("confidence", 0),
            "method":     invoice_type.get("method", "REGEX"),
        },

        # --- Header section ---
        # These are the fields displayed at the top of the Streamlit review UI.
        "header": {
            "invoice_number": scored.get("invoice_number",
                _make_field(None, 0, "NONE")),

            "date": scored.get("date",
                _make_field(None, 0, "NONE")),

            "vendor_name": scored.get("vendor_name",
                _make_field(None, 0, "NONE")),

            "vendor_city": scored.get("vendor_city",
                _make_field(None, 0, "NONE")),

            "client_name": scored.get("client_name",
                _make_field(None, 0, "NONE")),
        },

        # --- Body section ---
        # Line items mapping directly to lignefac rows.
        "body": {
            "line_items": line_items,
            "line_count": len(line_items),
        },

        # --- Footer section ---
        # Financial totals — these must match the ERP cross-reference in Sprint 4.
        "footer": {
            "total_ht": scored.get("total_ht",
                _make_field(
                    _parse_number(regex_fields.get("total_ht")),
                    score_field("total_ht",
                                regex_fields.get("total_ht"),
                                "REGEX")["confidence"],
                    "REGEX"
                )
            ),

            "tva_rate": _make_field(
                tva_rate,
                score_field("tva_amount",
                            regex_fields.get("tva_rate"),
                            "REGEX")["confidence"],
                "REGEX"
            ),

            "tva_amount": scored.get("tva_amount",
                _make_field(None, 0, "NONE")),

            "fodec_rate": _make_field(
                fodec_rate,
                score_field("fodec_amount",
                            regex_fields.get("fodec_rate"),
                            "REGEX")["confidence"],
                "REGEX"
            ),

            "fodec_amount": scored.get("fodec_amount",
                _make_field(None, 0, "NONE")),

            "total_ttc": scored.get("total_ttc",
                _make_field(
                    _parse_number(regex_fields.get("total_ttc")),
                    score_field("total_ttc",
                                regex_fields.get("total_ttc"),
                                "REGEX")["confidence"],
                    "REGEX"
                )
            ),
        },

        # --- Validation block ---
        # Read by Streamlit to decide what to highlight and by Sprint 4 DB injection.
        "validation": {
            "confidence_avg":         summary["confidence_avg"],
            "confidence_min":         summary["confidence_min"],
            "low_confidence_fields":  summary["low_confidence_fields"],
            "needs_review":           summary["needs_review"],
            "status":                 "PENDING",   # PENDING → VALIDATED → REJECTED
            "validated_by":           None,         # filled when Accountant approves
            "validated_at":           None,
        },
    }

    return invoice_json


# ---------------------------------------------------------------------------
# SECTION 5 — Utilities for Streamlit and DB
# ---------------------------------------------------------------------------

def invoice_json_to_string(invoice_json: dict) -> str:
    """Pretty-print the invoice JSON. Used in the Streamlit debug panel."""
    return json.dumps(invoice_json, ensure_ascii=False, indent=2)


def get_fields_for_display(invoice_json: dict) -> list:
    """
    Flatten the invoice JSON into a list of display rows for the Streamlit UI.
    Each row is a dict the UI can render without knowing the JSON structure.

    Returns:
        [
          {"section": "header", "field": "vendor_name",
           "value": "Société X", "confidence": 88,
           "method": "MERGED", "needs_review": False},
          ...
        ]
    """
    rows = []

    for section_name in ("header", "footer"):
        section = invoice_json.get(section_name, {})
        for field_name, field_data in section.items():
            if not isinstance(field_data, dict):
                continue
            rows.append({
                "section":      section_name,
                "field":        field_name,
                "value":        field_data.get("value"),
                "confidence":   field_data.get("confidence", 0),
                "method":       field_data.get("method", ""),
                "needs_review": field_data.get("needs_review", True),
            })

    return rows


def apply_accountant_corrections(invoice_json: dict, corrections: dict) -> dict:
    """
    Apply manual corrections made by the Accountant in the Streamlit UI.

    Args:
        invoice_json : the original invoice JSON
        corrections  : {"vendor_name": "corrected value", ...}

    Returns:
        Updated invoice JSON with corrected values and confidence set to 100
        (human-verified = maximum confidence).
    """
    for field_name, new_value in corrections.items():
        for section_name in ("header", "footer"):
            section = invoice_json.get(section_name, {})
            if field_name in section:
                section[field_name]["value"]        = new_value
                section[field_name]["confidence"]   = 100
                section[field_name]["method"]       = "HUMAN"
                section[field_name]["needs_review"] = False

    # Recompute validation block after corrections
    all_fields = {}
    for section_name in ("header", "footer"):
        all_fields.update(invoice_json.get(section_name, {}))

    scores = {k: v for k, v in all_fields.items() if isinstance(v, dict)}
    conf_values = [v.get("confidence", 0) for v in scores.values()]

    if conf_values:
        invoice_json["validation"]["confidence_avg"] = round(
            sum(conf_values) / len(conf_values), 2
        )
        invoice_json["validation"]["confidence_min"] = min(conf_values)
        invoice_json["validation"]["low_confidence_fields"] = [
            k for k, v in scores.items()
            if v.get("needs_review", False)
        ]
        invoice_json["validation"]["needs_review"] = (
            len(invoice_json["validation"]["low_confidence_fields"]) > 0
        )

    return invoice_json


def mark_as_validated(invoice_json: dict, accountant_username: str) -> dict:
    """
    Mark an invoice as validated by the Accountant.
    Called when the Accountant clicks the 'Validate & Push to DB' button.
    """
    invoice_json["validation"]["status"]       = "VALIDATED"
    invoice_json["validation"]["validated_by"] = accountant_username
    invoice_json["validation"]["validated_at"] = datetime.now().isoformat()
    return invoice_json


# ---------------------------------------------------------------------------
# SECTION 6 — Standalone test
# Run: python sprint3/json_builder.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    print("=" * 60)
    print("SE24D2 — JSON Builder Test")
    print("=" * 60)

    # Simulate Sprint 2 parse_text_structure() output
    fake_parsed = {
        "header": (
            "FACTURE N° : FAC-2024/053\n"
            "Date : 12/05/2024\n"
            "Fournisseur : Société Générale de Fournitures SARL\n"
            "Adresse : 12 Rue de la République, Tunis 1001\n"
            "Client : Entreprise ABC"
        ),
        "body": (
            "BA26  Tissu coton blanc       100   1,050000   105,000000\n"
            "AG23  Agrafe métallique       650   1,090000   708,500000\n"
        ),
        "footer": (
            "Total HT  :  813,50\n"
            "TVA 19%   :  154,57\n"
            "FODEC     :    0,00\n"
            "Total TTC :  968,07"
        ),
    }

    # Simulate binôme's regex_extractor output
    fake_regex = {
        "invoice_number": "FAC-2024/053",
        "date":           "12/05/2024",
        "total_ht":       "813,50",
        "tva_rate":       "19",
        "tva_amount":     "154,57",
        "fodec_rate":     "0",
        "fodec_amount":   "0,00",
        "total_ttc":      "968,07",
    }

    # Simulate binôme's type detection output
    fake_type = {"value": "FACTURE", "confidence": 95, "method": "REGEX"}

    print("\n[1] Building invoice JSON (no image — LayoutLM skipped)...")
    result = build_invoice_json(
        parsed_sections=fake_parsed,
        regex_fields=fake_regex,
        image=None,            # no image in test → LayoutLM skipped
        invoice_type=fake_type,
    )

    print("\n[2] Full JSON output:")
    print(invoice_json_to_string(result))

    print("\n[3] Display rows for Streamlit UI:")
    rows = get_fields_for_display(result)
    print(f"  {'Section':<10} {'Field':<22} {'Conf':>5}  {'Method':<10}  {'Value'}")
    print("  " + "-" * 75)
    for row in rows:
        flag = "⚠️ " if row["needs_review"] else "✅"
        val  = str(row["value"])[:30] if row["value"] else "—"
        print(f"  {row['section']:<10} {row['field']:<22} "
              f"{row['confidence']:>4}%  {row['method']:<10}  {flag} {val}")

    print("\n[4] Simulating Accountant correction on vendor_city...")
    corrected = apply_accountant_corrections(result, {"vendor_city": "Sfax"})
    city = corrected["header"]["vendor_city"]
    print(f"  vendor_city → value: {city['value']}, "
          f"confidence: {city['confidence']}%, method: {city['method']}")

    print("\n[5] Marking invoice as validated...")
    validated = mark_as_validated(corrected, accountant_username="accountant1")
    v = validated["validation"]
    print(f"  status: {v['status']}")
    print(f"  validated_by: {v['validated_by']}")
    print(f"  validated_at: {v['validated_at']}")

    print("\n✅ json_builder.py is working correctly.")
    print("   Next: wire this into streamlit_ocr_app.py (Step 7).")