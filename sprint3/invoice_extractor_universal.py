"""
invoice_extractor_universal.py
SE24D2 — Spatial Lane-Based Invoice Extractor (v3)

MF engine: top 25% scan, smallest (top + left) score wins.
"""

import re
import json
import fitz
import pdfplumber
import pytesseract
import numpy as np
from PIL import Image
from pathlib import Path
from typing import Optional

# =============================================================================
# CONFIG
# =============================================================================

HEADER_SYNONYMS = {
    "code":        ["code", "ref", "référence", "reference", "art", "article"],
    "quantite":    ["qté", "qte", "qty", "quantité", "quantite", "nbre", "nb",
                    "qte.", "qté."],
    "designation": ["désignation", "designation", "libellé", "libelle",
                    "description", "produit", "dénomination"],
    "prix_unit":   ["pu", "p.u", "prix unit", "prix unitaire", "p.u ht", "pu ht",
                    "prix"],
    "montant":     ["montant", "total", "total ht", "mt ht", "mt", "net"],
}

DOC_TYPE_KEYWORDS = {
    "Bon de commande":  ["bon de commande", "commande fournisseur", "b.c."],
    "Bon de livraison": ["bon de livraison", "note d'envoi", "b.l."],
    "Facture":          ["facture", "invoice"],
    "Proforma":         ["proforma", "pro-forma", "pro forma"],
    "Avoir":            ["avoir", "note de crédit"],
}

# ─────────────────────────────────────────────────────────────────────────────
# MATRICULE FISCALE ENGINE
# Tunisian MF: 7-8 digits / letter / letter / letter / 3 digits
# Handles spaces or slashes between components
# ─────────────────────────────────────────────────────────────────────────────
_MF_PATTERN = re.compile(
    r'\b(\d{7,8})\s*[/\\\|\s]?\s*([A-Z])\s*[/\\\|\s]?\s*([A-Z])\s*[/\\\|\s]?\s*([A-Z])\s*[/\\\|\s]?\s*(\d{3})\b',
    re.IGNORECASE,
)

DOCNUM_PATTERNS = [
    r'\b(\d{3,6}/\d{2,4})\b',
    r'\b([A-Z]{2,4}-\d{2,6})\b',
    r'\b([A-Z]{2,4}\d{2,6})\b',
    r'\b(\d{4,8})\b',
]


# =============================================================================
# WORD EXTRACTION
# =============================================================================

def _words_from_native_pdf(pdf_path: str, page_index: int = 0):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        words = page.extract_words(
            x_tolerance=2, y_tolerance=2,
            keep_blank_chars=False, use_text_flow=False,
        )
        page_w, page_h = page.width, page.height
    return [
        {
            "text": w["text"],
            "x0":   float(w["x0"]),
            "x1":   float(w["x1"]),
            "top":  float(w["top"]),
            "bottom": float(w["bottom"]),
            "left": float(w["x0"]),  # alias for MF engine
            "cx":   (float(w["x0"]) + float(w["x1"])) / 2,
            "cy":   (float(w["top"]) + float(w["bottom"])) / 2,
        }
        for w in words
    ], page_w, page_h


def _words_from_scanned_pdf(pdf_path: str, page_index: int = 0, dpi: int = 300):
    doc  = fitz.open(pdf_path)
    page = doc[page_index]
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    img  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    pil  = Image.fromarray(img)

    data = pytesseract.image_to_data(
        pil, lang="fra+eng",
        config="--psm 6 --oem 1",
        output_type=pytesseract.Output.DICT,
    )

    words = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        try:
            conf = int(data["conf"][i])
        except (ValueError, TypeError):
            conf = 0
        if conf < 30:
            continue
        x, y = data["left"][i], data["top"][i]
        w, h = data["width"][i], data["height"][i]
        words.append({
            "text":   txt,
            "x0":     float(x),
            "x1":     float(x + w),
            "top":    float(y),
            "bottom": float(y + h),
            "left":   float(x),  # alias for MF engine
            "cx":     float(x + w / 2),
            "cy":     float(y + h / 2),
        })
    return words, float(pil.width), float(pil.height), pil


def _detect_pdf_type(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        total = sum(len((p.extract_text() or "").strip()) for p in pdf.pages)
    return "native" if total > 100 else "scanned"


def extract_words(pdf_path: str, page_index: int = 0):
    """Returns (words, page_w, page_h, source, pil_image_or_None)."""
    if _detect_pdf_type(pdf_path) == "native":
        words, w, h = _words_from_native_pdf(pdf_path, page_index)
        # Render the native PDF to PIL too, so the MF engine can re-OCR a crop
        doc  = fitz.open(pdf_path)
        page = doc[page_index]
        mat  = fitz.Matrix(300 / 72, 300 / 72)
        pix  = page.get_pixmap(matrix=mat, alpha=False)
        img  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        pil  = Image.fromarray(img)
        return words, w, h, "native", pil
    words, w, h, pil = _words_from_scanned_pdf(pdf_path, page_index)
    return words, w, h, "scanned", pil


# =============================================================================
# ROW GROUPING
# =============================================================================

def group_words_into_rows(words, y_tolerance: float = 5.0):
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (w["cy"], w["x0"]))
    rows = []
    current = [sorted_words[0]]
    current_cy = sorted_words[0]["cy"]
    for w in sorted_words[1:]:
        if abs(w["cy"] - current_cy) <= y_tolerance:
            current.append(w)
            current_cy = sum(x["cy"] for x in current) / len(current)
        else:
            rows.append(sorted(current, key=lambda x: x["x0"]))
            current = [w]
            current_cy = w["cy"]
    rows.append(sorted(current, key=lambda x: x["x0"]))
    return rows


def estimate_avg_char_width(words) -> float:
    widths = []
    for w in words:
        if len(w["text"]) > 0:
            widths.append((w["x1"] - w["x0"]) / max(len(w["text"]), 1))
    if not widths:
        return 6.0
    return float(sorted(widths)[len(widths) // 2])


# =============================================================================
# MATRICULE FISCALE — top-25% + (top + left) score
# =============================================================================

def _format_mf(m: re.Match) -> str:
    return f"{m.group(1)}{m.group(2).upper()}/{m.group(3).upper()}/{m.group(4).upper()}/{m.group(5)}"


def _get_words_from_crop(pil_crop: Image.Image, min_conf: int = 15):
    """OCR a PIL image crop and return word dicts in the same format we use."""
    data = pytesseract.image_to_data(
        pil_crop, lang="fra+eng",
        config="--psm 6 --oem 1",
        output_type=pytesseract.Output.DICT,
    )
    words = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        try:
            conf = int(data["conf"][i])
        except (ValueError, TypeError):
            conf = 0
        if conf < min_conf:
            continue
        x, y = data["left"][i], data["top"][i]
        w, h = data["width"][i], data["height"][i]
        words.append({
            "text": txt,
            "left": float(x),
            "top":  float(y),
            "x0":   float(x),
            "x1":   float(x + w),
            "bottom": float(y + h),
            "cx":   float(x + w / 2),
            "cy":   float(y + h / 2),
        })
    return words


def _group_into_rows_simple(words, y_tol: int = 10):
    """Simple row grouping for the MF engine."""
    if not words:
        return []
    sorted_w = sorted(words, key=lambda w: (w["top"], w["left"]))
    rows = []
    current = [sorted_w[0]]
    current_top = sorted_w[0]["top"]
    for w in sorted_w[1:]:
        if abs(w["top"] - current_top) <= y_tol:
            current.append(w)
        else:
            rows.append(sorted(current, key=lambda x: x["left"]))
            current = [w]
            current_top = w["top"]
    rows.append(sorted(current, key=lambda x: x["left"]))
    return rows


def extract_mf(pil_image: Image.Image) -> Optional[str]:
    """
    ENGINE 1: Extract supplier Matricule Fiscale.

    Scans the top 25% of the image.
    If multiple MF patterns found, returns the one whose first digit
    group appears at the smallest (top + left) pixel sum.
    Falls back to top 50% then full page if nothing found.
    """
    if pil_image is None:
        return None

    img_w, img_h = pil_image.size

    for fraction in [0.25, 0.50, 1.0]:
        crop  = pil_image.crop((0, 0, img_w, int(img_h * fraction)))
        words = _get_words_from_crop(crop, min_conf=15)
        rows  = _group_into_rows_simple(words, y_tol=10)

        # Reconstruct text preserving spatial order
        text = "\n".join(" ".join(w["text"] for w in row) for row in rows)

        matches = list(_MF_PATTERN.finditer(text))
        if not matches:
            continue

        if len(matches) == 1:
            return _format_mf(matches[0])

        # Multiple candidates — pick closest to top-left (Manhattan distance)
        best_mf    = None
        best_score = float("inf")

        for match in matches:
            first_digits = match.group(1)
            for word in words:
                if first_digits in word["text"]:
                    score = word["top"] + word["left"]
                    if score < best_score:
                        best_score = score
                        best_mf    = _format_mf(match)
                    break

        if best_mf:
            return best_mf

    return None


# =============================================================================
# HEADER DETECTION
# =============================================================================

def _match_header_token(text: str) -> Optional[str]:
    t = text.lower().strip(" .:|")
    for canonical, synonyms in HEADER_SYNONYMS.items():
        for syn in synonyms:
            if t == syn or t == syn.replace(" ", ""):
                return canonical
    return None


def detect_header_row(rows):
    best_idx = None
    best_hits = {}

    for idx, row in enumerate(rows):
        hits = {}
        for w in row:
            canon = _match_header_token(w["text"])
            if canon and canon not in hits:
                hits[canon] = w

        for i in range(len(row) - 1):
            merged = f"{row[i]['text']} {row[i+1]['text']}"
            canon = _match_header_token(merged)
            if canon and canon not in hits:
                hits[canon] = {
                    "text": merged,
                    "x0":   row[i]["x0"],
                    "x1":   row[i+1]["x1"],
                    "top":  min(row[i]["top"], row[i+1]["top"]),
                    "bottom": max(row[i]["bottom"], row[i+1]["bottom"]),
                    "cx":   (row[i]["x0"] + row[i+1]["x1"]) / 2,
                    "cy":   (row[i]["cy"] + row[i+1]["cy"]) / 2,
                }

        if len(hits) >= 2 and len(hits) > len(best_hits):
            best_idx = idx
            best_hits = hits

    return best_idx, best_hits if best_idx is not None else None


def build_lanes(header_hits: dict, page_width: float) -> list:
    sorted_heads = sorted(header_hits.items(), key=lambda kv: kv[1]["cx"])
    lanes = []
    for i, (name, w) in enumerate(sorted_heads):
        if i == 0:
            x_start = 0.0
        else:
            prev_cx = sorted_heads[i-1][1]["cx"]
            x_start = (prev_cx + w["cx"]) / 2
        if i == len(sorted_heads) - 1:
            x_end = page_width
        else:
            next_cx = sorted_heads[i+1][1]["cx"]
            x_end = (w["cx"] + next_cx) / 2
        lanes.append((x_start, x_end, name))
    return lanes


def assign_word_to_lane(word, lanes):
    cx = word["cx"]
    for x_start, x_end, name in lanes:
        if x_start <= cx < x_end:
            return name
    return None


# =============================================================================
# WIDE-GAP ROW SPLITTING
# =============================================================================

def split_row_by_gaps(row, lanes, avg_char_width: float):
    if not row:
        return {}

    sorted_row = sorted(row, key=lambda w: w["x0"])
    GAP_THRESHOLD = avg_char_width * 2.0

    buckets = {name: [] for _, _, name in lanes}
    lane_names = [name for _, _, name in lanes]

    prev_word = None
    for w in sorted_row:
        natural_lane = assign_word_to_lane(w, lanes)
        if natural_lane is None:
            prev_word = w
            continue

        if prev_word is not None:
            gap = w["x0"] - prev_word["x1"]
            if gap > GAP_THRESHOLD:
                prev_lane = assign_word_to_lane(prev_word, lanes)
                if prev_lane == natural_lane and natural_lane in lane_names:
                    idx = lane_names.index(natural_lane)
                    if idx + 1 < len(lane_names):
                        natural_lane = lane_names[idx + 1]

        buckets[natural_lane].append(w)
        prev_word = w

    return buckets


# =============================================================================
# LINE ITEM EXTRACTION
# =============================================================================

def extract_line_items(rows, header_idx: int, lanes: list, avg_char_width: float) -> list:
    items = []
    code_pat = re.compile(r'^[A-Z0-9]{3,15}$', re.IGNORECASE)
    detected_lane_names = {name for _, _, name in lanes}

    for row in rows[header_idx + 1:]:
        buckets = split_row_by_gaps(row, lanes, avg_char_width)

        row_data = {}
        for lane_name, ws in buckets.items():
            if not ws:
                continue
            ws_sorted = sorted(ws, key=lambda x: x["x0"])
            row_data[lane_name] = " ".join(w["text"] for w in ws_sorted).strip()

        if not row_data:
            continue

        joined = " ".join(row_data.values()).lower()
        if any(k in joined for k in ["total ht", "total ttc", "tva", "net à payer", "sous-total"]):
            break

        code  = row_data.get("code", "").strip()
        qty   = row_data.get("quantite", "").strip()
        desig = row_data.get("designation", "").strip()

        has_code = bool(code_pat.match(code)) if code else False
        has_qty  = bool(re.search(r'\d', qty)) if qty else False

        if not has_code and not has_qty and desig and items:
            if "designation" in items[-1]:
                items[-1]["designation"] = (items[-1]["designation"] + " " + desig).strip()
            continue

        if not (has_code or has_qty or desig):
            continue

        # Peel trailing standalone number from designation into quantity
        if "quantite" in detected_lane_names and not has_qty and desig:
            tail_m = re.search(r'\s+(\d{1,5})\s*$', desig)
            if tail_m:
                qty = tail_m.group(1)
                desig = desig[:tail_m.start()].strip()
                has_qty = True

        # Peel leading standalone number from designation into quantity
        if "quantite" in detected_lane_names and not has_qty and desig:
            head_m = re.match(r'^(\d{1,5})\s+(.+)', desig)
            if head_m:
                candidate = int(head_m.group(1))
                if 1 <= candidate <= 99999:
                    qty = head_m.group(1)
                    desig = head_m.group(2).strip()
                    has_qty = True

        item = {}
        if "code" in detected_lane_names:
            item["code"] = code
        if "quantite" in detected_lane_names:
            item["quantite"] = _clean_qty(qty)
        if "designation" in detected_lane_names:
            item["designation"] = desig
        if "prix_unit" in detected_lane_names and row_data.get("prix_unit"):
            item["prix_unitaire"] = row_data["prix_unit"]
        if "montant" in detected_lane_names and row_data.get("montant"):
            item["montant"] = row_data["montant"]

        items.append(item)

    return items


def _clean_qty(s: str) -> str:
    if not s:
        return ""
    m = re.search(r'\d+(?:[.,]\d+)?', s)
    return m.group(0) if m else s


# =============================================================================
# DOC TYPE & DOC NUMBER
# =============================================================================

def extract_doc_type_and_title_word(words, page_height: float):
    top_zone = [w for w in words if w["cy"] < page_height * 0.30]
    rows = group_words_into_rows(top_zone, y_tolerance=5)
    for row in rows:
        for span_len in (3, 2, 1):
            for i in range(len(row) - span_len + 1):
                span_words = row[i:i + span_len]
                text = " ".join(w["text"] for w in span_words).lower().strip(" .:")
                for dtype, keywords in DOC_TYPE_KEYWORDS.items():
                    if any(kw in text for kw in keywords):
                        anchor = {
                            "x0": span_words[0]["x0"],
                            "x1": span_words[-1]["x1"],
                            "top": min(w["top"] for w in span_words),
                            "bottom": max(w["bottom"] for w in span_words),
                            "cx": sum(w["cx"] for w in span_words) / span_len,
                            "cy": sum(w["cy"] for w in span_words) / span_len,
                        }
                        return dtype, anchor
    return None, None


def extract_document_number(words, title_anchor, page_width: float) -> Optional[str]:
    TRIGGER_KEYWORDS = [
        "bon de commande", "bon de livraison", "facture", "invoice",
        "proforma", "avoir", "n°", "no.", "no:", "reference", "référence", "ref",
    ]

    PRIORITY_PATTERNS = [
        r'\b(\d{3,6}/\d{2,4})\b',
        r'\b([A-Z]{2,5}-\d{2,6}/\d{2,4})\b',
        r'\b([A-Z]{2,5}-\d{2,6})\b',
        r'\b([A-Z]{2,5}\d{2,6})\b',
        r'\b(\d{5,8})\b',
    ]

    def _try_patterns(text: str) -> Optional[str]:
        for pat in PRIORITY_PATTERNS:
            m = re.search(pat, text)
            if m:
                val = m.group(1)
                if re.fullmatch(r'\d{4}', val) and 1900 <= int(val) <= 2100:
                    continue
                return val
        return None

    triggers = []
    for i, w in enumerate(words):
        wt = w["text"].lower().strip(" .:")
        if wt in ("n°", "no", "no.", "no:", "ref", "référence", "reference"):
            triggers.append(w)
        for span in (2, 3):
            if i + span <= len(words):
                phrase = " ".join(words[i+k]["text"].lower() for k in range(span))
                if any(kw in phrase for kw in TRIGGER_KEYWORDS):
                    triggers.append(words[i + span - 1])
                    break

    for trig in triggers:
        nearby = []
        for w in words:
            if w is trig:
                continue
            dx = w["x0"] - trig["x1"]
            dy = w["top"] - trig["bottom"]
            same_row = abs(w["cy"] - trig["cy"]) < 10 and 0 <= dx < 200
            below = 0 <= dy < 50 and abs(w["cx"] - trig["cx"]) < 100
            if same_row or below:
                dist = (dx if same_row else 0) + (dy if below else 0)
                nearby.append((dist, w))
        nearby.sort(key=lambda t: t[0])
        for _, w in nearby[:5]:
            val = _try_patterns(w["text"])
            if val:
                return val

    if title_anchor is not None:
        below = [
            w for w in words
            if w["top"] > title_anchor["bottom"]
            and w["top"] - title_anchor["bottom"] < 150
            and abs(w["cx"] - title_anchor["cx"]) < 200
        ]
        below.sort(key=lambda w: (w["top"], w["x0"]))
        for w in below:
            val = _try_patterns(w["text"])
            if val:
                return val

    return None


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def extract_invoice_data(pdf_path: str, page_index: int = 0) -> dict:
    words, page_w, page_h, source, pil_image = extract_words(pdf_path, page_index)
    if not words:
        return {"header": {}, "lignes_facture": [], "_source": source,
                "_error": "no words extracted"}

    avg_char_width = estimate_avg_char_width(words)
    rows = group_words_into_rows(words, y_tolerance=5)

    doc_type, title_anchor = extract_doc_type_and_title_word(words, page_h)
    doc_num = extract_document_number(words, title_anchor, page_w)
    mf = extract_mf(pil_image)  # ← uses your engine

    header_idx, header_hits = detect_header_row(rows)
    line_items = []
    lanes = []
    if header_idx is not None:
        lanes = build_lanes(header_hits, page_w)
        line_items = extract_line_items(rows, header_idx, lanes, avg_char_width)

    return {
        "header": {
            "matricule_fiscale": mf,
            "document_number":   doc_num,
            "type":              doc_type,
        },
        "lignes_facture": line_items,
        "_meta": {
            "source":         source,
            "page_size":      [page_w, page_h],
            "header_row_idx": header_idx,
            "lanes_detected": [name for _, _, name in lanes],
            "avg_char_width": round(avg_char_width, 2),
        },
    }


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python invoice_extractor_universal.py <pdf_path> [page]")
        sys.exit(1)
    pdf = sys.argv[1]
    page = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    result = extract_invoice_data(pdf, page)
    print(json.dumps(result, indent=2, ensure_ascii=False))