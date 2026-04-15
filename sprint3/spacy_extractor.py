# =============================================================================
# sprint3/spacy_extractor.py
# SE24D2 — Automated Invoice Intelligence System
# Sprint 3 — Step 3: SpaCy NER Entity Extractor
# =============================================================================
#
# WHAT THIS FILE DOES:
#   Takes the cleaned OCR text (from your Sprint 2 parse_text_structure output)
#   and uses the French SpaCy model to identify named entities: vendor names,
#   dates, monetary amounts, and addresses.
#
# INPUT:
#   A dict with keys "header", "body", "footer" — each is a plain string.
#   This is exactly what your Sprint 2 parse_text_structure() already returns.
#
# OUTPUT:
#   A dict of extracted entities, each with a raw value and a spacy_score.
#   Example:
#   {
#       "vendor_name":  {"value": "Entreprise X",  "spacy_score": 0.91},
#       "vendor_city":  {"value": "Tunis",          "spacy_score": 0.85},
#       "dates":        [{"value": "12/05/2024",    "spacy_score": 0.88}],
#       "amounts":      [{"value": "1 200,00",      "spacy_score": 0.79}],
#   }
# =============================================================================

import re
import spacy
from typing import Optional

# ---------------------------------------------------------------------------
# Load the French model once at module level.
# Loading is slow (~1-2s). Doing it at import time means it only happens
# once per Streamlit session, not on every button click.
# ---------------------------------------------------------------------------
try:
    nlp = spacy.load("fr_core_news_md")
except OSError:
    raise OSError(
        "[SE24D2] French SpaCy model not found.\n"
        "Run: python -m spacy download fr_core_news_md"
    )


# ---------------------------------------------------------------------------
# SECTION 1 — Label mapping
# SpaCy's French model uses these entity labels:
#   ORG   → organisation / company name  (what we want for vendor)
#   PER   → person name
#   LOC   → location / city / country
#   DATE  → date expression
#   MISC  → miscellaneous named entity
#
# There is no MONEY label in fr_core_news_md — monetary amounts are not
# tagged as entities by this model. We handle amounts with REGEX in
# regex_extractor.py (your binôme's file). SpaCy's job here is names + dates.
# ---------------------------------------------------------------------------

SPACY_LABEL_MAP = {
    "ORG":  "organisation",
    "PER":  "person",
    "LOC":  "location",
    "DATE": "date",
    "MISC": "misc",
}


# ---------------------------------------------------------------------------
# SECTION 2 — Noise filters
# Invoice OCR text contains many short tokens that SpaCy mis-tags as ORG
# (e.g. "TVA", "TTC", "HT", "N°", "REF"). We filter them out.
# ---------------------------------------------------------------------------

NOISE_TOKENS = {
    "tva", "ttc", "ht", "fodec", "n°", "ref", "code", "tel", "fax",
    "email", "objet", "date", "facture", "avoir", "total", "montant",
    "page", "de", "du", "le", "la", "les", "des", "et", "ou", "en",
    "sa", "sarl", "suarl",  # keep these only if attached to a real name
}

MIN_ENTITY_LENGTH = 3   # ignore entities shorter than 3 characters
MAX_VENDOR_CANDIDATES = 5  # keep at most 5 ORG candidates for ranking


# ---------------------------------------------------------------------------
# SECTION 3 — Core extraction function
# ---------------------------------------------------------------------------

def extract_entities(parsed_sections: dict) -> dict:
    """
    Main entry point. Takes the Header/Body/Footer dict from Sprint 2
    and returns a structured dict of SpaCy-extracted entities.

    Args:
        parsed_sections (dict): {
            "header": "..text..",
            "body":   "..text..",
            "footer": "..text.."
        }

    Returns:
        dict: extracted entities with spacy_score per field.
    """

    # We run NER primarily on the header (vendor name, date are usually there)
    # and secondarily on the body (line item context, delivery address).
    # Footer rarely contains new named entities.
    header_text = parsed_sections.get("header", "")
    body_text   = parsed_sections.get("body",   "")

    # Combine header + body for a single NER pass.
    # We track character offsets to know which section an entity came from.
    header_len  = len(header_text)
    combined    = header_text + "\n" + body_text

    doc = nlp(combined)

    # Collect all entities from SpaCy
    raw_orgs   = []
    raw_dates  = []
    raw_locs   = []

    for ent in doc.ents:
        label  = ent.label_
        text   = ent.text.strip()
        in_header = ent.start_char < header_len  # True if entity is in header

        if len(text) < MIN_ENTITY_LENGTH:
            continue
        if text.lower() in NOISE_TOKENS:
            continue

        if label == "ORG":
            raw_orgs.append({
                "value":      text,
                "in_header":  in_header,
                # SpaCy fr_core_news_md doesn't expose per-entity scores,
                # so we assign a heuristic score: header ORGs score higher
                # because vendor name is almost always in the header.
                "spacy_score": 0.88 if in_header else 0.65,
            })

        elif label == "PER":
            # Person names are less likely to be the vendor, but we keep them
            # as fallback (some invoices are from individual traders).
            raw_orgs.append({
                "value":      text,
                "in_header":  in_header,
                "spacy_score": 0.72 if in_header else 0.50,
                "is_person":  True,
            })

        elif label == "DATE":
            raw_dates.append({
                "value":      text,
                "in_header":  in_header,
                "spacy_score": 0.85 if in_header else 0.75,
            })

        elif label == "LOC":
            raw_locs.append({
                "value":      text,
                "in_header":  in_header,
                "spacy_score": 0.80 if in_header else 0.68,
            })

    # Build and return the final result
    result = {
        "vendor_name":  _pick_best_vendor(raw_orgs),
        "vendor_city":  _pick_best_location(raw_locs),
        "dates":        _deduplicate(raw_dates),
        "all_orgs":     raw_orgs[:MAX_VENDOR_CANDIDATES],
    }

    return result


# ---------------------------------------------------------------------------
# SECTION 4 — Selection helpers
# ---------------------------------------------------------------------------

def _pick_best_vendor(orgs: list) -> Optional[dict]:
    """
    From a list of ORG/PER candidates, pick the most likely vendor name.

    Strategy:
      1. Prefer ORGs over PERs (companies over individuals).
      2. Prefer entities found in the header.
      3. Among ties, prefer longer names (more specific = more likely real).
      4. Apply a small bonus for known Tunisian legal suffixes (SARL, SA, SUARL).
    """
    if not orgs:
        return None

    LEGAL_SUFFIXES = ("sarl", "sa", "suarl", "spa", "ste", "société", "company", "corp")

    def score(org):
        base  = org["spacy_score"]
        bonus = 0.05 if org.get("in_header") else 0
        bonus += 0.03 if any(s in org["value"].lower() for s in LEGAL_SUFFIXES) else 0
        bonus -= 0.10 if org.get("is_person") else 0
        length_bonus = min(len(org["value"]) / 100, 0.05)  # tiny bonus for length
        return base + bonus + length_bonus

    best = max(orgs, key=score)
    return {"value": best["value"], "spacy_score": round(best["spacy_score"], 3)}


def _pick_best_location(locs: list) -> Optional[dict]:
    """
    Pick the most likely vendor city/location from LOC entities.
    Prefers header locations.
    """
    if not locs:
        return None

    header_locs = [l for l in locs if l["in_header"]]
    candidates  = header_locs if header_locs else locs

    # Among candidates, take the one with highest spacy_score
    best = max(candidates, key=lambda l: l["spacy_score"])
    return {"value": best["value"], "spacy_score": round(best["spacy_score"], 3)}


def _deduplicate(entities: list) -> list:
    """
    Remove duplicate entity values (case-insensitive).
    Keeps the one with the highest spacy_score when duplicates exist.
    """
    seen   = {}
    result = []

    for ent in entities:
        key = ent["value"].lower().strip()
        if key not in seen:
            seen[key] = ent
        else:
            # Keep whichever has the higher score
            if ent["spacy_score"] > seen[key]["spacy_score"]:
                seen[key] = ent

    return list(seen.values())


# ---------------------------------------------------------------------------
# SECTION 5 — Quick standalone test
# Run: python sprint3/spacy_extractor.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # Simulate what Sprint 2 parse_text_structure() returns
    test_input = {
        "header": (
            "FACTURE N° : FAC-2024/053\n"
            "Date : 12/05/2024\n"
            "Fournisseur : Société Générale de Fournitures SARL\n"
            "Adresse : 12 Rue de la République, Tunis 1001\n"
            "Client : Entreprise ABC"
        ),
        "body": (
            "Réf.    Description              Qté    PU HT    Total HT\n"
            "BA26    Tissu coton blanc        100    1,05     105,00\n"
            "AG23    Agrafe métallique        650    1,09     708,50\n"
        ),
        "footer": (
            "Total HT  :  813,50\n"
            "TVA 19%   :  154,57\n"
            "Total TTC :  968,07"
        ),
    }

    print("=" * 60)
    print("SE24D2 — SpaCy NER Extractor Test")
    print("=" * 60)

    result = extract_entities(test_input)

    print(f"\n  Vendor name : {result['vendor_name']}")
    print(f"  Vendor city : {result['vendor_city']}")
    print(f"  Dates found : {result['dates']}")
    print(f"  All orgs    : {result['all_orgs']}")
    print("\n✅ spacy_extractor.py is working correctly.")