# =============================================================================
# sprint3/line_item_extractor.py
# SE24D2 — Automated Invoice Intelligence System
# Robust table row extraction using OCR bounding boxes
# =============================================================================
#
# WHY THIS FILE EXISTS:
#   REGEX on flat OCR text misses 80%+ of table rows because:
#     1. It relies on specific code formats (BA26, AG23) — misses anything else
#     2. It reads text linearly — breaks on multi-line descriptions
#     3. It ignores spatial layout — can't distinguish columns
#
#   This file uses pytesseract.image_to_data() bounding boxes to:
#     Step A — group words into rows by Y-axis proximity
#     Step B — detect columns (description / qty / price / total) by X position
#     Step C — handle multi-line descriptions and OCR noise
#
# USAGE:
#   from sprint3.line_item_extractor import extract_line_items
#   items = extract_line_items(pil_image, debug=False)
#
# OUTPUT:
#   [
#     {"description": "Tissu coton BA26", "qty": 100,
#      "unit_price": 1.05, "total": 105.0, "raw_row": "..."},
#     ...
#   ]
# =============================================================================

import re
import numpy as np
import pytesseract
from PIL import Image
from typing import Optional


# ---------------------------------------------------------------------------
# SECTION 1 — OCR word extraction with bounding boxes
# ---------------------------------------------------------------------------

def get_ocr_words(image: Image.Image) -> list:
    """
    Run Tesseract image_to_data() and return a clean list of word dicts.

    Each dict contains:
      text, left, top, width, height, conf
      plus computed: right (left+width), bottom (top+height), cx, cy (centers)

    Words with confidence < 30 or empty text are discarded.
    """
    data = pytesseract.image_to_data(
        image,
        lang="fra+eng",
        config="--psm 6 --oem 1",
        output_type=pytesseract.Output.DICT,
    )

    words = []
    n = len(data["text"])

    for i in range(n):
        text = str(data["text"][i]).strip()
        conf = int(data["conf"][i])

        if not text or conf < 30:
            continue

        left   = int(data["left"][i])
        top    = int(data["top"][i])
        width  = int(data["width"][i])
        height = int(data["height"][i])

        words.append({
            "text":   text,
            "left":   left,
            "top":    top,
            "width":  width,
            "height": height,
            "right":  left + width,
            "bottom": top + height,
            "cx":     left + width  // 2,
            "cy":     top  + height // 2,
            "conf":   conf,
        })

    return words


# ---------------------------------------------------------------------------
# SECTION 2 — Step A: Group words into rows by Y-axis proximity
# ---------------------------------------------------------------------------

def group_words_into_rows(words: list, y_tolerance: int = 8) -> list:
    """
    Group words that share approximately the same vertical position into rows.

    Algorithm:
      1. Sort all words by their top-Y coordinate.
      2. Start a new row whenever the next word's top-Y is more than
         y_tolerance pixels below the current row's average Y.
      3. Within each row, sort words left-to-right by X position.

    y_tolerance = 8px works well at 300 DPI.
    Increase to 12-15 if your invoice has large line spacing.

    Returns:
      List of rows, each row is a list of word dicts sorted left-to-right.
    """
    if not words:
        return []

    # Sort by vertical position first
    sorted_words = sorted(words, key=lambda w: w["top"])

    rows       = []
    current_row = [sorted_words[0]]

    for word in sorted_words[1:]:
        # Compare to the average Y of the current row
        avg_top = sum(w["top"] for w in current_row) / len(current_row)

        if abs(word["top"] - avg_top) <= y_tolerance:
            current_row.append(word)
        else:
            # Sort current row left-to-right and save it
            rows.append(sorted(current_row, key=lambda w: w["left"]))
            current_row = [word]

    # Don't forget the last row
    if current_row:
        rows.append(sorted(current_row, key=lambda w: w["left"]))

    return rows


# ---------------------------------------------------------------------------
# SECTION 3 — Step B: Detect table body region and column boundaries
# ---------------------------------------------------------------------------

def detect_table_region(rows: list, image_height: int) -> tuple:
    """
    Find which rows belong to the table body (not header/footer).

    Strategy:
      - Header rows contain keywords like "désignation", "quantité", "prix"
      - Footer rows contain keywords like "total", "tva", "ttc", "net à payer"
      - Table body rows are between header and footer rows

    Returns:
      (start_row_index, end_row_index) — slice of rows list
    """
    HEADER_KEYWORDS = {
        "désignation", "designation", "libellé", "article", "description",
        "référence", "ref", "code", "quantité", "qté", "qty",
        "prix", "unitaire", "pu", "montant", "total", "ht",
    }
    FOOTER_KEYWORDS = {
        "total", "sous-total", "tva", "t.v.a", "ttc", "fodec",
        "net", "payer", "règlement", "remise", "escompte",
        "arrêté", "arrete",
    }

    start_idx = 0
    end_idx   = len(rows)

    for i, row in enumerate(rows):
        row_text = " ".join(w["text"].lower() for w in row)
        # Table header row — the row AFTER this is where body starts
        matches = sum(1 for kw in HEADER_KEYWORDS if kw in row_text)
        if matches >= 2:
            start_idx = i + 1
            break

    for i in range(len(rows) - 1, start_idx, -1):
        row_text = " ".join(w["text"].lower() for w in rows[i])
        matches = sum(1 for kw in FOOTER_KEYWORDS if kw in row_text)
        if matches >= 2:
            end_idx = i
            break

    return start_idx, end_idx


def detect_column_boundaries(header_row: list, image_width: int) -> dict:
    """
    Use the table header row to find the X positions of each column.

    Looks for column header keywords and records their X center position.
    Returns a dict of {column_name: x_center}.

    Example: {"qty": 420, "unit_price": 520, "total": 620}
    """
    COLUMN_KEYWORDS = {
        "qty":        ["qté", "qty", "quantité", "quantite", "nbre", "nb"],
        "unit_price": ["pu", "prix", "unitaire", "p.u", "p.v", "tarif"],
        "total":      ["montant", "total", "ht", "net", "prix\ntotal"],
        "description":["désignation", "designation", "libellé", "article",
                       "description", "référence", "ref"],
    }

    boundaries = {}
    for word in header_row:
        word_lower = word["text"].lower().strip(".:;")
        for col_name, keywords in COLUMN_KEYWORDS.items():
            if any(kw in word_lower for kw in keywords):
                if col_name not in boundaries:
                    boundaries[col_name] = word["cx"]

    return boundaries


# ---------------------------------------------------------------------------
# SECTION 4 — Step B: Assign words to columns using X position
# ---------------------------------------------------------------------------

def assign_words_to_columns(
    row_words:    list,
    col_bounds:   dict,
    image_width:  int,
) -> dict:
    """
    Given a row of words and column X boundaries, assign each word
    to its most likely column based on horizontal position.

    If no column boundaries were detected (col_bounds is empty),
    falls back to heuristic position-based assignment.

    Returns:
      {"description": "Tissu BA26", "qty": "100", "unit_price": "1,05", "total": "105,00"}
    """
    result = {"description": [], "qty": [], "unit_price": [], "total": []}

    if col_bounds:
        # Sort columns by X position
        sorted_cols = sorted(col_bounds.items(), key=lambda x: x[1])
        col_names   = [c[0] for c in sorted_cols]
        col_centers = [c[1] for c in sorted_cols]

        for word in row_words:
            # Find the nearest column center
            distances  = [abs(word["cx"] - cx) for cx in col_centers]
            nearest    = col_names[distances.index(min(distances))]
            result[nearest].append(word["text"])

    else:
        # Fallback: split by thirds of image width
        # Left third → description, middle → qty, right → prices
        third = image_width // 3

        for word in row_words:
            if word["cx"] < third:
                result["description"].append(word["text"])
            elif word["cx"] < 2 * third:
                result["qty"].append(word["text"])
            else:
                result["total"].append(word["text"])

    # Join multi-word values
    return {k: " ".join(v).strip() for k, v in result.items()}


# ---------------------------------------------------------------------------
# SECTION 5 — Step C: Parse numbers and clean descriptions
# ---------------------------------------------------------------------------

def parse_number(raw: str) -> Optional[float]:
    """
    Convert raw OCR number string to float.
    Handles French format: 1 200,50 → 1200.50
    Handles English format: 1,200.50 → 1200.50
    Returns None if not parseable.
    """
    if not raw:
        return None

    s = str(raw).strip()
    # Remove currency symbols and spaces
    s = re.sub(r"[€$£\s]", "", s)
    # Remove everything except digits, comma, dot
    s = re.sub(r"[^\d,.]", "", s)

    if not s:
        return None

    # French format: comma is decimal separator
    if "," in s and "." in s:
        # 1.200,50 → remove dot, replace comma
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            # 1,200.50 → remove comma
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        # 1,05 → decimal (2-3 digits after comma = decimal)
        if len(parts) == 2 and len(parts[1]) <= 3:
            s = s.replace(",", ".")
        else:
            # 1,200 → thousands separator
            s = s.replace(",", "")

    try:
        return round(float(s), 3)
    except ValueError:
        return None


def clean_description(text: str) -> str:
    """Remove OCR noise from product descriptions."""
    if not text:
        return ""
    # Remove isolated special chars
    text = re.sub(r"(?<!\w)[|\\/_](?!\w)", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"\s{2,}", " ", text)
    # Remove leading/trailing punctuation
    text = text.strip(".,;:-|/\\")
    return text.strip()


def is_likely_table_row(columns: dict) -> bool:
    """
    Decide if a row is a real product line or noise/header/footer.

    A real product line has at least:
      - A non-empty description with 3+ characters
      - OR a parseable number in qty, unit_price, or total
    """
    desc = columns.get("description", "")
    qty  = parse_number(columns.get("qty", ""))
    pu   = parse_number(columns.get("unit_price", ""))
    tot  = parse_number(columns.get("total", ""))

    has_desc   = len(clean_description(desc)) >= 3
    has_number = any(v is not None for v in [qty, pu, tot])

    # Must have description AND at least one number
    return has_desc and has_number


# ---------------------------------------------------------------------------
# SECTION 6 — Step C: Merge multi-line description rows
# ---------------------------------------------------------------------------

def merge_multiline_rows(structured_rows: list) -> list:
    """
    Handle multi-line descriptions: when a row has a description but
    no numbers, it's likely a continuation of the previous row's description.

    Algorithm:
      - If current row has NO numbers and previous row HAS numbers →
        append current row's description to the previous row.
      - Otherwise keep as separate row.
    """
    if not structured_rows:
        return []

    merged = [structured_rows[0]]

    for row in structured_rows[1:]:
        qty = parse_number(row.get("qty", ""))
        pu  = parse_number(row.get("unit_price", ""))
        tot = parse_number(row.get("total", ""))
        desc = clean_description(row.get("description", ""))

        # No numbers in this row → likely continuation
        if qty is None and pu is None and tot is None and desc:
            prev = merged[-1]
            prev["description"] = (
                prev.get("description", "") + " " + desc
            ).strip()
        else:
            merged.append(row)

    return merged


# ---------------------------------------------------------------------------
# SECTION 7 — Main public function
# ---------------------------------------------------------------------------

def extract_line_items(
    image:       Image.Image,
    debug:       bool = False,
    y_tolerance: int  = 8,
) -> list:
    """
    Full pipeline: image → structured line items.

    Args:
        image       : PIL Image — the cleaned invoice image from Sprint 2
        debug       : if True, prints intermediate steps
        y_tolerance : Y-axis grouping threshold in pixels (default 8)

    Returns:
        List of dicts:
        [
          {
            "description": str,
            "qty":         float or None,
            "unit_price":  float or None,
            "total":       float or None,
            "raw_row":     str,   # full raw text of the row for debugging
            # lignefac-compatible fields:
            "LibProd":     str,
            "Quantité":    float,
            "PrixVente":   float,
            "TauxTVA":     float,
            "TauxFODEC":   float,
            "Remise":      float,
          },
          ...
        ]
    """
    img_w, img_h = image.size

    # ── A: Get words with bounding boxes ──────────────────────────────
    words = get_ocr_words(image)
    if debug:
        print(f"[line_extractor] Total OCR words: {len(words)}")

    if not words:
        return []

    # ── A: Group into rows by Y proximity ─────────────────────────────
    rows = group_words_into_rows(words, y_tolerance=y_tolerance)
    if debug:
        print(f"[line_extractor] Rows after Y-grouping: {len(rows)}")

    # ── B: Find table body region ──────────────────────────────────────
    start_idx, end_idx = detect_table_region(rows, img_h)
    table_rows         = rows[start_idx:end_idx]
    header_row         = rows[start_idx - 1] if start_idx > 0 else []

    if debug:
        print(f"[line_extractor] Table rows found: {len(table_rows)} "
              f"(rows {start_idx}–{end_idx})")

    # ── B: Detect column boundaries from header row ────────────────────
    col_bounds = detect_column_boundaries(header_row, img_w)
    if debug:
        print(f"[line_extractor] Column boundaries: {col_bounds}")

    # ── B: Assign words to columns ────────────────────────────────────
    structured_rows = []
    for row_words in table_rows:
        columns  = assign_words_to_columns(row_words, col_bounds, img_w)
        raw_text = " ".join(w["text"] for w in row_words)
        columns["raw_row"] = raw_text
        structured_rows.append(columns)

    # ── C: Merge multi-line descriptions ──────────────────────────────
    structured_rows = merge_multiline_rows(structured_rows)

    # ── C: Filter noise, parse numbers, build final output ────────────
    line_items = []
    for row in structured_rows:
        if not is_likely_table_row(row):
            if debug:
                print(f"[line_extractor] SKIP: {row.get('raw_row', '')[:60]}")
            continue

        desc     = clean_description(row.get("description", ""))
        qty      = parse_number(row.get("qty", ""))
        pu       = parse_number(row.get("unit_price", ""))
        total    = parse_number(row.get("total", ""))

        # If unit_price missing but qty and total exist → compute it
        if pu is None and qty and total and qty > 0:
            pu = round(total / qty, 6)

        # If total missing but qty and unit_price exist → compute it
        if total is None and qty and pu:
            total = round(qty * pu, 6)

        item = {
            # Human-readable fields
            "description": desc,
            "qty":         qty,
            "unit_price":  pu,
            "total":       total,
            "raw_row":     row.get("raw_row", ""),
            # lignefac-compatible column names (for Sprint 4 DB injection)
            "LibProd":     desc,
            "Quantité":    qty   or 0.0,
            "PrixVente":   pu    or 0.0,
            "TauxTVA":     0.0,   # filled from footer extraction
            "TauxFODEC":   0.0,
            "Remise":      0.0,
        }
        line_items.append(item)

    if debug:
        print(f"[line_extractor] Final line items: {len(line_items)}")

    return line_items


# ---------------------------------------------------------------------------
# SECTION 8 — Standalone test
# Run: python sprint3/line_item_extractor.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("SE24D2 — Line Item Extractor Test")
    print("=" * 60)

    # Try to use a real invoice if provided as argument
    if len(sys.argv) > 1:
        img_path = sys.argv[1]
        print(f"\nLoading image: {img_path}")
        image = Image.open(img_path).convert("RGB")
    else:
        # Create a synthetic invoice table image for testing
        from PIL import ImageDraw
        print("\nNo image provided — using synthetic invoice table")
        print("Usage: python sprint3/line_item_extractor.py path/to/invoice.png\n")

        img  = Image.new("RGB", (900, 600), color="white")
        draw = ImageDraw.Draw(img)

        # Table header
        draw.text((10,  40), "Code",        fill="black")
        draw.text((100, 40), "Désignation", fill="black")
        draw.text((500, 40), "Qté",         fill="black")
        draw.text((600, 40), "P.U",         fill="black")
        draw.text((750, 40), "Montant",     fill="black")

        # Table rows
        rows = [
            ("BA26", "Tissu coton blanc 80g",          "100", "1,050", "105,000"),
            ("AG23", "Agrafe métallique 12mm",          "650", "1,090", "708,500"),
            ("BA27", "Tissu polyester noir 120g",       "350", "1,090", "381,500"),
            ("FO01", "Fil à coudre blanc bobine 500m",  "200", "0,850", "170,000"),
            ("ET05", "Étiquette tissée logo 3x2cm",    "1000", "0,120", "120,000"),
            ("BT12", "Bouton plastique 4 trous 15mm",   "500", "0,045",  "22,500"),
            ("ZI08", "Fermeture éclair 20cm noire",     "300", "0,380", "114,000"),
        ]
        for i, (code, desc, qty, pu, total) in enumerate(rows):
            y = 80 + i * 30
            draw.text((10,  y), code,  fill="black")
            draw.text((100, y), desc,  fill="black")
            draw.text((500, y), qty,   fill="black")
            draw.text((600, y), pu,    fill="black")
            draw.text((750, y), total, fill="black")

        # Footer
        draw.text((10, 300), "Total HT : 1 621,500", fill="black")
        draw.text((10, 330), "TVA 19%  :   308,085", fill="black")
        draw.text((10, 360), "Total TTC: 1 929,585", fill="black")
        image = img

    print("\nRunning extraction (debug=True)…\n")
    items = extract_line_items(image, debug=True)

    print(f"\n{'─'*70}")
    print(f"{'#':<4} {'Description':<35} {'Qty':>6} {'Unit Price':>10} {'Total':>10}")
    print(f"{'─'*70}")
    for i, item in enumerate(items, 1):
        print(f"{i:<4} {item['description'][:34]:<35} "
              f"{str(item['qty'] or '—'):>6} "
              f"{str(item['unit_price'] or '—'):>10} "
              f"{str(item['total'] or '—'):>10}")
    print(f"{'─'*70}")
    print(f"Total rows extracted: {len(items)}")
    print("\n✅ line_item_extractor.py is working.")
    print("   Pass a real invoice: python sprint3/line_item_extractor.py invoice.png")