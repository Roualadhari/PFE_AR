"""
Invoice OCR Pipeline — Streamlit App v3
Integrates: invoice_extractor.py preprocessing + pdfplumber tables + regex extraction

Changes v3:
  • All pages processed from page 1 onwards
  • Live pipeline log panel shows every step as it runs
  • Address extraction added
  • Document type shown in Extracted Information grid
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
import time as _time
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
    html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
    code, .stCode, pre { font-family: 'JetBrains Mono', monospace !important; }
    .stApp { background: #0f1117; color: #e8e8e2; }
    h1 { font-family: 'Syne'; font-weight: 700; letter-spacing: -1px; color: #f0f0ea; }
    h2, h3 { font-family: 'Syne'; font-weight: 600; color: #d4d4ce; }
    .metric-card { background: #1a1d26; border: 1px solid #2a2d3a; border-radius: 8px;
                   padding: 16px 20px; margin: 6px 0; }
    .metric-label { font-size: 11px; color: #666; text-transform: uppercase;
                    letter-spacing: 1px; margin-bottom: 4px; }
    .metric-value { font-family: 'JetBrains Mono'; font-size: 18px;
                    font-weight: 600; color: #7ee8a2; }
    .tag-bc       { background: #1a3a2a; color: #7ee8a2;  padding: 2px 10px;
                    border-radius: 12px; font-size: 11px; border: 1px solid #2a5a3a; }
    .tag-proforma { background: #1a2a3a; color: #7ec8e8;  padding: 2px 10px;
                    border-radius: 12px; font-size: 11px; border: 1px solid #2a4a5a; }
    .tag-facture  { background: #3a2a1a; color: #e8c87e;  padding: 2px 10px;
                    border-radius: 12px; font-size: 11px; border: 1px solid #5a4a2a; }
    .tag-stat     { background: #2a1a3a; color: #c87ee8;  padding: 2px 10px;
                    border-radius: 12px; font-size: 11px; border: 1px solid #4a2a5a; }
    div[data-testid="stSidebar"] { background: #13151f; border-right: 1px solid #1e2130; }
    .stButton > button { background: #7ee8a2; color: #0f1117; border: none;
                         font-family: 'Syne'; font-weight: 700; letter-spacing: 0.5px;
                         padding: 10px 28px; border-radius: 6px; width: 100%;
                         transition: all 0.2s; }
    .stButton > button:hover { background: #a0f0b8; transform: translateY(-1px); }
    .raw-text { background: #1a1d26; border: 1px solid #2a2d3a; border-radius: 8px;
                padding: 16px; font-family: 'JetBrains Mono'; font-size: 11px;
                color: #b0b0a8; max-height: 400px; overflow-y: auto; white-space: pre-wrap; }
    .table-container { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; font-family: 'JetBrains Mono'; }
    th { background: #1e2130; color: #7ee8a2; padding: 8px 12px;
         text-align: left; border-bottom: 1px solid #2a2d3a; font-weight: 600; }
    td { padding: 7px 12px; border-bottom: 1px solid #1e2130;
         color: #c8c8c2; vertical-align: top; }
    tr:hover td { background: #1a1d26; }
    .page-label { font-family: 'Syne'; font-size: 12px; color: #555;
                  text-transform: uppercase; letter-spacing: 1px; margin: 12px 0 4px 0; }

    /* ── Pipeline Log ─────────────────────────────── */
    .pl-wrap  { background: #0d0f17; border: 1px solid #1e2130; border-radius: 10px;
                padding: 14px 16px; margin-bottom: 12px; }
    .pl-title { font-family: 'Syne'; font-size: 11px; font-weight: 600; color: #555;
                text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 10px; }
    .pl-step  { display: flex; align-items: flex-start; gap: 10px;
                padding: 7px 0; border-bottom: 1px solid #141720; }
    .pl-step:last-child { border-bottom: none; }
    .pl-icon  { font-size: 13px; flex-shrink: 0; width: 18px; text-align: center; margin-top: 1px; }
    .pl-info  { flex: 1; min-width: 0; }
    .pl-name  { font-family: 'Syne'; font-size: 12px; }
    .pl-detail{ font-family: 'JetBrains Mono'; font-size: 10px; color: #445;
                margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .pl-time  { font-family: 'JetBrains Mono'; font-size: 10px; color: #445;
                flex-shrink: 0; padding-left: 8px; align-self: center; }
    .s-pending .pl-name { color: #383c50; }
    .s-running .pl-name { color: #7ee8a2; }
    .s-done    .pl-name { color: #c8c8c2; }
    .s-skip    .pl-name { color: #333849; font-style: italic; }
    .s-warn    .pl-name { color: #e8c87e; }
    .s-done    .pl-icon::after { content: ''; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE LOG — live step-by-step status panel
# ═══════════════════════════════════════════════════════════════════════════

_STEPS = [
    # (key,            icon, label)
    ("load",           "📂", "Load file"),
    ("detect",         "🔍", "Detect PDF type"),
    ("preprocess",     "🧹", "Preprocess image(s)"),
    ("ocr",            "🔤", "OCR text extraction"),
    ("pdfplumber",     "📊", "pdfplumber tables"),
    ("regex",          "🔎", "Regex field extraction"),
    ("products",       "📦", "Product line extraction"),
    ("done",           "✅", "Pipeline complete"),
]

def _log_init():
    st.session_state["_pl"] = {
        k: {"status": "pending", "detail": "", "t": ""}
        for k, *_ in _STEPS
    }

def _log_set(key, status, detail="", t0=0.0):
    if "_pl" not in st.session_state:
        _log_init()
    elapsed = ""
    if status == "done" and t0:
        ms = int((_time.time() - t0) * 1000)
        elapsed = f"{ms}ms" if ms < 1000 else f"{ms/1000:.1f}s"
    st.session_state["_pl"][key] = {"status": status, "detail": detail, "t": elapsed}

def _log_render(ph):
    """Re-render the pipeline log into Streamlit placeholder `ph`."""
    if "_pl" not in st.session_state:
        return
    pl = st.session_state["_pl"]
    icons = {"pending": "○", "running": "⏳", "done": "✓", "skip": "–", "warn": "⚠"}
    html = "<div class='pl-wrap'><div class='pl-title'>⚡ Pipeline</div>"
    for key, _, label in _STEPS:
        s   = pl.get(key, {"status": "pending", "detail": "", "t": ""})
        st_ = s["status"]
        html += (
            f"<div class='pl-step s-{st_}'>"
            f"<span class='pl-icon'>{icons.get(st_, '○')}</span>"
            f"<div class='pl-info'>"
            f"<div class='pl-name'>{label}</div>"
            + (f"<div class='pl-detail'>{s['detail']}</div>" if s['detail'] else "")
            + "</div>"
            + (f"<span class='pl-time'>{s['t']}</span>" if s['t'] else "")
            + "</div>"
        )
    html += "</div>"
    ph.markdown(html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# PREPROCESSING — from invoice_extractor.py (best version)
# ═══════════════════════════════════════════════════════════════════════════

def fix_rotation(img_bgr):
    try:
        gray_temp = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(gray_temp, config="--psm 0 -c min_characters_to_try=5")
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
    gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    coords = np.column_stack(np.where(gray < 200))
    if len(coords) >= 500:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45: angle = 90 + angle
        if 0.3 <= abs(angle) <= 3.0:
            h, w = gray.shape
            M = cv2.getRotationMatrix2D((w//2, h//2), angle, 1.0)
            img_bgr = cv2.warpAffine(img_bgr, M, (w, h),
                                     flags=cv2.INTER_CUBIC,
                                     borderMode=cv2.BORDER_REPLICATE)
    return img_bgr


def erase_colored_ink(img_bgr):
    hsv    = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    result = img_bgr.copy()
    color_mask = cv2.inRange(hsv, np.array([0,25,40]), np.array([180,255,255]))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    color_mask = cv2.dilate(color_mask, k, iterations=1)
    dark = (gray < 100)
    result[(color_mask > 0) & ~dark] = [230, 230, 230]
    result[(color_mask > 0) &  dark] = [0, 0, 0]
    return result


def binarize(gray):
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, blockSize=25, C=8)


def remove_long_lines(binary):
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
        bw = stats[i, cv2.CC_STAT_WIDTH]; bh = stats[i, cv2.CC_STAT_HEIGHT]
        ar = stats[i, cv2.CC_STAT_AREA]
        if 5 <= bw <= 120 and 5 <= bh <= 120 and 20 <= ar <= 8000:
            text_protect[labels == i] = 255
    pk = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
    text_protect = cv2.dilate(text_protect, pk, iterations=1)
    safe = cv2.bitwise_and(lines_mask, cv2.bitwise_not(text_protect))
    inverted[safe > 0] = 0
    return cv2.bitwise_not(inverted)


def stroke_cv(blob):
    ek = cv2.getStructuringElement(cv2.MORPH_CROSS, (3,3))
    cur, counts = blob.copy(), []
    for _ in range(15):
        cur = cv2.erode(cur, ek)
        n = cv2.countNonZero(cur); counts.append(n)
        if n == 0: break
    if len(counts) < 2: return 999.0
    nz = np.array(counts, dtype=float); nz = nz[nz > 0]
    return float(np.std(nz) / (np.mean(nz) + 1e-5)) if len(nz) else 999.0


def build_keep_mask(binary):
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


def enhance_kept_text(binary, keep_mask):
    ek = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
    km = cv2.dilate(keep_mask, ek, iterations=1)
    result = np.full_like(binary, 255); result[km > 0] = 0
    return result


# ═══════════════════════════════════════════════════════════════════════════
# OCR FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def ocr_full_page(clean_img):
    return pytesseract.image_to_string(
        clean_img, lang="fra+eng", config="--psm 6 --oem 1").strip()

def ocr_header_zone(clean_img):
    h = clean_img.shape[0]
    return pytesseract.image_to_string(
        clean_img[:int(h*0.25), :], lang="fra+eng", config="--psm 4 --oem 1").strip()

def ocr_body_zone(clean_img):
    h = clean_img.shape[0]
    return pytesseract.image_to_string(
        clean_img[int(h*0.22):int(h*0.92), :], lang="fra+eng", config="--psm 6 --oem 1").strip()

def clean_ocr_text(text):
    text = re.sub(r'\(cid:\d+\)', '', text)
    text = re.sub(r'(?<!\w)([A-Z] ){3,}([A-Z])(?!\w)',
                  lambda m: m.group(0).replace(' ', ''), text)
    text = re.sub(r'(?<!\w)((?:[A-Z0-9] ){4,}[A-Z0-9])(?!\w)',
                  lambda m: m.group(0).replace(' ', ''), text)
    text = re.sub(r'(?<=\d)l(?=\d)', '1', text)
    text = re.sub(r'(?<=\d)I(?=\d)', '1', text)
    text = re.sub(r'(\d)°o', r'\g<1>0', text)
    text = re.sub(r'(\d)°(?=\d)', r'\g<1>0', text)
    text = re.sub(r'(?<=[A-Za-z0-9])\|(?=[A-Za-z0-9])', ' ', text)
    text = re.sub(r'^\s*\|\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'(?i)\b(on de commande)\b', 'Bon de commande', text)
    text = re.sub(r'(?i)\b(on de livraison)\b', 'Bon de livraison', text)
    text = re.sub(r'[=~_—]{2,}', ' ', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
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
# TABLE EXTRACTION — pdfplumber
# ═══════════════════════════════════════════════════════════════════════════

def extract_tables_pdfplumber(pdf_path):
    all_tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables({"vertical_strategy":"lines",
                                          "horizontal_strategy":"lines",
                                          "intersection_tolerance":5})
            for table in (tables or []):
                clean = []
                for row in table:
                    r = [str(c or '').strip() for c in row]
                    if any(c for c in r): clean.append(r)
                if clean: all_tables.append(clean)
    return all_tables

def detect_pdf_native(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        total = sum(len((p.extract_text() or '').strip()) for p in pdf.pages)
    return total > 100


# ═══════════════════════════════════════════════════════════════════════════
# REGEX EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

DOC_TYPES = {
    "Proforma":           ["proforma", "b.c. interne", "incoterms", "date/heure livraison"],
    "Bon de Commande":    ["bon de commande", "commande fournisseur", "bcn-", "bc n°"],
    "Facture":            ["facture", "invoice", "facture numéro"],
    "Statistiques":       ["statistique", "quantitatif des ventes", "stat. ventes",
                           "quantité proposée", "moyenne des ventes"],
    "Chiffre d'Affaires": ["chiffre d'affaire", "ventes et chiffre"],
}

def detect_doc_type(text):
    tl = text.lower()
    for dtype, kws in DOC_TYPES.items():
        if any(k in tl for k in kws): return dtype
    return "Document"

_ADDR_ANCHOR = re.compile(
    r'\b(route|rue|avenue|av\.?|bd\.?|boulevard|cit[eé]|zone\s+ind'
    r'|lot\s+n?[°o]?|lotissement|impasse|r[eé]sidence|quartier|km\s*\d'
    r'|n[°o]\s*\d{1,4}\s+(?:rue|route|av))\b', re.IGNORECASE)

def extract_address(header_text):
    lines = [l.strip() for l in header_text.splitlines() if l.strip()]
    found = []; in_block = False
    for line in lines:
        if _ADDR_ANCHOR.search(line):
            found.append(line); in_block = True
        elif in_block:
            is_label = re.match(r'^(tel|fax|m\.?f|r\.?c|sfax|tunis|nabeul|sousse'
                                r'|date|page|code|email|prépar|edité)', line, re.I)
            if not is_label and 6 < len(line) < 120: found.append(line)
            in_block = False
    return " — ".join(found) if found else ""

def _to_float(s):
    if not s: return None
    s = str(s).strip(); s = re.sub(r'[^\d,.]','', s)
    if not s: return None
    if ',' in s and '.' in s:
        s = s.replace(',','') if s.rfind('.')>s.rfind(',') else s.replace('.','').replace(',','.')
    elif ',' in s:
        p = s.split(',')
        s = s.replace(',','.') if len(p)==2 and len(p[1])<=3 else s.replace(',','')
    try: return round(float(s), 3)
    except: return None

def extract_info(text):
    info = {}
    info["type"] = detect_doc_type(text)
    for pat in [
        r'PROFORMA\s+N[°o][:\s]*([A-Z0-9\-]{6,25})',
        r'Commande\s+(?:Fournisseur\s+)?N[°o][:\s]*(\d{4,10})',
        r'N[°o]\s*Facture[:\s]*([A-Z0-9\-]{4,20})',
        r'Facture\s+num[eé]ro\s+([0-9\s]{3,15})',
        r'\b(BCN-\d{2}-\d{4})\b',
        r'\b(BCM?-\d{2}-\d{4})\b',
        r'N[°o][:\s]*([A-Z0-9\-]{4,20})',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            num = re.sub(r'\s+','', m.group(1)).strip(".,;:")
            if len(num) >= 3: info["numero"] = num; break

    m = re.search(r'Date\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})', text, re.I)
    if not m: m = re.search(r'\b(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})\b', text)
    if m: info["date"] = m.group(1)

    _MF = re.compile(
        r'\b(\d{6,8})[/\\|\s]?([A-Z])[/\\|\s]?([A-Z])[/\\|\s]?([A-Z])[/\\|\s]?(\d{3})\b',
        re.IGNORECASE)
    mf = _MF.search(text)
    if mf:
        d1,l1,l2,l3,d2 = mf.group(1),mf.group(2).upper(),mf.group(3).upper(),mf.group(4).upper(),mf.group(5)
        if 6 <= len(d1) <= 8 and len(d2) == 3:
            info["matricule_fiscal"] = f"{d1}{l1}/{l2}/{l3}/{d2}"

    m = re.search(r'T[eé]l[:\.\s/]*(\d[\d\s\.\-]{6,14}\d)', text, re.I)
    if m: info["tel"] = re.sub(r'[\s\.\-]','', m.group(1))
    m = re.search(r'Fax[:\.\s]*([\d][\d\s\.\-]{6,14}\d)', text, re.I)
    if m: info["fax"] = re.sub(r'[\s\.\-]','', m.group(1))
    m = re.search(r'[\w\.-]+@[\w\.-]+\.\w{2,}', text)
    if m: info["email"] = m.group(0)
    m = re.search(r'R\.?C\.?\s*[:\-]?\s*([A-Z][A-Z0-9]{5,14})', text, re.I)
    if m: info["rc"] = m.group(1)

    addr = extract_address(text)
    if addr: info["adresse"] = addr

    for field, kws in {
        "total_ht":  ["total ht","total hors taxe","montant ht","total net ht"],
        "tva":       [" tva ","t.v.a","valeur tva"],
        "total_ttc": ["total ttc","net à payer","montant ttc"],
    }.items():
        for kw in kws:
            if kw in (" " + text.lower() + " "):
                nums = re.findall(r'\d[\d,\.\s]{0,15}\d|\b\d{1,8}\b', text)
                if nums:
                    val = _to_float(nums[-1])
                    if val and 0.01 < val < 50_000_000: info[field] = val
                break
    return {k: v for k, v in info.items() if v}


def extract_product_lines(text):
    items = []; seen = set()
    CODE_PCT   = re.compile(r'^([A-Z]{2,4}\d{2,12}|\d{6})', re.IGNORECASE)
    CODE_ART   = re.compile(r'^([A-Z]{2,4}\d{5,12})\b',     re.IGNORECASE)
    QTY_PFX    = re.compile(r'^(\d{1,5})[\s\|,;._~\-]+(?=[A-Za-z])')
    PRICE_STOP = re.compile(r'\b\d{1,6}[,\.]\d{2,3}\b')
    QTY_END    = re.compile(r'\b(\d{1,5})\b')

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line: continue
        line = re.sub(r'^[\|.\-\s]+', '', line).strip()
        if not line or len(line) < 5: continue
        m_code = CODE_PCT.match(line)
        if not m_code: continue
        code = m_code.group(1).upper()
        if code in seen: continue
        rest = line[len(m_code.group(0)):].strip()
        if len(rest) < 2: continue

        code_article = None
        m_art = CODE_ART.match(rest)
        if m_art:
            code_article = m_art.group(1).upper()
            rest = rest[len(code_article):].strip().lstrip('-').strip()

        rest = re.sub(r"^[\|\.'\"()\[\]\-\s]+", '', rest).strip()
        rest = re.sub(r'^\d{3,}\s+(?=\d{1,3}[\s\|,;._~\-]+[A-Za-z])', '', rest)
        if not rest: continue
        qty_prefix = None
        m_pfx = QTY_PFX.match(rest)
        if m_pfx:
            v = int(m_pfx.group(1))
            if 1 <= v <= 99999:
                qty_prefix = float(v); rest = rest[m_pfx.end():].strip()

        price_m = PRICE_STOP.search(rest)
        if price_m:
            designation_zone = rest[:price_m.start()].strip()
            price_zone       = rest[price_m.start():]
        else:
            designation_zone = rest; price_zone = ""

        desc = re.sub(r'^[\|,;.\-\s]+', '', designation_zone).strip()
        desc = re.sub(r'[\|,;.\-\s]+$', '', desc).strip()
        desc = re.sub(r'\s*\|\s*', ' ', desc).strip()
        if not desc or len(desc) < 3: continue

        qty = qty_prefix
        if not qty:
            for qm in QTY_END.finditer(designation_zone):
                v = int(qm.group(1))
                if 1 <= v <= 99999:
                    tail = designation_zone[qm.start():].strip()
                    if re.fullmatch(r'\d{1,5}', tail):
                        qty = float(v)
                        desc = re.sub(r'^[\|,;.\-\s]+|[\|,;.\-\s]+$', '',
                                      designation_zone[:qm.start()].strip()).strip()
                        break
            if not qty and price_zone:
                for qm in QTY_END.finditer(price_zone):
                    v = int(qm.group(1))
                    if 1 <= v <= 99999: qty = float(v); break

        if not desc or len(desc) < 3: continue
        seen.add(code)
        item = {"code": code, "designation": desc}
        if code_article: item["code_article"] = code_article
        if qty:          item["quantite"] = qty
        items.append(item)
    return items


# ═══════════════════════════════════════════════════════════════════════════
# PDF → IMAGE
# ═══════════════════════════════════════════════════════════════════════════

def pdf_page_to_image(pdf_path, page_index, dpi=300):
    doc  = fitz.open(pdf_path)
    page = doc[page_index]
    mat  = fitz.Matrix(dpi/72, dpi/72)
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    img  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⚙️ Options")
    st.markdown("---")
    st.markdown("**Preprocessing**")
    use_fix_rotation = st.checkbox("Fix Rotation",      value=True)
    use_erase_color  = st.checkbox("Erase Colored Ink", value=True)
    use_remove_lines = st.checkbox("Remove Borders",    value=True)
    use_keep_mask    = st.checkbox("Blob Filter (CV)",  value=True)
    st.markdown("---")
    st.markdown("**OCR**")
    split_zones = st.checkbox("Split Header / Body OCR", value=True)
    show_raw    = st.checkbox("Show Raw OCR Text",       value=False)
    st.markdown("---")
    st.markdown("**Output**")
    show_tables   = st.checkbox("Show pdfplumber Tables", value=True)
    show_products = st.checkbox("Show Product Lines",     value=True)
    show_json     = st.checkbox("Show Full JSON",         value=False)


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

    # ── Pipeline log: initialise + place placeholder at top of page ────
    _log_init()
    _log_ph = st.empty()     # single placeholder re-rendered at each step
    _log_render(_log_ph)

    is_pdf = uploaded.type == "application/pdf"
    suffix = ".pdf" if is_pdf else Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    # ── Step 1: Load ───────────────────────────────────────────────────
    file_kb = round(len(uploaded.getvalue()) / 1024, 1)
    _log_set("load", "done", f"{uploaded.name}  ({file_kb} KB)")
    _log_render(_log_ph)

    # ── Step 2: Detect type ────────────────────────────────────────────
    if is_pdf:
        _log_set("detect", "running", "reading PDF…")
        _log_render(_log_ph)
        is_native   = detect_pdf_native(tmp_path)
        doc_fitz    = fitz.open(tmp_path)
        total_pages = len(doc_fitz)
        _log_set("detect", "done",
                 f"{'Native' if is_native else 'Scanned'} PDF  —  {total_pages} page(s)")
        _log_render(_log_ph)
    else:
        is_native   = False
        total_pages = 1
        _log_set("detect", "done", f"Image file  —  1 page")
        _log_render(_log_ph)

    if is_pdf:
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

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════════════
    # PROCESS ALL PAGES
    # ═══════════════════════════════════════════════════════════════════

    all_header_texts  = []
    all_body_texts    = []
    all_full_texts    = []
    all_clean_imgs    = []
    all_orig_imgs     = []
    all_product_lines = []
    seen_codes        = set()

    prog = st.progress(0, text="Processing pages…")

    for page_i in range(total_pages):

        # ── Step 3: Preprocess ─────────────────────────────────────────
        _log_set("preprocess", "running",
                 f"page {page_i+1}/{total_pages}  |  "
                 f"rotation={use_fix_rotation}  color={use_erase_color}  "
                 f"lines={use_remove_lines}  blob={use_keep_mask}")
        _log_render(_log_ph)
        _pp_t0 = _time.time()

        if is_pdf:
            img_bgr = pdf_page_to_image(tmp_path, page_i, dpi=300)
        else:
            file_bytes = np.frombuffer(uploaded.getvalue(), dtype=np.uint8)
            img_bgr    = cv2.imdecode(file_bytes, 1)

        all_orig_imgs.append(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))

        work = img_bgr.copy()
        if use_fix_rotation: work = fix_rotation(work)
        if use_erase_color:  work = erase_colored_ink(work)
        gray   = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        binary = binarize(gray)
        if use_remove_lines: binary = remove_long_lines(binary)
        if use_keep_mask:    clean  = enhance_kept_text(binary, build_keep_mask(binary))
        else:                clean  = binary
        all_clean_imgs.append(clean)

        _log_set("preprocess", "done",
                 f"{total_pages} page(s) cleaned", t0=_pp_t0)
        _log_render(_log_ph)

        # ── Step 4: OCR ────────────────────────────────────────────────
        _log_set("ocr", "running",
                 f"page {page_i+1}/{total_pages}  |  "
                 f"LSTM  split={split_zones}")
        _log_render(_log_ph)
        _ocr_t0 = _time.time()

        if split_zones:
            h_text = clean_ocr_text(ocr_header_zone(clean))
            b_text = clean_ocr_text(ocr_body_zone(clean))
            f_text = h_text + "\n" + b_text
        else:
            f_text = clean_ocr_text(ocr_full_page(clean))
            h_text = b_text = f_text

        all_header_texts.append(h_text)
        all_body_texts.append(b_text)
        all_full_texts.append(f_text)

        _log_set("ocr", "done",
                 f"{total_pages} page(s)  |  {len(f_text.split())} words", t0=_ocr_t0)
        _log_render(_log_ph)

        # ── Step 5: Product lines (per page) ───────────────────────────
        _log_set("products", "running",
                 f"page {page_i+1}/{total_pages}  |  scanning product codes…")
        _log_render(_log_ph)

        if show_products:
            for item in extract_product_lines(b_text):
                code = item.get("code", "")
                if code and code not in seen_codes:
                    seen_codes.add(code); all_product_lines.append(item)
                elif not code:
                    all_product_lines.append(item)

        _log_set("products", "done",
                 f"{len(all_product_lines)} unique product line(s) so far")
        _log_render(_log_ph)

        prog.progress((page_i+1)/total_pages,
                      text=f"Processing page {page_i+1} / {total_pages}…")

    prog.empty()

    combined_full   = "\n\n".join(all_full_texts)
    combined_header = "\n\n".join(all_header_texts)

    # ── Step 6: pdfplumber ─────────────────────────────────────────────
    plumber_tables = []
    if is_pdf and is_native and show_tables:
        _log_set("pdfplumber", "running", "reading PDF vector table data…")
        _log_render(_log_ph)
        _pl_t0 = _time.time()
        with st.spinner("Extracting tables with pdfplumber…"):
            plumber_tables = extract_tables_pdfplumber(tmp_path)
        _log_set("pdfplumber", "done",
                 f"{len(plumber_tables)} table(s) found", t0=_pl_t0)
        _log_render(_log_ph)
    else:
        reason = "scanned PDF — OCR used" if (is_pdf and not is_native) \
            else "image file" if not is_pdf \
            else "disabled in sidebar"
        _log_set("pdfplumber", "skip", reason)
        _log_render(_log_ph)

    # ── Step 7: Regex extraction ───────────────────────────────────────
    _log_set("regex", "running",
             f"scanning {len(combined_full.split())} words  |  "
             f"MF · date · tel · doc number · address…")
    _log_render(_log_ph)
    _rx_t0 = _time.time()

    extracted_info = extract_info(combined_full)
    addr_p1 = extract_address(all_header_texts[0])
    if addr_p1: extracted_info["adresse"] = addr_p1

    _log_set("regex", "done",
             f"type={extracted_info.get('type','?')}  "
             f"date={extracted_info.get('date','—')}  "
             f"MF={extracted_info.get('matricule_fiscal','—')}",
             t0=_rx_t0)
    _log_render(_log_ph)

    # ── Step 8: Done ───────────────────────────────────────────────────
    _log_set("done", "done",
             f"{total_pages} page(s) processed  |  "
             f"{len(all_product_lines)} items  |  "
             f"{len(plumber_tables)} tables")
    _log_render(_log_ph)

    # ═══════════════════════════════════════════════════════════════════
    # DISPLAY: ALL PAGES
    # ═══════════════════════════════════════════════════════════════════

    st.markdown("## 🖼️ Pages — Original & Cleaned")
    for page_i, (orig_img, clean_img) in enumerate(zip(all_orig_imgs, all_clean_imgs)):
        label = f"Page {page_i+1} / {total_pages}" if total_pages > 1 else "Document"
        st.markdown(f"<div class='page-label'>{label}</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#888;"
                        "text-align:center;margin-bottom:4px'>📷 Original</div>",
                        unsafe_allow_html=True)
            st.image(orig_img, use_container_width=True)
        with c2:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#7ee8a2;"
                        "text-align:center;margin-bottom:4px'>✨ After Cleaning</div>",
                        unsafe_allow_html=True)
            st.image(clean_img, use_container_width=True)
        if page_i < len(all_clean_imgs)-1:
            st.markdown("<hr style='border-color:#1e2130;margin:12px 0;'>",
                        unsafe_allow_html=True)

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════════════
    # RESULTS
    # ═══════════════════════════════════════════════════════════════════

    dtype     = extracted_info.get("type", "Document")
    tag_class = {"Bon de Commande":"tag-bc","Proforma":"tag-proforma",
                 "Facture":"tag-facture"}.get(dtype, "tag-stat")
    st.markdown(f"<span class='{tag_class}'>{dtype}</span>", unsafe_allow_html=True)
    st.markdown("## 📋 Extracted Information")

    info_cols = st.columns(3)
    fields = [
        ("Type de document",  extracted_info.get("type",             "—")),
        ("Document N°",       extracted_info.get("numero",           "—")),
        ("Date",              extracted_info.get("date",             "—")),
        ("Matricule Fiscal",  extracted_info.get("matricule_fiscal", "—")),
        ("Téléphone",         extracted_info.get("tel",              "—")),
        ("Fax",               extracted_info.get("fax",              "—")),
        ("Email",             extracted_info.get("email",            "—")),
        ("RC",                extracted_info.get("rc",               "—")),
        ("Total HT",          extracted_info.get("total_ht",         "—")),
        ("Total TTC",         extracted_info.get("total_ttc",        "—")),
    ]
    for idx, (label, value) in enumerate(fields):
        with info_cols[idx % 3]:
            st.markdown(f"""
            <div class='metric-card'>
                <div class='metric-label'>{label}</div>
                <div class='metric-value' style='font-size:14px'>{value}</div>
            </div>""", unsafe_allow_html=True)

    if extracted_info.get("adresse"):
        st.markdown(f"""
        <div class='metric-card' style='margin-top:6px'>
            <div class='metric-label'>Adresse</div>
            <div class='metric-value' style='font-size:13px;color:#7ec8e8'>
                {extracted_info['adresse']}
            </div>
        </div>""", unsafe_allow_html=True)

    # Product lines
    if show_products and all_product_lines:
        st.markdown(f"## 📦 Product Lines ({len(all_product_lines)} items)")
        tbl = "<div class='table-container'><table><thead><tr>"
        tbl += "<th>#</th><th>Code</th><th>Designation</th><th>Quantity</th>"
        tbl += "</tr></thead><tbody>"
        for i, item in enumerate(all_product_lines, 1):
            qty = item.get("quantite", "—")
            qty_s = f"{qty:.0f}" if isinstance(qty, float) else str(qty)
            tbl += (f"<tr><td style='color:#555'>{i}</td>"
                    f"<td style='color:#7ee8a2'>{item.get('code','')}</td>"
                    f"<td>{item.get('designation','')}</td>"
                    f"<td style='text-align:right;color:#e8c87e'>{qty_s}</td></tr>")
        tbl += "</tbody></table></div>"
        st.markdown(tbl, unsafe_allow_html=True)
    elif show_products:
        st.info("No product lines detected. Enable 'Show Raw OCR Text' to debug.")

    # pdfplumber tables
    if plumber_tables:
        st.markdown(f"## 🗃️ pdfplumber Tables ({len(plumber_tables)} found)")
        for t_idx, table in enumerate(plumber_tables):
            if not table: continue
            st.markdown(f"**Table {t_idx+1}**")
            tbl = "<div class='table-container'><table><thead><tr>"
            for h in table[0]:
                tbl += f"<th>{str(h).replace('&','&amp;').replace('<','&lt;')}</th>"
            tbl += "</tr></thead><tbody>"
            for row in table[1:]:
                if any(str(c).strip() for c in row):
                    tbl += "<tr>"
                    for cell in row:
                        tbl += f"<td>{str(cell).replace('&','&amp;').replace('<','&lt;')}</td>"
                    tbl += "</tr>"
            tbl += "</tbody></table></div>"
            st.markdown(tbl, unsafe_allow_html=True)
            st.markdown("")

    # Raw OCR
    if show_raw:
        st.markdown("## 📝 Raw OCR Text")
        for page_i in range(total_pages):
            label = f"Page {page_i+1}" if total_pages > 1 else "Full text"
            with st.expander(label, expanded=(page_i == 0)):
                if split_zones:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Header zone**")
                        st.markdown(f"<div class='raw-text'>{all_header_texts[page_i]}</div>",
                                    unsafe_allow_html=True)
                    with c2:
                        st.markdown("**Body zone**")
                        st.markdown(f"<div class='raw-text'>{all_body_texts[page_i]}</div>",
                                    unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='raw-text'>{all_full_texts[page_i]}</div>",
                                unsafe_allow_html=True)

    # Full JSON
    if show_json:
        st.markdown("## 🗂️ Full JSON")
        st.json({"informations_document": extracted_info,
                 "ligne_articles": all_product_lines})

    # Downloads
    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇ Download JSON",
            data=json.dumps({"informations_document": extracted_info,
                             "ligne_articles": all_product_lines},
                            ensure_ascii=False, indent=2),
            file_name=f"{Path(uploaded.name).stem}_extracted.json",
            mime="application/json", use_container_width=True)
    with c2:
        st.download_button("⬇ Download OCR Text",
            data=combined_full,
            file_name=f"{Path(uploaded.name).stem}_ocr.txt",
            mime="text/plain", use_container_width=True)

    try: os.unlink(tmp_path)
    except: pass