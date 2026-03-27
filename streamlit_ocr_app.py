"""
Invoice OCR Pipeline — Streamlit App
Integrates: invoice_extractor.py preprocessing + pdfplumber tables + regex extraction
"""

import streamlit as st
import cv2
import numpy as np
import pytesseract
import pdfplumber
import fitz
import re
import json
import tempfile
import os
from pathlib import Path
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ═══════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Invoice OCR Pipeline",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Syne', sans-serif;
    }
    code, .stCode, pre {
        font-family: 'JetBrains Mono', monospace !important;
    }

    .stApp { background: #0f1117; color: #e8e8e2; }

    h1 { font-family: 'Syne', sans-serif; font-weight: 700;
         letter-spacing: -1px; color: #f0f0ea; }
    h2, h3 { font-family: 'Syne', sans-serif; font-weight: 600; color: #d4d4ce; }

    .metric-card {
        background: #1a1d26; border: 1px solid #2a2d3a;
        border-radius: 8px; padding: 16px 20px; margin: 6px 0;
    }
    .metric-label { font-size: 11px; color: #666; text-transform: uppercase;
                    letter-spacing: 1px; margin-bottom: 4px; }
    .metric-value { font-family: 'JetBrains Mono'; font-size: 18px;
                    font-weight: 600; color: #7ee8a2; }

    .field-row { display: flex; gap: 12px; margin: 4px 0; }
    .field-key { font-family: 'JetBrains Mono'; font-size: 12px;
                 color: #888; min-width: 160px; }
    .field-val { font-family: 'JetBrains Mono'; font-size: 12px; color: #e8e8e2; }

    .tag-bc { background: #1a3a2a; color: #7ee8a2; padding: 2px 10px;
              border-radius: 12px; font-size: 11px; border: 1px solid #2a5a3a; }
    .tag-proforma { background: #1a2a3a; color: #7ec8e8; padding: 2px 10px;
                    border-radius: 12px; font-size: 11px; border: 1px solid #2a4a5a; }
    .tag-facture { background: #3a2a1a; color: #e8c87e; padding: 2px 10px;
                   border-radius: 12px; font-size: 11px; border: 1px solid #5a4a2a; }
    .tag-stat { background: #2a1a3a; color: #c87ee8; padding: 2px 10px;
                border-radius: 12px; font-size: 11px; border: 1px solid #4a2a5a; }

    .step-badge { background: #2a2d3a; color: #7ee8a2;
                  font-family: 'JetBrains Mono'; font-size: 11px;
                  padding: 2px 8px; border-radius: 4px; margin-right: 8px; }

    div[data-testid="stSidebar"] { background: #13151f; border-right: 1px solid #1e2130; }

    .stButton > button {
        background: #7ee8a2; color: #0f1117; border: none;
        font-family: 'Syne'; font-weight: 700; letter-spacing: 0.5px;
        padding: 10px 28px; border-radius: 6px; width: 100%;
        transition: all 0.2s;
    }
    .stButton > button:hover { background: #a0f0b8; transform: translateY(-1px); }

    .raw-text { background: #1a1d26; border: 1px solid #2a2d3a; border-radius: 8px;
                padding: 16px; font-family: 'JetBrains Mono'; font-size: 11px;
                color: #b0b0a8; max-height: 400px; overflow-y: auto; white-space: pre-wrap; }

    .table-container { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 12px;
            font-family: 'JetBrains Mono'; }
    th { background: #1e2130; color: #7ee8a2; padding: 8px 12px;
         text-align: left; border-bottom: 1px solid #2a2d3a; font-weight: 600; }
    td { padding: 7px 12px; border-bottom: 1px solid #1e2130;
         color: #c8c8c2; vertical-align: top; }
    tr:hover td { background: #1a1d26; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# PREPROCESSING — from invoice_extractor.py (best version)
# ═══════════════════════════════════════════════════════════════════════════

def fix_rotation(img_bgr: np.ndarray) -> np.ndarray:
    """Stage 1: OSD for 90/180/270 flips. Stage 2: fine skew via Hough lines."""
    try:
        gray_temp = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(
            gray_temp, config="--psm 0 -c min_characters_to_try=5"
        )
        angle_m = re.search(r"Rotate: (\d+)", osd)
        conf_m  = re.search(r"Orientation confidence: ([\d\.]+)", osd)
        confidence = float(conf_m.group(1)) if conf_m else 0.0
        if angle_m and confidence >= 2.0:
            a = int(angle_m.group(1))
            if a == 90:    img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif a == 180: img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_180)
            elif a == 270: img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    except Exception:
        pass

    # Fine skew correction using Hough lines — handles angles from 0.05° to 10°
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    try:
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                                minLineLength=img_bgr.shape[1] // 4,
                                maxLineGap=20)
        if lines is not None and len(lines) >= 3:
            angles = []
            for ln in lines:
                x1, y1, x2, y2 = ln[0]
                if x2 != x1:
                    a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                    if abs(a) < 15:          # only near-horizontal lines
                        angles.append(a)
            if len(angles) >= 3:
                median_angle = float(np.median(angles))
                if 0.05 <= abs(median_angle) <= 10.0:
                    h, w = img_bgr.shape[:2]
                    M = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
                    img_bgr = cv2.warpAffine(img_bgr, M, (w, h),
                                             flags=cv2.INTER_CUBIC,
                                             borderMode=cv2.BORDER_REPLICATE)
    except Exception:
        pass
    return img_bgr


def erase_colored_ink(img_bgr: np.ndarray) -> np.ndarray:
    """Fade colored ink to gray, keep dark digits inside colored regions.
    Additionally, darken digits/numbers inside circled or highlighted regions
    so they remain readable after blob-filter processing."""
    hsv    = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    result = img_bgr.copy()

    # --- standard colored-ink erasure ---
    color_mask = cv2.inRange(hsv, np.array([0, 25, 40]), np.array([180, 255, 255]))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    color_mask = cv2.dilate(color_mask, k, iterations=1)
    dark = (gray < 100)
    result[(color_mask > 0) & ~dark] = [230, 230, 230]
    result[(color_mask > 0) &  dark] = [0, 0, 0]

    # --- darken circled / highlighted numbers ---
    # Build a foreground (colored-blob) mask and find circular/oval contours
    try:
        fg = cv2.inRange(hsv, np.array([0, 40, 80]), np.array([180, 255, 255]))
        # Remove tiny specks
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        # Close gaps inside circles
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 50 or area > 30000:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / (h + 1e-5)
            # A circle or oval has aspect ratio near 1 and circularity > 0.4
            peri = cv2.arcLength(cnt, True)
            circularity = 4 * np.pi * area / (peri * peri + 1e-5)
            is_circle = (0.4 <= aspect <= 2.5) and (circularity > 0.35)
            # Highlighted rectangles: wider aspect, high saturation fill
            is_highlight = (aspect > 1.5) and (w > 10) and (h < 60)
            if is_circle or is_highlight:
                pad = 4
                rx1, ry1 = max(0, x - pad), max(0, y - pad)
                rx2, ry2 = min(result.shape[1], x + w + pad), min(result.shape[0], y + h + pad)
                roi_gray = gray[ry1:ry2, rx1:rx2]
                # threshold to get dark pixels (digits inside the circle)
                _, dark_px = cv2.threshold(roi_gray, 0, 255,
                                           cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                # Darken only those pixels extremely (set to pure black)
                roi = result[ry1:ry2, rx1:rx2]
                roi[dark_px > 0] = [0, 0, 0]
                result[ry1:ry2, rx1:rx2] = roi
    except Exception:
        pass

    return result


def binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, blockSize=25, C=8
    )


def remove_long_lines(binary: np.ndarray) -> np.ndarray:
    """Remove table borders > 80px. Protect text blobs from deletion."""
    inverted = cv2.bitwise_not(binary)
    h_k = cv2.getStructuringElement(cv2.MORPH_RECT, (80, 1))
    v_k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 80))
    lines_mask = cv2.add(
        cv2.morphologyEx(inverted, cv2.MORPH_OPEN, h_k),
        cv2.morphologyEx(inverted, cv2.MORPH_OPEN, v_k)
    )
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(inverted, 8)
    text_protect = np.zeros_like(binary)
    for i in range(1, num_labels):
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        ar = stats[i, cv2.CC_STAT_AREA]
        if 5 <= bw <= 120 and 5 <= bh <= 120 and 20 <= ar <= 8000:
            text_protect[labels == i] = 255
    pk = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
    text_protect = cv2.dilate(text_protect, pk, iterations=1)
    safe = cv2.bitwise_and(lines_mask, cv2.bitwise_not(text_protect))
    inverted[safe > 0] = 0
    return cv2.bitwise_not(inverted)


def stroke_cv(blob: np.ndarray) -> float:
    ek = cv2.getStructuringElement(cv2.MORPH_CROSS, (3,3))
    cur, counts = blob.copy(), []
    for _ in range(15):
        cur = cv2.erode(cur, ek)
        n = cv2.countNonZero(cur)
        counts.append(n)
        if n == 0: break
    if len(counts) < 2: return 999.0
    nz = np.array(counts, dtype=float)
    nz = nz[nz > 0]
    return float(np.std(nz) / (np.mean(nz) + 1e-5)) if len(nz) else 999.0


def build_keep_mask(binary: np.ndarray) -> np.ndarray:
    inverted = cv2.bitwise_not(binary)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(inverted, 8)
    keep_mask = np.zeros_like(binary)
    for i in range(1, num_labels):
        bx = stats[i, cv2.CC_STAT_LEFT];  by = stats[i, cv2.CC_STAT_TOP]
        bw = stats[i, cv2.CC_STAT_WIDTH]; bh = stats[i, cv2.CC_STAT_HEIGHT]
        area = stats[i, cv2.CC_STAT_AREA]
        aspect = max(bw,bh) / (min(bw,bh) + 1e-5)
        if area < 15 or area > 15000: continue
        if aspect > 20 and area > 200: continue
        if area < 80:   keep_mask[labels==i] = 255; continue
        if area > 3000:
            if area / (bw*bh + 1e-5) > 0.15: keep_mask[labels==i] = 255
            continue
        if area / (bw*bh + 1e-5) < 0.12: continue
        blob = (labels[by:by+bh, bx:bx+bw] == i).astype(np.uint8)*255
        if stroke_cv(blob) < 1.5: keep_mask[labels==i] = 255
    return keep_mask


def enhance_kept_text(binary: np.ndarray, keep_mask: np.ndarray) -> np.ndarray:
    ek = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
    km = cv2.dilate(keep_mask, ek, iterations=1)
    result = np.full_like(binary, 255)
    result[km > 0] = 0
    return result


def full_preprocess(img_bgr: np.ndarray) -> np.ndarray:
    img_bgr = fix_rotation(img_bgr)
    img_bgr = erase_colored_ink(img_bgr)
    gray    = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    binary  = binarize(gray)
    binary  = remove_long_lines(binary)
    return enhance_kept_text(binary, build_keep_mask(binary))


# ═══════════════════════════════════════════════════════════════════════════
# OCR FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def ocr_full_page(clean_img: np.ndarray) -> str:
    """Standard full-page OCR — LSTM engine, French+English."""
    return pytesseract.image_to_string(
        clean_img, lang="fra+eng", config="--psm 6 --oem 1"
    ).strip()


def ocr_header_zone(clean_img: np.ndarray) -> str:
    """
    OCR the top 40% of the image (header zone).
    Runs three PSM passes and returns the longest result for best coverage
    of company name, address, phone, email, fax, RC, MF, etc.
    """
    h = clean_img.shape[0]
    header_zone = clean_img[:int(h * 0.40), :]
    results = []
    for psm in ("4", "6", "3"):
        try:
            t = pytesseract.image_to_string(
                header_zone, lang="fra+eng",
                config=f"--psm {psm} --oem 1"
            ).strip()
            results.append(t)
        except Exception:
            pass
    # pick the result with most characters (most complete)
    return max(results, key=len) if results else ""


def ocr_body_zone(clean_img: np.ndarray) -> str:
    """
    OCR the body (38%-92% of image height) — the table area.
    Uses --psm 6 (uniform block) which is best for tables.
    """
    h = clean_img.shape[0]
    body_zone = clean_img[int(h * 0.38):int(h * 0.92), :]
    return pytesseract.image_to_string(
        body_zone, lang="fra+eng", config="--psm 6 --oem 1"
    ).strip()


def clean_ocr_text(text: str) -> str:
    """Post-process OCR output: fix common character confusions."""
    # Remove (cid:XX) native PDF artifacts
    text = re.sub(r'\(cid:\d+\)', '', text)
    # Collapse spaced uppercase letters "O M N I" → "OMNI"
    text = re.sub(r'(?<!\w)([A-Z] ){3,}([A-Z])(?!\w)',
                  lambda m: m.group(0).replace(' ', ''), text)
    text = re.sub(r'(?<!\w)((?:[A-Z0-9] ){4,}[A-Z0-9])(?!\w)',
                  lambda m: m.group(0).replace(' ', ''), text)
    # Fix l/I between digits → 1
    text = re.sub(r'(?<=\d)l(?=\d)', '1', text)
    text = re.sub(r'(?<=\d)I(?=\d)', '1', text)
    # Fix O between digits → 0
    text = re.sub(r'(?<=\d)O(?=\d)', '0', text)
    text = re.sub(r'(?<=\d)o(?=\d)', '0', text)
    # Fix degree sign used as 0
    text = re.sub(r'(\d)°o', r'\g<1>0', text)
    text = re.sub(r'(\d)°(?=\d)', r'\g<1>0', text)
    # Fix S→5 or 5→S confusion between digits
    text = re.sub(r'(?<=\d)S(?=\d)', '5', text)
    # Fix B→8 between digits
    text = re.sub(r'(?<=\d)B(?=\d)', '8', text)
    # Fix Z→2 between digits
    text = re.sub(r'(?<=\d)Z(?=\d)', '2', text)
    # Fix G→6 between digits
    text = re.sub(r'(?<=\d)G(?=\d)', '6', text)
    # Remove stray border pipes
    text = re.sub(r'(?<=[A-Za-z0-9])\|(?=[A-Za-z0-9])', ' ', text)
    text = re.sub(r'^\s*\|\s*$', '', text, flags=re.MULTILINE)
    # Title restorations
    text = re.sub(r'(?i)\b(on de commande)\b', 'Bon de commande', text)
    text = re.sub(r'(?i)\b(on de livraison)\b', 'Bon de livraison', text)
    # Normalize common field labels so regex can find them
    text = re.sub(r'(?i)\bM\.?F\.?\b', 'M.F.', text)
    text = re.sub(r'(?i)\bB[-.]?C\.?\b(?=\s*[:\-N°])', 'Bon de commande', text)
    text = re.sub(r'(?i)\bT\.?E\.?L\.?\b(?=\s*[:\-])', 'Tel:', text)
    text = re.sub(r'(?i)\bAdd\.?\s*:', 'Adresse:', text)
    # Clean noise
    text = re.sub(r'[=~_—]{2,}', ' ', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # Remove garbage lines: must have ≥3 alphanum chars AND word/number
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s: lines.append(''); continue
        alnum = len(re.findall(r'[A-Za-z0-9]', s))
        total = len(s)
        if alnum < 3: continue
        if 1 - alnum/(total+1e-5) > 0.60: continue
        if not re.search(r'[A-Za-z]{3,}|\d', s): continue
        lines.append(s)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# TABLE EXTRACTION — pdfplumber (for native PDFs)
# ═══════════════════════════════════════════════════════════════════════════

def extract_tables_pdfplumber(pdf_path: str) -> list:
    """
    Uses pdfplumber to extract structured tables from native PDFs.
    Tries "lines" strategy first; falls back to "text" strategy.
    On each page, tables are sorted top-to-bottom / left-to-right so the
    main product table (which always starts at the top-left of the data area)
    appears first.  All rows (including header) are preserved; only fully
    blank rows are dropped.
    """
    all_tables = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # ── Strategy 1: explicit drawn lines ────────────────────────────
            raw_tables = page.find_tables({
                "vertical_strategy":      "lines",
                "horizontal_strategy":    "lines",
                "intersection_tolerance": 5,
                "snap_tolerance":         4,
                "join_tolerance":         4,
            })
            # ── Strategy 2: text alignment ───────────────────────────────────
            if not raw_tables:
                raw_tables = page.find_tables({
                    "vertical_strategy":      "text",
                    "horizontal_strategy":    "text",
                    "intersection_tolerance": 10,
                })

            if not raw_tables:
                continue

            # Sort tables top→bottom then left→right so we always start
            # from the first (header) table at the top-left of the page.
            raw_tables = sorted(raw_tables,
                                key=lambda t: (t.bbox[1], t.bbox[0]))  # (top, left)

            for tbl_obj in raw_tables:
                table = tbl_obj.extract()
                if not table:
                    continue

                # Consistent column count = widest row
                ncols = max(len(row) for row in table)
                clean = []
                for row in table:
                    padded = list(row) + [''] * (ncols - len(row))
                    r = [str(cell or '').strip() for cell in padded]
                    # Only skip rows where every cell is empty
                    if not any(c for c in r):
                        continue
                    clean.append(r)

                if clean:
                    all_tables.append(clean)

    return all_tables


def detect_pdf_native(pdf_path: str) -> bool:
    """Check if PDF has a real text layer (native) or is scanned."""
    with pdfplumber.open(pdf_path) as pdf:
        total = sum(len((p.extract_text() or '').strip()) for p in pdf.pages)
    return total > 100


# ═══════════════════════════════════════════════════════════════════════════
# REGEX EXTRACTION — structured fields from OCR text
# ═══════════════════════════════════════════════════════════════════════════

DOC_TYPES = {
    "Proforma":            ["proforma", "b.c. interne", "incoterms", "date/heure livraison"],
    "Bon de Commande":     ["bon de commande", "commande fournisseur", "bcn-", "bc n°",
                            "b-c", "b.c.", "bdc"],
    "Facture":             ["facture", "invoice", "facture numéro", "facture n°"],
    "Statistiques":        ["statistique", "quantitatif des ventes", "stat. ventes",
                            "quantité proposée", "moyenne des ventes"],
    "Chiffre d'Affaires":  ["chiffre d'affaire", "ventes et chiffre"],
    "Bon de Livraison":    ["bon de livraison", "bdl", "livraison n°"],
    "Avoir":               ["avoir", "note de crédit", "note de credit"],
}

def detect_doc_type(text: str) -> str:
    tl = text.lower()
    for dtype, keywords in DOC_TYPES.items():
        if any(kw in tl for kw in keywords):
            return dtype
    return "Document"


def extract_info(text: str) -> dict:
    """Extract structured fields using regex on the full OCR text.
    Handles many abbreviations: MF, M.F, B-C, BC, Add, Tel, TEL, Email, etc."""
    info = {}

    # Document type
    info["type"] = detect_doc_type(text)

    # Document number — try most specific first
    for pattern in [
        r'PROFORMA\s+N[°o][:\s]*([A-Z0-9\-]{6,25})',
        r'Commande\s+(?:Fournisseur\s+)?N[°o][:\s]*(\d{4,10})',
        r'N[°o]\s*Facture[:\s]*([A-Z0-9\-]{4,20})',
        r'Facture\s+num[eé]ro\s+([0-9\s]{3,15})',
        r'\b(BCN-\d{2}-\d{4})\b',
        r'\b(BCM?-\d{2}-\d{4})\b',
        r'Bon\s+de\s+commande\s+N[°o]?[:\s]*([\d/\-A-Z]{3,20})',
        r'N[°o][:\s]*([A-Z0-9\-]{4,20})',
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            num = re.sub(r'\s+', '', m.group(1)).strip('.,;:')
            if len(num) >= 3:
                info["numero"] = num
                break

    # Date  — prefer labelled date, then any DD/MM/YYYY
    m = re.search(r'(?:Date|Dat[ée]e?)[\s:/-]*?(\d{1,2}[/\-.\\]\d{1,2}[/\-.\\]\d{2,4})',
                  text, re.I)
    if not m:
        m = re.search(r'\b(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})\b', text)
    if m:
        info["date"] = m.group(1)

    # Matricule fiscal / MF — strict Tunisian format ONLY:
    #   NNNNNNN X / X / X / NNN   (6-7 digits, then 3 uppercase letters, then 3 digits)
    #   Separators between letters may be "/", "|", "\\", a space, or nothing at all.
    #   Examples: 1234567A/P/M/000  |  0012345APM000  |  1234567 A P M 000
    mf_label = (
        r'(?:'
        r'M\.?F\.?|Matr\.?\s*Fiscal|Matricule\s*Fiscal|'
        r'Code\s*TVA|N[°o]?\s*TVA|MFCOD|ID\s*Fiscal|Fiscal\s*N[°o]?'
        r')'
    )
    # sep = optional separator between the three letters
    _sep = r'[/\\|\s]?'
    for pat in [
        # Labelled — spaces allowed inside the value
        mf_label + r'\s*[:\-]?\s*(\d{6,7}\s*[A-Z]' + _sep + r'[A-Z]' + _sep + r'[A-Z]' + _sep + r'\d{3})\b',
        # Unlabelled — compact form (no surrounding spaces needed)
        r'\b(\d{6,7}[A-Z]' + _sep + r'[A-Z]' + _sep + r'[A-Z]' + _sep + r'\d{3})\b',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            val = m.group(1).strip()
            # Normalise to canonical X/X/X form
            val = re.sub(r'[ \t]', '', val).replace('\\', '/').replace('|', '/')
            # Must match the exact digit-letter-digit structure after compaction
            if re.fullmatch(r'\d{6,7}[A-Z]/?[A-Z]/?[A-Z]/?\d{3}', val, re.I):
                info["matricule_fiscal"] = val
                break

    # Telephone / Tel — many label variants
    tel_label = r'(?:T[eé]l[eé]?phone?|T[eé]l|TEL|T\.E\.L|Tél|Portable|Mobile|GSM|Phone)'
    m = re.search(tel_label + r'[:\s./]*([\d][\d\s.\-]{6,14}\d)', text, re.I)
    if not m:
        # grab any 8-10 digit phone-like number
        m = re.search(r'(?i)(?:tél|tel|phone)\s*[:\-]?\s*([+\d][\d\s.\-]{7,15})', text)
    if m:
        info["tel"] = re.sub(r'[\s.\-]', '', m.group(1))

    # Fax
    m = re.search(r'(?:Fax|FAX)[:\s./]*([\d][\d\s.\-]{6,14}\d)', text, re.I)
    if m:
        info["fax"] = re.sub(r'[\s.\-]', '', m.group(1))

    # Email — standard pattern, also after "Email:", "E-mail:", "Mail:"
    m = re.search(r'(?:E[-\s]?mail|Email|Mail|Courriel)?\s*[:\-]?\s*([\w.+\-]+@[\w.\-]+\.[a-z]{2,6})',
                  text, re.I)
    if m:
        info["email"] = m.group(1)

    # Address / Adresse / Add  — labelled form
    m = re.search(r'(?:Adresse|Address|Add\.?|Adr\.?)[:\s]*(.+?)(?:\n|Tel|T[eé]l|M\.?F|Fax|Email|RC\b|$)',
                  text, re.I | re.DOTALL)
    if m:
        addr = re.sub(r'\s+', ' ', m.group(1)).strip().rstrip('.,;')
        if len(addr) >= 5:
            info["adresse"] = addr

    # Address — implicit (no label): detect lines containing street/location keywords
    if "adresse" not in info:
        # Keywords that strongly suggest a street address line
        street_kw = re.compile(
            r'\b(?:Rue|Route|Avenue|Av\.?|Bd\.?|Boulevard|Cité|Zone\s+(?:Ind(?:ustrielle)?|Commerciale)?'
            r'|Lotissement|Lot\.?\s|Quartier|Immeuble|Imm\.?|Résidence|Centre\s+Urbain'
            r'|BP\s*\d|Km\s*\d|N°\s*\d|Bloc|Sis\b|Siège)'
            r'',
            re.IGNORECASE
        )
        # Walk through lines; join consecutive address-like lines (max 2)
        text_lines = text.splitlines()
        for li, line in enumerate(text_lines):
            stripped = line.strip()
            if not stripped or len(stripped) < 5:
                continue
            if street_kw.search(stripped):
                # Try to grab this line + optionally the next non-empty line
                parts = [stripped]
                for nxt in text_lines[li + 1: li + 3]:
                    ns = nxt.strip()
                    # Stop if next line looks like a field label
                    if re.match(r'(?:Tel|T[eé]l|Fax|Email|M\.?F|RC|Matricule)', ns, re.I):
                        break
                    if ns and len(ns) >= 4 and not re.search(r'(?:facture|commande|proforma|livraison)', ns, re.I):
                        parts.append(ns)
                        break
                candidate = ', '.join(parts)
                if len(candidate) >= 8:
                    info["adresse"] = candidate
                break

    # RC
    m = re.search(r'R\.?C\.?\s*[:\-]?\s*([A-Z][A-Z0-9]{5,14})', text, re.I)
    if m:
        info["rc"] = m.group(1)

    # Totals
    for field, keywords in {
        "total_ht":  ["total ht", "total hors taxe", "montant ht", "total net ht"],
        "tva":       [" tva ", "t.v.a", "valeur tva"],
        "total_ttc": ["total ttc", "net à payer", "montant ttc"],
    }.items():
        for kw in keywords:
            idx = (" " + text.lower() + " ").find(kw)
            if idx >= 0:
                # look for numbers after the keyword
                snippet = text[max(0, idx - 1):idx + len(kw) + 80]
                nums = re.findall(r'\d[\d,.\s]{0,15}\d|\b\d{1,8}\b', snippet)
                if nums:
                    val = _to_float(nums[-1])
                    if val and 0.01 < val < 50_000_000:
                        info[field] = val
                break

    return {k: v for k, v in info.items() if v}


def _to_float(s) -> float | None:
    if not s: return None
    s = str(s).strip()
    s = re.sub(r'[^\d,.]','', s)
    if not s: return None
    if ',' in s and '.' in s:
        s = s.replace(',','') if s.rfind('.')>s.rfind(',') else s.replace('.','').replace(',','.')
    elif ',' in s:
        parts = s.split(',')
        s = s.replace(',','.') if len(parts)==2 and len(parts[1])<=3 else s.replace(',','')
    try: return round(float(s), 3)
    except: return None


def extract_product_lines(text: str) -> list[dict]:
    """
    Extract product line items from OCR text using regex.
    Looks for lines starting with a 6-digit code (or PF/PH prefix).
    Returns list of dicts with code, designation, quantity (when found).
    """
    items = []
    seen  = set()

    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 10: continue

        # Pattern: 6-digit code OR alphanumeric code (PF/PH prefix)
        m = re.match(
            r'^(\d{6}|[A-Z]{2}\d{5,10}|[A-Z]{3}\d{3,8})\s+'  # code
            r'(.{5,60?}?)\s+'                                    # designation (lazy)
            r'(\d{1,5}(?:[,.]\d+)?)\s*$',                       # quantity at end
            line
        )
        if not m:
            # Try without quantity
            m2 = re.match(
                r'^(\d{6}|[A-Z]{2}\d{5,10})\s+(.{5,70})',
                line
            )
            if m2:
                code = m2.group(1)
                desc = m2.group(2).strip()
                # Try to find a number at the end of desc
                num_m = re.search(r'\b(\d{1,5})\s*$', desc)
                qty   = None
                if num_m:
                    v = int(num_m.group(1))
                    if 1 <= v <= 99999:
                        qty  = float(v)
                        desc = desc[:num_m.start()].strip()
                if code not in seen and len(desc) >= 4:
                    seen.add(code)
                    item = {"code": code, "designation": desc}
                    if qty: item["quantite"] = qty
                    items.append(item)
        else:
            code = m.group(1)
            desc = m.group(2).strip()
            qty_s = m.group(3)
            qty = _to_float(qty_s)
            if code not in seen and len(desc) >= 4:
                seen.add(code)
                item = {"code": code, "designation": desc}
                if qty and 1 <= qty <= 99999: item["quantite"] = qty
                items.append(item)

    return items


# ═══════════════════════════════════════════════════════════════════════════
# PDF → IMAGE
# ═══════════════════════════════════════════════════════════════════════════

def pdf_page_to_image(pdf_path: str, page_index: int, dpi: int = 300) -> np.ndarray:
    """Render a PDF page to a high-resolution image for OCR."""
    doc  = fitz.open(pdf_path)
    page = doc[page_index]
    mat  = fitz.Matrix(dpi/72, dpi/72)   # 300 DPI for best OCR quality
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    img  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⚙️ Options")
    st.markdown("---")

    st.markdown("**Preprocessing**")
    use_fix_rotation  = st.checkbox("Fix Rotation",      value=True)
    use_erase_color   = st.checkbox("Erase Colored Ink", value=True)
    use_remove_lines  = st.checkbox("Remove Borders",    value=True)
    use_keep_mask     = st.checkbox("Blob Filter (CV)",  value=True)

    st.markdown("---")
    st.markdown("**OCR**")
    split_zones = st.checkbox("Split Header / Body OCR", value=True,
        help="Uses different Tesseract configs for header vs table area")
    show_raw    = st.checkbox("Show Raw OCR Text",       value=False)

    st.markdown("---")
    st.markdown("**Output**")
    show_tables   = st.checkbox("Show pdfplumber Tables", value=True)
    show_products = st.checkbox("Show Product Lines",     value=True)
    show_json     = st.checkbox("Show Full JSON",         value=False)

    st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN UI
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("# 🔬 Invoice OCR Pipeline")
st.markdown("*Preprocessing → OCR → Table extraction → Regex parsing*")
st.markdown("---")

uploaded = st.file_uploader(
    "Drop a PDF or image file",
    type=["pdf", "png", "jpg", "jpeg"],
    label_visibility="collapsed"
)

run_btn = st.button("▶  Run Pipeline", use_container_width=True)

if not uploaded:
    st.markdown("""
    <div style='text-align:center;padding:60px 0;color:#444;'>
        <div style='font-size:48px;margin-bottom:16px'>📄</div>
        <div style='font-size:14px'>Upload a PDF or image to begin</div>
        <div style='font-size:11px;color:#333;margin-top:8px'>
        Supports: Bon de Commande · Proforma · Facture · Statistiques
        </div>
    </div>
    """, unsafe_allow_html=True)

if uploaded and run_btn:

    is_pdf = uploaded.type == "application/pdf"

    # Save to temp file (needed by fitz and pdfplumber)
    suffix = ".pdf" if is_pdf else Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    # ── Detect PDF type ────────────────────────────────────────────────
    if is_pdf:
        is_native = detect_pdf_native(tmp_path)
        doc_fitz  = fitz.open(tmp_path)
        total_pages = len(doc_fitz)

        col_type, col_pages = st.columns([2, 1])
        with col_type:
            color = "#7ee8a2" if is_native else "#e8c87e"
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>PDF type</div>
                <div class='metric-value' style='color:{color}'>
                    {"📄 Native (digital)" if is_native else "📷 Scanned (image-based)"}
                </div>
            </div>""", unsafe_allow_html=True)
        with col_pages:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>Pages</div>
                <div class='metric-value'>{total_pages}</div>
            </div>""", unsafe_allow_html=True)
    else:
        is_native = False
        total_pages = 1

    st.markdown("---")

    # ── Per-page preview: preprocess & display all pages ──────────────
    # We collect cleaned images here for display AND later reuse in OCR loop
    all_clean_imgs  = []   # list of preprocessed (binary) np arrays
    all_orig_imgs   = []   # list of original BGR np arrays

    if is_pdf:
        with st.spinner(f"Preprocessing all {total_pages} pages for preview..."):
            for pg_i in range(total_pages):
                pg_img = pdf_page_to_image(tmp_path, pg_i, dpi=300)
                all_orig_imgs.append(pg_img)
                w = pg_img.copy()
                if use_fix_rotation: w = fix_rotation(w)
                if use_erase_color:  w = erase_colored_ink(w)
                g = cv2.cvtColor(w, cv2.COLOR_BGR2GRAY)
                b = binarize(g)
                if use_remove_lines: b = remove_long_lines(b)
                if use_keep_mask:
                    c_pg = enhance_kept_text(b, build_keep_mask(b))
                else:
                    c_pg = b
                all_clean_imgs.append(c_pg)
    else:
        file_bytes = np.frombuffer(uploaded.getvalue(), dtype=np.uint8)
        img_bgr    = cv2.imdecode(file_bytes, 1)
        all_orig_imgs.append(img_bgr)
        w = img_bgr.copy()
        if use_fix_rotation: w = fix_rotation(w)
        if use_erase_color:  w = erase_colored_ink(w)
        g = cv2.cvtColor(w, cv2.COLOR_BGR2GRAY)
        b = binarize(g)
        if use_remove_lines: b = remove_long_lines(b)
        if use_keep_mask:
            c_pg = enhance_kept_text(b, build_keep_mask(b))
        else:
            c_pg = b
        all_clean_imgs.append(c_pg)

    # Show page tabs
    st.markdown("### 🖼️ Cleaned Pages Preview")
    if total_pages == 1:
        col_orig, col_clean = st.columns(2)
        with col_orig:
            st.markdown("**Original**")
            st.image(cv2.cvtColor(all_orig_imgs[0], cv2.COLOR_BGR2RGB),
                     use_container_width=True)
        with col_clean:
            st.markdown("**After Preprocessing**")
            st.image(all_clean_imgs[0], use_container_width=True)
    else:
        tab_labels = [f"Page {i+1}" for i in range(total_pages)]
        page_tabs  = st.tabs(tab_labels)
        for i, tab in enumerate(page_tabs):
            with tab:
                col_orig, col_clean = st.columns(2)
                with col_orig:
                    st.markdown("**Original**")
                    st.image(cv2.cvtColor(all_orig_imgs[i], cv2.COLOR_BGR2RGB),
                             use_container_width=True)
                with col_clean:
                    st.markdown("**After Preprocessing**")
                    st.image(all_clean_imgs[i], use_container_width=True)

    st.markdown("---")

    # ── OCR — reuse already-preprocessed images ──────────────────────
    all_header_texts = []
    all_body_texts   = []
    progress_bar = st.progress(0, text="Running OCR...")

    for pg_i, c_pg in enumerate(all_clean_imgs):
        progress_bar.progress(
            int((pg_i / len(all_clean_imgs)) * 100),
            text=f"OCR page {pg_i + 1}/{len(all_clean_imgs)}..."
        )
        if split_zones:
            all_header_texts.append(clean_ocr_text(ocr_header_zone(c_pg)))
            all_body_texts.append(clean_ocr_text(ocr_body_zone(c_pg)))
        else:
            ft = clean_ocr_text(ocr_full_page(c_pg))
            all_header_texts.append(ft)
            all_body_texts.append(ft)
    progress_bar.progress(100, text="Done!")

    header_text = "\n".join(all_header_texts)
    body_text   = "\n".join(all_body_texts)
    full_text   = header_text + "\n" + body_text

    # ── pdfplumber tables (native only) ───────────────────────────────
    plumber_tables = []
    if is_pdf and is_native and show_tables:
        with st.spinner("Extracting tables with pdfplumber..."):
            plumber_tables = extract_tables_pdfplumber(tmp_path)

    # ── Regex extraction ───────────────────────────────────────────────
    extracted_info  = extract_info(full_text)
    product_lines   = extract_product_lines(body_text) if show_products else []

    # ════════════════════════════════════════════════════════════════════
    # DISPLAY RESULTS
    # ════════════════════════════════════════════════════════════════════

    # Document type badge
    dtype = extracted_info.get("type", "Document")
    tag_class = {"Bon de Commande": "tag-bc", "Proforma": "tag-proforma",
                 "Facture": "tag-facture",
                 "Bon de Livraison": "tag-bc",
                 "Avoir": "tag-stat"}.get(dtype, "tag-stat")
    st.markdown(f"<span class='{tag_class}'>{dtype}</span>", unsafe_allow_html=True)
    st.markdown("## 📋 Extracted Information")

    # Info grid — include doc type as first card
    info_cols = st.columns(3)
    fields = [
        ("Document Type",    extracted_info.get("type",             "—")),
        ("Document N\u00b0",  extracted_info.get("numero",           "—")),
        ("Date",             extracted_info.get("date",             "—")),
        ("Matricule Fiscal", extracted_info.get("matricule_fiscal", "—")),
        ("T\u00e9l\u00e9phone", extracted_info.get("tel",            "—")),
        ("Fax",              extracted_info.get("fax",              "—")),
        ("Email",            extracted_info.get("email",            "—")),
        ("Adresse",          extracted_info.get("adresse",          "—")),
        ("RC",               extracted_info.get("rc",               "—")),
        ("Total HT",         extracted_info.get("total_ht",         "—")),
        ("Total TTC",        extracted_info.get("total_ttc",        "—")),
    ]
    for idx, (label, value) in enumerate(fields):
        with info_cols[idx % 3]:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>{label}</div>
                <div class='metric-value' style='font-size:14px'>{value}</div>
            </div>""", unsafe_allow_html=True)

    # ── Product lines ─────────────────────────────────────────────────
    if show_products and product_lines:
        st.markdown(f"## 📦 Product Lines ({len(product_lines)} items)")
        table_html = "<div class='table-container'><table><thead><tr>"
        table_html += "<th>#</th><th>Code</th><th>Designation</th><th>Quantity</th>"
        table_html += "</tr></thead><tbody>"
        for i, item in enumerate(product_lines, 1):
            qty = item.get("quantite", "—")
            qty_str = f"{qty:.0f}" if isinstance(qty, float) else str(qty)
            table_html += f"""<tr>
                <td style='color:#555'>{i}</td>
                <td style='color:#7ee8a2'>{item.get('code','')}</td>
                <td>{item.get('designation','')}</td>
                <td style='text-align:right;color:#e8c87e'>{qty_str}</td>
            </tr>"""
        table_html += "</tbody></table></div>"
        st.markdown(table_html, unsafe_allow_html=True)
    elif show_products:
        st.info("No product lines detected by regex. Check the raw OCR text below.")

    # ── pdfplumber tables ─────────────────────────────────────────────
    if plumber_tables:
        st.markdown(f"## 🗃️ pdfplumber Tables ({len(plumber_tables)} found)")
        for t_idx, table in enumerate(plumber_tables):
            if not table:
                continue
            headers = table[0]
            rows    = table[1:]
            # count non-empty data rows
            data_rows = [r for r in rows if any(str(c).strip() for c in r)]
            st.markdown(f"**Table {t_idx + 1}** — {len(data_rows)} rows")
            table_html = "<div class='table-container'><table><thead><tr>"
            for h in headers:
                safe_h = str(h).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                table_html += f"<th>{safe_h}</th>"
            table_html += "</tr></thead><tbody>"
            for row in data_rows:
                table_html += "<tr>"
                for cell in row:
                    safe_c = str(cell).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    table_html += f"<td>{safe_c}</td>"
                table_html += "</tr>"
            table_html += "</tbody></table></div>"
            st.markdown(table_html, unsafe_allow_html=True)
            st.markdown("")

    # ── Raw OCR text ──────────────────────────────────────────────────
    if show_raw:
        st.markdown("## 📝 Raw OCR Text")
        if split_zones:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Header zone**")
                st.markdown(f"<div class='raw-text'>{header_text}</div>",
                            unsafe_allow_html=True)
            with c2:
                st.markdown("**Body zone**")
                st.markdown(f"<div class='raw-text'>{body_text}</div>",
                            unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='raw-text'>{full_text}</div>",
                        unsafe_allow_html=True)

    # ── Full JSON ─────────────────────────────────────────────────────
    if show_json:
        result = {
            "informations_document": extracted_info,
            "ligne_articles": product_lines,
        }
        st.markdown("## 🗂️ Full JSON")
        st.json(result)

    # ── Download ───────────────────────────────────────────────────────
    st.markdown("---")
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        # Build tables payload: list of {headers, rows} dicts for readability
        tables_payload = []
        for tbl in plumber_tables:
            if tbl:
                tables_payload.append({
                    "headers": tbl[0],
                    "rows":    tbl[1:]
                })
        result_json = json.dumps({
            "informations_document": extracted_info,
            "ligne_articles":        product_lines,
            "tables_extraites":      tables_payload,
        }, ensure_ascii=False, indent=2)
        st.download_button(
            "⬇ Download JSON",
            data=result_json,
            file_name=f"{Path(uploaded.name).stem}_extracted.json",
            mime="application/json",
            use_container_width=True
        )
    with col_dl2:
        st.download_button(
            "⬇ Download OCR Text",
            data=full_text,
            file_name=f"{Path(uploaded.name).stem}_ocr.txt",
            mime="text/plain",
            use_container_width=True
        )

    # Cleanup temp file
    try: os.unlink(tmp_path)
    except: pass