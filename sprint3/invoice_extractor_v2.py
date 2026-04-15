# =============================================================================
# sprint3/invoice_extractor_v2.py — SE24D2
# UNIVERSAL SPATIAL EXTRACTION ENGINE
# Works on any invoice layout — no hardcoded column positions.
#
# Three engines:
#   1. MF (Matricule Fiscale)  — top-left rule in header region
#   2. Document Number         — spatial search around trigger keywords
#   3. Dynamic Table           — vertical lane mapping from detected header
#
# Usage from streamlit_ocr_app.py:
#   from sprint3.invoice_extractor_v2 import build_lignefac_json
#   result = build_lignefac_json(pil_image, ocr_full_text, taux_tva=19.0)
#
# Usage standalone:
#   python sprint3/invoice_extractor_v2.py path/to/invoice.png
#   python sprint3/invoice_extractor_v2.py path/to/invoice.pdf
# =============================================================================

import re
import sys
import json
import pytesseract
import numpy as np
from PIL import Image
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 0 — CORE SPATIAL PRIMITIVES
# Everything else is built on top of these two functions.
# ─────────────────────────────────────────────────────────────────────────────

def get_words(pil_image: Image.Image, min_conf: int = 15) -> list[dict]:
    """
    Run Tesseract image_to_data on a PIL image.
    Returns one dict per word containing text + pixel bounding box.

    Fields returned:
        text, left, top, right, bottom, cx (x-center), cy (y-center), conf
    """
    data = pytesseract.image_to_data(
        pil_image,
        lang="fra+eng",
        config="--psm 6 --oem 1",
        output_type=pytesseract.Output.DICT,
    )
    words = []
    for i in range(len(data["text"])):
        text = str(data["text"][i]).strip()
        conf = int(data["conf"][i])
        if not text or conf < min_conf:
            continue
        l = int(data["left"][i])
        t = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        words.append({
            "text":   text,
            "left":   l,
            "top":    t,
            "right":  l + w,
            "bottom": t + h,
            "cx":     l + w // 2,
            "cy":     t + h // 2,
            "conf":   conf,
        })
    return words


def group_into_rows(words: list[dict], y_tol: int = 12) -> list[list[dict]]:
    """
    Group words that share the same horizontal band into rows.
    y_tol: maximum pixel gap between word tops to be in the same row.
    Each row is sorted left → right by word.left.
    """
    if not words:
        return []
    sw  = sorted(words, key=lambda w: w["top"])
    rows = []
    cur  = [sw[0]]
    for w in sw[1:]:
        avg_top = sum(x["top"] for x in cur) / len(cur)
        if abs(w["top"] - avg_top) <= y_tol:
            cur.append(w)
        else:
            rows.append(sorted(cur, key=lambda x: x["left"]))
            cur = [w]
    if cur:
        rows.append(sorted(cur, key=lambda x: x["left"]))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — MATRICULE FISCALE ENGINE
#
# Rule: scan top 25% of page only (supplier letterhead lives here).
# Find all strings matching the Tunisian MF pattern.
# If multiple found, pick the one closest to the top-left corner:
#   score = word.top + word.left  →  smallest score wins.
# ─────────────────────────────────────────────────────────────────────────────

# Tunisian MF: 7-8 digits / letter / letter / letter / 3 digits
# Handles spaces or slashes between components
_MF_PATTERN = re.compile(
    r'\b(\d{7,8})\s*[/\\\|\s]?\s*([A-Z])\s*[/\\\|\s]?\s*([A-Z])\s*[/\\\|\s]?\s*([A-Z])\s*[/\\\|\s]?\s*(\d{3})\b',
    re.IGNORECASE,
)

def _format_mf(m: re.Match) -> str:
    return f"{m.group(1)}{m.group(2).upper()}/{m.group(3).upper()}/{m.group(4).upper()}/{m.group(5)}"


def extract_mf(pil_image: Image.Image) -> Optional[str]:
    """
    ENGINE 1: Extract supplier Matricule Fiscale.

    Scans the top 25% of the image.
    If multiple MF patterns found, returns the one whose first digit
    group appears at the smallest (top + left) pixel sum.
    Falls back to top 50% if nothing found in top 25%.
    """
    img_w, img_h = pil_image.size

    for fraction in [0.25, 0.50, 1.0]:
        crop  = pil_image.crop((0, 0, img_w, int(img_h * fraction)))
        words = get_words(crop, min_conf=15)
        rows  = group_into_rows(words, y_tol=10)

        # Reconstruct text preserving spatial order
        text = "\n".join(" ".join(w["text"] for w in row) for row in rows)

        matches = list(_MF_PATTERN.finditer(text))
        if not matches:
            continue

        if len(matches) == 1:
            return _format_mf(matches[0])

        # Multiple candidates — pick closest to top-left
        best_mf   = None
        best_score = float("inf")

        for match in matches:
            first_digits = match.group(1)
            for word in words:
                if first_digits in word["text"]:
                    score = word["top"] + word["left"]   # Manhattan to (0,0)
                    if score < best_score:
                        best_score = score
                        best_mf   = _format_mf(match)
                    break

        if best_mf:
            return best_mf

    return None


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — DOCUMENT NUMBER ENGINE
#
# Trigger keywords: "Bon de commande", "Facture", "Invoice", "N°", "No.", "Ref"
# Strategy A (spatial): find trigger word → search 120px below + 300px right
# Strategy B (regex): fallback on full OCR text
# Pattern priority: XXXX/YYYY > letter-prefix/number > standalone 3-6 digits
# ─────────────────────────────────────────────────────────────────────────────

_TRIGGER_KEYWORDS = [
    "bon de commande", "commande fournisseur", "purchase order",
    "facture", "invoice", "bon de livraison",
    "n°", "no.", "n°:", "référence", "reference", "ref",
]

_DOC_NUM_PATTERNS = [
    re.compile(r'\b([A-Z]{2,5}-\d{2,4}\/\d{3,6})\b'),   # CDA-23/01151
    re.compile(r'\b(\d{3,6}\/\d{3,6})\b'),                # 1890/2023
    re.compile(r'\b(\d{4}-\d{3,6})\b'),                   # 2024-0053
    re.compile(r'\b([A-Z]{2,5}-\d{4,8})\b'),              # BCN-2023001
    re.compile(r'\b(\d{3,8})\b'),                          # 287  (last resort)
]


def extract_doc_number(pil_image: Image.Image,
                        ocr_text: str) -> Optional[str]:
    """
    ENGINE 2: Extract document number using spatial + regex.

    Strategy A: locate trigger keyword spatially, search in a 120px×400px
    rectangle below and to the right of it.
    Strategy B: regex fallback on full text.
    """
    words    = get_words(pil_image, min_conf=15)
    all_rows = group_into_rows(words, y_tol=12)

    # ── Strategy A: spatial ───────────────────────────────────────────
    trigger_word = None
    for row in all_rows:
        row_text = " ".join(w["text"] for w in row).lower()
        for kw in _TRIGGER_KEYWORDS:
            if kw in row_text:
                # Record the bottom of this trigger row
                trigger_word = {
                    "bottom": max(w["bottom"] for w in row),
                    "left":   min(w["left"]   for w in row),
                    "right":  max(w["right"]  for w in row),
                    "top":    min(w["top"]     for w in row),
                    "keyword": kw,
                }
                break
        if trigger_word:
            break

    if trigger_word:
        search_top    = trigger_word["top"]    - 5
        search_bottom = trigger_word["bottom"] + 120
        search_left   = trigger_word["left"]   - 10
        search_right  = trigger_word["right"]  + 400

        candidates = []
        for row in all_rows:
            for w in row:
                if (search_top <= w["top"] <= search_bottom and
                        search_left <= w["left"] <= search_right):
                    candidates.append(w["text"])

        candidate_text = " ".join(candidates)

        # Try patterns in priority order
        for pat in _DOC_NUM_PATTERNS:
            m = pat.search(candidate_text)
            if m and len(m.group(1)) >= 3:
                # Skip if it looks like a date (dd/mm/yyyy)
                val = m.group(1)
                if re.match(r'^\d{1,2}\/\d{1,2}\/\d{2,4}$', val):
                    continue
                return val

    # ── Strategy B: regex on full text ───────────────────────────────
    for pat_str in [
        r'N[°o]\s*(?:Commande|Facture|BL|Livraison|Cmd)\s*[:\-]?\s*([A-Z]{0,5}-?\d{3,6}\/\d{3,6})',
        r'N[°o]\s*[:\s]\s*([A-Z]{2,5}-\d{2,4}\/\d{3,6})',
        r'N[°o]\s*[:\s]\s*(\d{3,6}\/\d{3,6})',
        r'(?:Bon\s+de\s+commande|Facture)[^\n]{0,60}[\r\n]+\s*(\d{3,6}\/\d{3,6})',
        r'\b(CDA-\d{2}\/\d{4,6})\b',
        r'\b(BCN-\d{2}-\d{4})\b',
    ]:
        m = re.search(pat_str, ocr_text, re.IGNORECASE | re.MULTILINE)
        if m:
            return re.sub(r'\s+', '', m.group(1)).strip(".,;:")

    return None


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — DYNAMIC TABLE ENGINE (the LigneFac core)
#
# Step A: find header row — score every row by matching keywords from
#         _COL_KEYWORDS. Row with highest score (min 2) is the header.
# Step B: build "vertical lanes" — for each detected column, record
#         its LEFT and RIGHT boundary from the header word's bounding box.
#         A word belongs to a lane if its cx falls within [lane_left, lane_right].
#         If lanes overlap, assign by nearest cx (tie-break).
# Step C: for each row below the header, assign words to lanes.
# Step D: merge rows that have a description but no quantity/code
#         (multi-line product names).
# Stop:   when a row contains a footer keyword.
# ─────────────────────────────────────────────────────────────────────────────

# All known column header synonyms → canonical name
_COL_KEYWORDS: dict[str, str] = {
    # Code / Reference
    "no."           : "code",
    "n°"            : "code",
    "no"            : "code",
    "ref"           : "code",
    "référence"     : "code",
    "reference"     : "code",
    "code"          : "code",
    "cod"           : "code",
    # Description / Designation
    "désignation"   : "designation",
    "designation"   : "designation",
    "description"   : "designation",
    "libellé"       : "designation",
    "libelle"       : "designation",
    "article"       : "designation",
    "désig."        : "designation",
    "désig"         : "designation",
    "desig"         : "designation",
    "produit"       : "designation",
    # Quantity
    "qté"           : "quantite",
    "qty"           : "quantite",
    "quantité"      : "quantite",
    "quantite"      : "quantite",
    "qte"           : "quantite",
    "nbre"          : "quantite",
    "nb"            : "quantite",
    "qt"            : "quantite",
    # Unit price
    "prix unitaire" : "prix_unitaire",
    "p.u"           : "prix_unitaire",
    "p.u."          : "prix_unitaire",
    "pu"            : "prix_unitaire",
    "prix"          : "prix_unitaire",
    "tarif"         : "prix_unitaire",
    "unit price"    : "prix_unitaire",
    # Line total
    "montant"       : "montant",
    "total"         : "montant",
    "ht"            : "montant",
    "amount"        : "montant",
    # Pharmaceutical extras
    "emp"           : "emp",
    "emp frs"       : "emp",
    "frs"           : "emp",
    "forme"         : "forme",
    "code pct"      : "code_pct",
    "cod pct"       : "code_pct",
    "yn"            : "yn",
    "y/n"           : "yn",
}

_STOP_KEYWORDS = {
    "total ht", "total h.t", "total ttc", "net à payer", "montant total",
    "sous-total", "tva", "t.v.a", "fodec", "arrêté", "règlement",
    "escompte", "remise globale", "total général",
}

_MIN_HEADER_SCORE = 2   # need at least 2 column keywords to accept a header row


def _score_row_as_header(row: list[dict]) -> tuple[int, dict[str, dict]]:
    """
    Score a row as a potential table header.
    Returns (score, {col_name: {"cx": int, "left": int, "right": int}}).
    Tries multi-word keywords first for accuracy.
    """
    row_text  = " ".join(w["text"] for w in row).lower()
    found_cols: dict[str, dict] = {}
    score     = 0

    for kw, col_name in sorted(_COL_KEYWORDS.items(), key=lambda x: -len(x[0])):
        if kw not in row_text:
            continue
        if col_name in found_cols:
            continue   # already mapped this canonical name

        # Find the word(s) in the row that contain this keyword
        for w in row:
            if kw in w["text"].lower() or w["text"].lower() in kw:
                found_cols[col_name] = {
                    "cx":    w["cx"],
                    "left":  w["left"],
                    "right": w["right"],
                }
                score += 1
                break

    return score, found_cols


def _assign_word_to_lane(word_cx: int,
                          lanes: dict[str, dict]) -> str:
    """
    Assign a word to a column lane.

    First tries strict lane membership: word.cx within [lane.left, lane.right].
    If no strict match (lanes may be narrow from single header words),
    falls back to nearest cx distance.
    """
    # Strict: word center falls inside a lane's horizontal span
    for col_name, lane in lanes.items():
        if lane["left"] <= word_cx <= lane["right"]:
            return col_name

    # Fallback: nearest column center
    return min(lanes.items(), key=lambda kv: abs(word_cx - kv[1]["cx"]))[0]


def _parse_number(raw: str) -> Optional[float]:
    """Parse French/English number strings to float."""
    if not raw:
        return None
    s = re.sub(r'[€$£\s]', '', raw.strip())
    s = re.sub(r'[^\d,.]', '', s)
    if not s:
        return None
    dot_p = s.split('.')
    if '.' in s and ',' not in s:
        if len(dot_p) > 2:
            s = s.replace('.', '')
        elif len(dot_p) == 2 and len(dot_p[1]) == 3:
            s = s.replace('.', '')
    elif ',' in s and '.' in s:
        if s.rfind('.') > s.rfind(','):
            s = s.replace(',', '')
        else:
            s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        p = s.split(',')
        if len(p) == 2 and len(p[1]) <= 3:
            s = s.replace(',', '.')
        else:
            s = s.replace(',', '')
    try:
        return round(float(s), 6)
    except ValueError:
        return None


def _widen_lanes(lanes: dict[str, dict],
                  img_width: int) -> dict[str, dict]:
    """
    Widen narrow lanes so every pixel on the page belongs to exactly one lane.

    Algorithm:
      - Sort lanes by cx (left to right).
      - Set each lane's left boundary = midpoint between it and the previous lane.
      - Set each lane's right boundary = midpoint between it and the next lane.
      - First lane starts at 0; last lane ends at img_width.
    """
    if not lanes:
        return lanes

    ordered = sorted(lanes.items(), key=lambda kv: kv[1]["cx"])
    widened = {}

    for i, (col_name, lane) in enumerate(ordered):
        if i == 0:
            new_left = 0
        else:
            prev_cx  = ordered[i - 1][1]["cx"]
            new_left = (prev_cx + lane["cx"]) // 2

        if i == len(ordered) - 1:
            new_right = img_width
        else:
            next_cx   = ordered[i + 1][1]["cx"]
            new_right = (lane["cx"] + next_cx) // 2

        widened[col_name] = {
            "cx":    lane["cx"],
            "left":  new_left,
            "right": new_right,
        }

    return widened


def extract_table(pil_image: Image.Image,
                   taux_tva:   float = 0.0,
                   taux_fodec: float = 0.0,
                   y_tol:      int   = 12,
                   debug:      bool  = False) -> tuple[list, list, dict]:
    """
    ENGINE 3: Universal dynamic table extraction.

    Steps:
      A — Find header row (highest-scoring row with ≥2 column keywords)
      B — Build widened vertical lanes from header word positions
      C — Traverse rows below header, assign each word to a lane
      D — Merge continuation rows (description only, no code/qty)
      Stop — when footer keyword detected

    Returns:
      col_names  : list of detected column names left→right
      items      : list of lignefac-ready dicts
      debug_info : intermediate state for debugging
    """
    img_w, img_h = pil_image.size
    words        = get_words(pil_image, min_conf=15)
    all_rows     = group_into_rows(words, y_tol=y_tol)

    if debug:
        print(f"\n[TABLE DEBUG] Image: {img_w}×{img_h}px")
        print(f"[TABLE DEBUG] Words extracted: {len(words)}")
        print(f"[TABLE DEBUG] Row groups: {len(all_rows)}")
        for ri, row in enumerate(all_rows):
            print(f"  Row {ri:3d} y={min(w['top'] for w in row):4d}: "
                  f"{' | '.join(w['text'] for w in row)}")

    # ── Step A: find table header ─────────────────────────────────────
    best_idx   = -1
    best_score = 0
    best_lanes : dict[str, dict] = {}

    for idx, row in enumerate(all_rows):
        score, found = _score_row_as_header(row)
        if score > best_score:
            best_score = score
            best_idx   = idx
            best_lanes = found

    if best_score < _MIN_HEADER_SCORE:
        if debug:
            print(f"\n[TABLE DEBUG] No header found (best score={best_score}). "
                  f"Add missing keywords to _COL_KEYWORDS.")
        return [], [], {
            "error":       "No table header detected",
            "best_score":  best_score,
            "total_rows":  len(all_rows),
            "all_row_texts": [
                " ".join(w["text"] for w in row) for row in all_rows
            ],
        }

    if debug:
        print(f"\n[TABLE DEBUG] Header at row {best_idx} "
              f"(score={best_score}): {best_lanes}")

    # ── Step B: widen lanes to cover full page width ──────────────────
    lanes     = _widen_lanes(best_lanes, img_w)
    col_order = sorted(lanes.items(), key=lambda kv: kv[1]["cx"])
    col_names = [c[0] for c in col_order]

    if debug:
        print(f"[TABLE DEBUG] Widened lanes: "
              f"{[(n, l['left'], l['right']) for n, l in col_order]}")

    # ── Steps C+D: traverse data rows, assign, merge ──────────────────
    raw_rows = []

    for row_words in all_rows[best_idx + 1:]:
        if not row_words:
            continue

        # Stop rule
        row_text_lower = " ".join(w["text"] for w in row_words).lower()
        if any(kw in row_text_lower for kw in _STOP_KEYWORDS):
            if debug:
                print(f"[TABLE DEBUG] STOP at: {row_text_lower[:60]}")
            break

        # Assign each word to its lane
        cells: dict[str, list[str]] = {col: [] for col in col_names}
        for w in row_words:
            col = _assign_word_to_lane(w["cx"], lanes)
            if col in cells:
                cells[col].append(w["text"])

        row_str = {col: " ".join(tokens).strip()
                   for col, tokens in cells.items()}

        if not any(row_str.values()):
            continue

        raw_rows.append(row_str)

    # Step D: merge continuation rows
    # A continuation row has a designation but no code and no qty
    merged: list[dict] = []
    for row in raw_rows:
        code = row.get("code",        "").strip()
        qty  = row.get("quantite",    "").strip()
        desc = row.get("designation", "").strip()

        has_code = bool(code)
        has_qty  = bool(qty) and _parse_number(qty) is not None
        has_desc = bool(desc) and len(desc) >= 2

        if not has_code and not has_qty and has_desc and merged:
            # Append description to previous row
            merged[-1]["designation"] = (
                merged[-1].get("designation", "") + " " + desc
            ).strip()
        else:
            merged.append(row)

    # Build final lignefac items
    items = []
    for row in merged:
        code    = row.get("code",        "").strip()
        lib     = row.get("designation", "").strip()
        qty_raw = row.get("quantite",    "").strip()
        pu_raw  = row.get("prix_unitaire","").strip()
        mt_raw  = row.get("montant",     "").strip()

        qty = _parse_number(qty_raw)
        pu  = _parse_number(pu_raw)
        mt  = _parse_number(mt_raw)

        # Back-calculate missing values
        if pu is None and qty and mt and qty > 0:
            pu = round(mt / qty, 6)
        if mt is None and qty and pu:
            mt = round(qty * pu, 6)

        # Skip blank or header-repeat rows
        if not lib and not code:
            continue
        if lib.lower() in {"désignation","designation","libellé",
                            "description","article"}:
            continue

        items.append({
            "Code"       : code,
            "LibProd"    : lib,
            "Quantité"   : qty   or 0.0,
            "PrixVente"  : pu    or 0.0,
            "TauxTVA"    : taux_tva,
            "TauxFODEC"  : taux_fodec,
            "Remise"     : 0.0,
            "line_total" : mt,
            "Forme"      : row.get("forme",    ""),
            "Code_PCT"   : row.get("code_pct", ""),
            "YN"         : row.get("yn",       ""),
            "Emp_FRS"    : row.get("emp",      ""),
        })

    debug_info = {
        "total_word_rows" : len(all_rows),
        "header_row_idx"  : best_idx,
        "header_score"    : best_score,
        "col_lanes"       : {k: {"left":v["left"],"cx":v["cx"],"right":v["right"]}
                             for k,v in lanes.items()},
        "raw_rows_found"  : len(raw_rows),
        "items_after_merge": len(items),
    }

    return col_names, items, debug_info


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — MASTER ENTRY POINT
# Called by streamlit_ocr_app.py
# ─────────────────────────────────────────────────────────────────────────────

def build_lignefac_json(
    pil_image:     Image.Image,
    ocr_full_text: str,
    taux_tva:      float = 0.0,
    taux_fodec:    float = 0.0,
    y_tolerance:   int   = 12,
    debug:         bool  = False,
) -> dict:
    """
    Run all three engines and return structured result.

    Compatible with streamlit_ocr_app.py which calls:
        result = build_lignefac_json(pil_image, ocr_full_text, taux_tva=...)
        bbox_col_names = result["table_columns"]
        bbox_items     = result["ligne_items"]
    """
    mf  = extract_mf(pil_image)
    doc = extract_doc_number(pil_image, ocr_full_text)

    col_names, items, tbl_debug = extract_table(
        pil_image,
        taux_tva   = taux_tva,
        taux_fodec = taux_fodec,
        y_tol      = y_tolerance,
        debug      = debug,
    )

    return {
        # used by streamlit_ocr_app.py
        "matricule_fiscale" : mf,
        "document_number"   : doc,
        "table_columns"     : col_names,
        "ligne_items"       : items,
        "raw_row_count"     : tbl_debug.get("total_word_rows", 0),
        "mapped_item_count" : len(items),
        "debug"             : tbl_debug,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — STANDALONE RUNNER
#
# Accepts PNG, JPG, or PDF (first page extracted automatically).
# Run with --debug to see every row Tesseract found.
#
# Examples:
#   python sprint3/invoice_extractor_v2.py invoice.png
#   python sprint3/invoice_extractor_v2.py invoice.pdf --debug
# ─────────────────────────────────────────────────────────────────────────────

def _pdf_to_pil(pdf_path: str, dpi: int = 300) -> Image.Image:
    """Convert first page of a PDF to a PIL image."""
    try:
        import fitz   # PyMuPDF
        doc  = fitz.open(pdf_path)
        page = doc[0]
        mat  = fitz.Matrix(dpi / 72, dpi / 72)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        import numpy as np, cv2
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n)
        img_bgr = cv2.cvtColor(img_np,
                               cv2.COLOR_RGB2BGR if pix.n == 3
                               else cv2.COLOR_RGBA2BGR)
        return Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    except ImportError:
        raise ImportError("PyMuPDF not installed. Run: pip install pymupdf")


if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python sprint3/invoice_extractor_v2.py <invoice.png|invoice.pdf> [--debug]")
        sys.exit(1)

    path  = sys.argv[1]
    dbg   = "--debug" in sys.argv

    print(f"\n{'='*60}")
    print(f"  SE24D2 Invoice Extractor v2")
    print(f"  File: {path}")
    print(f"{'='*60}")

    # Load image
    if path.lower().endswith(".pdf"):
        print("  Converting PDF page 1 → image at 300 DPI…")
        img = _pdf_to_pil(path, dpi=300)
    else:
        img = Image.open(path).convert("RGB")

    print(f"  Image size: {img.size[0]}×{img.size[1]}px")

    # Full OCR text (for fallback strategies)
    ocr_text = pytesseract.image_to_string(
        img, lang="fra+eng", config="--psm 6 --oem 1")

    # Run all three engines
    result = build_lignefac_json(
        pil_image     = img,
        ocr_full_text = ocr_text,
        taux_tva      = 0.0,
        taux_fodec    = 0.0,
        y_tolerance   = 12,
        debug         = dbg,
    )

    # ── Output in your required JSON format ───────────────────────────
    output = {
        "matricule_fiscale" : result["matricule_fiscale"],
        "numero_document"   : result["document_number"],
        "lignes_facture"    : [
            {
                "code"         : item["Code"],
                "designation"  : item["LibProd"],
                "quantite"     : item["Quantité"],
                "prix_unitaire": item["PrixVente"],
            }
            for item in result["ligne_items"]
        ],
    }

    print(f"\n{'─'*60}")
    print("  EXTRACTION RESULT")
    print(f"{'─'*60}")
    print(json.dumps(output, ensure_ascii=False, indent=2))

    print(f"\n{'─'*60}")
    print(f"  Columns detected : {result['table_columns']}")
    print(f"  Rows extracted   : {result['mapped_item_count']}")
    print(f"  Debug            : {result['debug']}")

    if not result["ligne_items"]:
        print("\n  ⚠️  TABLE IS EMPTY. Common causes:")
        print("  1. You are running on a SCREENSHOT of the UI, not the real invoice.")
        print("     → Upload the actual invoice PDF or scanned image.")
        print("  2. The header keywords are in a language not in _COL_KEYWORDS.")
        print("     → Run with --debug to see all rows Tesseract found.")
        print("     → Add missing keywords to _COL_KEYWORDS in this file.")
        print("  3. OCR quality is too low (scanned at low DPI or blurry).")
        print("     → Increase scan DPI to 300+ or improve preprocessing.")
        print("\n  Run with --debug to see all detected rows:")
        print(f"  python sprint3/invoice_extractor_v2.py {path} --debug")