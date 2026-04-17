"""
Invoice OCR Pipeline — v4.2
════════════════════════════
Fixes over v4.1:
  • fix_rotation — removed minAreaRect fine-skew entirely (was tilting straight pages).
    Only Tesseract OSD (90/180/270 flips) is kept. Real documents are never
    more than 1-2° off and minAreaRect was over-correcting from logo/stamp pixels.
  • render_info_grid now used for ALL metric cards → no more raw HTML tags visible.
  • Confidence badges: now hidden by default; sidebar toggle explains what they are.
  • Doc N° catches "NNN/YYYY" line below document title (e.g. "445 / 2023").
  • MF extracted from header zone only (fournisseur block, top-left of page 1).
  • DPI selector (150/200/300, default 200) for ~40% speed gain over 300.
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

import spacy
from rapidfuzz import fuzz, process as fuzz_process
import dateparser
from datetime import datetime

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

    /* ── Info grid rendered as ONE html block to avoid Streamlit column bug ── */
    .info-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 10px;
        margin-bottom: 14px;
    }
    .metric-card {
        background: #1a1d26;
        border: 1px solid #2a2d3a;
        border-radius: 8px;
        padding: 14px 16px 12px 16px;
        position: relative;
        min-height: 72px;
    }
    .addr-card { grid-column: 1 / -1; }
    .metric-label {
        font-size: 10px; color: #555; text-transform: uppercase;
        letter-spacing: 1px; margin-bottom: 6px; font-family: 'Syne', sans-serif;
    }
    .metric-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 14px; font-weight: 600; color: #7ee8a2; word-break: break-word;
    }
    .metric-value.addr-val  { color: #7ec8e8; font-size: 12px; }
    .metric-value.warn-val  { color: #e8c87e; }
    .metric-value.empty-val { color: #333849; font-style: italic; }

    /* Confidence badge — small pill top-right of each card */
    .conf-badge {
        position: absolute; top: 10px; right: 10px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px; padding: 2px 6px; border-radius: 6px; font-weight: 600;
    }
    .cb-high   { background:#1a3a2a; color:#7ee8a2; border:1px solid #2a5a3a; }
    .cb-medium { background:#3a3a1a; color:#e8e87e; border:1px solid #5a5a2a; }
    .cb-low    { background:#3a1a1a; color:#e87e7e; border:1px solid #5a2a2a; }

    /* Legend below section title */
    .conf-hint {
        font-size: 11px; color: #445; margin-bottom: 12px;
        font-family: 'JetBrains Mono';
    }

    .tag-bc       { background:#1a3a2a;color:#7ee8a2;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #2a5a3a; }
    .tag-proforma { background:#1a2a3a;color:#7ec8e8;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #2a4a5a; }
    .tag-facture  { background:#3a2a1a;color:#e8c87e;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #5a4a2a; }
    .tag-stat     { background:#2a1a3a;color:#c87ee8;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #4a2a5a; }

    div[data-testid="stSidebar"] { background:#13151f;border-right:1px solid #1e2130; }
    .stButton > button {
        background:#7ee8a2;color:#0f1117;border:none;font-family:'Syne';
        font-weight:700;letter-spacing:0.5px;padding:10px 28px;border-radius:6px;
        width:100%;transition:all 0.2s;
    }
    .stButton > button:hover { background:#a0f0b8;transform:translateY(-1px); }
    .raw-text {
        background:#1a1d26;border:1px solid #2a2d3a;border-radius:8px;
        padding:16px;font-family:'JetBrains Mono';font-size:11px;color:#b0b0a8;
        max-height:400px;overflow-y:auto;white-space:pre-wrap;
    }
    .table-container { overflow-x:auto; }
    table { width:100%;border-collapse:collapse;font-size:12px;font-family:'JetBrains Mono'; }
    th { background:#1e2130;color:#7ee8a2;padding:8px 12px;text-align:left;border-bottom:1px solid #2a2d3a;font-weight:600; }
    td { padding:7px 12px;border-bottom:1px solid #1e2130;color:#c8c8c2;vertical-align:top; }
    tr:hover td { background:#1a1d26; }
    .page-label { font-family:'Syne';font-size:12px;color:#555;text-transform:uppercase;letter-spacing:1px;margin:12px 0 4px 0; }
    .warn-box { background:#2a1f0a;border:1px solid #5a3a0a;border-radius:8px;padding:10px 16px;margin:8px 0;font-size:12px;color:#e8c87e; }
    .warn-box ul { margin:4px 0 0 16px;padding:0; }

    /* Pipeline log */
    .pl-wrap  { background:#0d0f17;border:1px solid #1e2130;border-radius:10px;padding:14px 16px;margin-bottom:12px; }
    .pl-title { font-family:'Syne';font-size:11px;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px; }
    .pl-step  { display:flex;align-items:flex-start;gap:10px;padding:7px 0;border-bottom:1px solid #141720; }
    .pl-step:last-child { border-bottom:none; }
    .pl-icon  { font-size:13px;flex-shrink:0;width:18px;text-align:center;margin-top:1px; }
    .pl-info  { flex:1;min-width:0; }
    .pl-name  { font-family:'Syne';font-size:12px; }
    .pl-detail{ font-family:'JetBrains Mono';font-size:10px;color:#445;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap; }
    .pl-time  { font-family:'JetBrains Mono';font-size:10px;color:#445;flex-shrink:0;padding-left:8px;align-self:center; }
    .s-pending .pl-name { color:#383c50; }
    .s-running .pl-name { color:#7ee8a2; }
    .s-done    .pl-name { color:#c8c8c2; }
    .s-skip    .pl-name { color:#333849;font-style:italic; }
    .s-warn    .pl-name { color:#e8c87e; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE LOG
# ═══════════════════════════════════════════════════════════════════════════

_STEPS = [
    ("load",       "📂", "Load file"),
    ("detect",     "🔍", "Detect PDF type"),
    ("preprocess", "🧹", "Preprocess image(s)"),
    ("ocr",        "🔤", "OCR text extraction"),
    ("pdfplumber", "📊", "pdfplumber tables"),
    ("regex",      "🔎", "Regex baseline extraction"),
    ("nlp",        "🧠", "NLP enrichment"),
    ("products",   "📦", "Product line extraction"),
    ("done",       "✅", "Pipeline complete"),
]

def _log_init():
    st.session_state["_pl"] = {k: {"status":"pending","detail":"","t":""} for k,*_ in _STEPS}

def _log_set(key, status, detail="", t0=0.0):
    if "_pl" not in st.session_state: _log_init()
    elapsed = ""
    if status == "done" and t0:
        ms = int((_time.time()-t0)*1000)
        elapsed = f"{ms}ms" if ms < 1000 else f"{ms/1000:.1f}s"
    st.session_state["_pl"][key] = {"status":status,"detail":detail,"t":elapsed}

def _log_render(ph):
    if "_pl" not in st.session_state: return
    pl = st.session_state["_pl"]
    icons = {"pending":"○","running":"⏳","done":"✓","skip":"–","warn":"⚠"}
    html = "<div class='pl-wrap'><div class='pl-title'>⚡ Pipeline</div>"
    for key, _, label in _STEPS:
        s   = pl.get(key, {"status":"pending","detail":"","t":""})
        st_ = s["status"]
        html += (
            f"<div class='pl-step s-{st_}'>"
            f"<span class='pl-icon'>{icons.get(st_,'○')}</span>"
            f"<div class='pl-info'><div class='pl-name'>{label}</div>"
            + (f"<div class='pl-detail'>{s['detail']}</div>" if s['detail'] else "")
            + "</div>"
            + (f"<span class='pl-time'>{s['t']}</span>" if s['t'] else "")
            + "</div>"
        )
    html += "</div>"
    ph.markdown(html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# NLP MODEL LOADER
# ═══════════════════════════════════════════════════════════════════════════

@st.cache_resource(show_spinner=False)
def load_nlp():
    for model in ("fr_core_news_sm", "en_core_web_sm"):
        try:
            return spacy.load(model), model
        except OSError:
            continue
    return spacy.blank("fr"), "blank_fr"


# ═══════════════════════════════════════════════════════════════════════════
# NLP LAYER
# ═══════════════════════════════════════════════════════════════════════════

_LABEL_BANKS = {
    "total_ht": [
        "total ht","total hors taxe","montant ht","total net ht",
        "sous total ht","base ht","total brut ht","net ht","valeur ht",
    ],
    "tva": [
        "tva","t v a","valeur tva","montant tva","taxe valeur ajoutee",
        "taxe sur valeur ajoutee","tva 19","tva 7","total tva",
    ],
    "total_ttc": [
        "total ttc","net a payer","net a payer","montant ttc",
        "total a payer","total a payer","montant total","total general",
        "a regler","solde a payer","net payer","montant du",
    ],
}

_DOC_TYPE_LABELS = {
    "Proforma":           ["proforma","bc interne","incoterms","date heure livraison","pro forma"],
    "Bon de Commande":    ["bon de commande","commande fournisseur","bcn","bon commande","order"],
    "Facture":            ["facture","invoice","facture numero","note de debit"],
    "Statistiques":       ["statistique","quantitatif des ventes","stat ventes",
                           "quantite proposee","moyenne des ventes"],
    "Chiffre d'Affaires": ["chiffre affaire","ventes et chiffre","ca mensuel"],
}

_ADDR_ANCHOR = re.compile(
    r'\b(route|rue|avenue|av\.?|bd\.?|boulevard|cit[eé]|zone\s+ind'
    r'|lot\s+n?[°o]?|lotissement|impasse|r[eé]sidence|quartier|km\s*\d'
    r'|n[°o]\s*\d{1,4}\s+(?:rue|route|av))\b', re.IGNORECASE)

_ADDR_STOP = re.compile(
    r'^(tel|t[eé]l|fax|m\.?f|r\.?c|sfax|tunis|nabeul|sousse|monastir|date|page'
    r'|code|email|pr[eé]par|[eé]dit[eé]|bon\s+de|facture|proforma|commande)',
    re.IGNORECASE)


def _conf_badge_html(conf: float) -> str:
    pct = int(conf * 100)
    cls = "cb-high" if conf >= 0.80 else "cb-medium" if conf >= 0.55 else "cb-low"
    return f"<span class='conf-badge {cls}'>{pct}%</span>"


def _fuzzy_doc_type(text: str):
    snippet = re.sub(r'[^\w\s]', ' ', text[:400].lower())
    best_type, best_score = "Document", 0.0
    for dtype, labels in _DOC_TYPE_LABELS.items():
        for label in labels:
            score = fuzz.partial_ratio(label, snippet) / 100.0
            if score > best_score:
                best_score, best_type = score, dtype
    return best_type, round(best_score, 2)


def _fuzzy_find_amount(text: str, field: str):
    labels = _LABEL_BANKS.get(field, [])
    lines  = text.splitlines()
    best_val, best_conf = None, 0.0
    for i, line in enumerate(lines):
        if _is_likely_table_or_product_line(line):
            continue
        line_clean = re.sub(r'[^\w\s]', ' ', line.lower())
        # Raised from 65 → 72 to reduce false-positive label matches
        match = fuzz_process.extractOne(line_clean, labels,
                                        scorer=fuzz.partial_ratio, score_cutoff=72)
        if not match: continue
        _, score, _ = match
        conf = score / 100.0
        context = line + (" " + lines[i+1] if i+1 < len(lines) else "")
        nums = re.findall(r'\b\d{1,8}[,\.]\d{2,3}\b|\b\d{3,8}\b', context)
        for raw in reversed(nums):
            val = _to_float(raw)
            # Exclude years and numbers that look like dates/doc-numbers
            if val and 100 < val < 50_000_000 and not (1900 <= val <= 2100):
                is_bare_six = bool(re.fullmatch(r'\d{6}', re.sub(r'\s+', '', raw)))
                if is_bare_six and not re.search(r'[,.]\d{2,3}', raw) and _amount_context_strength(context) < 0.85:
                    continue
                if conf > best_conf:
                    best_val, best_conf = val, conf
                break
    return best_val, round(best_conf, 2)


def _validate_date(date_str: str):
    if not date_str:
        return date_str, False, "No date found"
    parts = re.split(r'[/\-\.]', date_str.strip())
    if len(parts) == 3:
        try:
            d, m = int(parts[0]), int(parts[1])
            if d > 31:
                return date_str, False, f"Invalid day '{d}' in '{date_str}'"
            if m > 12:
                if d <= 12:
                    fixed = f"{parts[1]}/{parts[0]}/{parts[2]}"
                    return fixed, True, f"Day/month swapped — corrected to {fixed}"
                return date_str, False, f"Invalid month '{m}' in '{date_str}'"
        except ValueError:
            pass
    parsed = dateparser.parse(date_str, settings={
        "PREFER_DAY_OF_MONTH": "first",
        "DATE_ORDER": "DMY",
        "RETURN_AS_TIMEZONE_AWARE": False,
    })
    if not parsed:
        return date_str, False, f"Could not parse date '{date_str}'"
    if parsed.year > datetime.now().year + 1:
        return date_str, False, f"Date '{date_str}' appears to be in the future"
    return parsed.strftime("%d/%m/%Y"), True, ""


def _spacy_extract(text: str, nlp):
    doc  = nlp(text[:3000])
    ents = {"DATE":[],"MONEY":[],"ORG":[],"LOC":[],"PER":[]}
    for ent in doc.ents:
        if ent.label_ in ents:
            ents[ent.label_].append(ent.text.strip())
    return ents


def nlp_enrich(regex_info: dict, text: str, header_text: str, nlp):
    enriched   = dict(regex_info)
    confidence = {}
    warnings   = []

    # 1. Doc type
    nlp_type, type_conf = _fuzzy_doc_type(text)
    regex_type = regex_info.get("type","Document")
    if regex_type == "Document" and nlp_type != "Document":
        enriched["type"] = nlp_type; confidence["type"] = type_conf
    elif nlp_type == regex_type:
        confidence["type"] = max(type_conf, 0.90)
    else:
        confidence["type"] = type_conf
        if type_conf > 0.80 and nlp_type != "Document":
            enriched["type"] = nlp_type

    # 2. Date
    raw_date = regex_info.get("date","")
    if not raw_date:
        ents = _spacy_extract(text, nlp)
        for ed in ents.get("DATE",[]):
            if re.search(r'\d{4}|\d{1,2}[/\-\.]\d{1,2}', ed):
                raw_date = ed; break
    if raw_date:
        normed, is_valid, warn_msg = _validate_date(raw_date)
        if is_valid:
            enriched["date"] = normed
            confidence["date"] = 0.92 if normed != raw_date else 0.95
            if normed != raw_date:
                warnings.append(f"Date corrected: '{raw_date}' → '{normed}'")
        else:
            confidence["date"] = 0.30
            warnings.append(f"Date issue: {warn_msg}")
            enriched["date"] = raw_date
    else:
        confidence["date"] = 0.0

    # 3. Amounts
    for field in ("total_ht","tva","total_ttc"):
        regex_val = regex_info.get(field)
        nlp_val, nlp_conf = _fuzzy_find_amount(text, field)
        if regex_val is not None:
            if nlp_val is not None and abs(regex_val-nlp_val)/(regex_val+1e-9) < 0.01:
                confidence[field] = 0.95
            elif nlp_val is not None:
                enriched[field] = nlp_val; confidence[field] = nlp_conf
                warnings.append(f"{field}: regex={regex_val} vs NLP={nlp_val} — using NLP")
            else:
                confidence[field] = 0.70
        elif nlp_val is not None:
            enriched[field] = nlp_val; confidence[field] = nlp_conf
        else:
            confidence[field] = 0.0

    # 4. Doc number confidence
    numero = enriched.get("numero","")
    if numero:
        if re.match(r'^(BCN|BCM|FAC|PRO|CMD|INV)[\-/]\d{2}[\-/]\d{4}$', numero, re.I):
            confidence["numero"] = 0.97
        elif re.match(r'^\d{3,6}/\d{4}$', numero):
            confidence["numero"] = 0.90
        elif re.match(r'^[A-Z]{2,4}\d{4,}$', numero, re.I):
            confidence["numero"] = 0.80
        else:
            confidence["numero"] = 0.60
    else:
        confidence["numero"] = 0.0

    # 5. Matricule fiscal (role-aware + backward alias)
    for mf_key in ("supplier_mf", "client_mf", "matricule_fiscal"):
        mf = enriched.get(mf_key, "")
        if mf:
            if re.match(r'^\d{6,8}[A-Z]/[A-Z]/[A-Z]/\d{3}$', mf):
                confidence[mf_key] = 0.98
            else:
                confidence[mf_key] = 0.55
                warnings.append(f"{mf_key} format unusual: '{mf}'")
        else:
            confidence[mf_key] = 0.0

    # 6. Phone
    tel = enriched.get("tel","")
    if tel:
        digits = re.sub(r'\D','',tel)
        if len(digits) == 8:   confidence["tel"] = 0.95
        elif len(digits) in (10,11): confidence["tel"] = 0.80
        else:
            confidence["tel"] = 0.50
            warnings.append(f"Phone '{tel}' has unusual length ({len(digits)} digits)")
    else:
        confidence["tel"] = 0.0

    # 7. Email
    email = enriched.get("email","")
    if email:
        confidence["email"] = 0.97 if re.match(r'^[\w\.\-]+@[\w\.\-]+\.\w{2,6}$',email) else 0.50

    # 8. Address spaCy LOC fallback
    if not enriched.get("adresse"):
        ents = _spacy_extract(text, nlp)
        locs = ents.get("LOC",[])
        if locs:
            enriched["adresse"] = " — ".join(locs[:2]); confidence["adresse"] = 0.60
    else:
        confidence["adresse"] = 0.75

    for key in enriched:
        if key not in confidence:
            confidence[key] = 0.70

    return enriched, confidence, warnings


# ═══════════════════════════════════════════════════════════════════════════
# PREPROCESSING
# ═══════════════════════════════════════════════════════════════════════════

def fix_rotation(img_bgr):
    """
    FIX v4.2: removed minAreaRect fine-skew correction.

    WHY: minAreaRect fits a rectangle around ALL dark pixels on the page.
    If there's a logo, stamp, diagonal line, or table border, those pixels
    pull the angle away from 0° — even on a perfectly straight page.
    This was causing pages to become slightly tilted AFTER cleaning.

    We keep ONLY Tesseract OSD which reliably detects 90/180/270° flips
    (like a scanned page that's upside-down or sideways).
    Real scanner skew < 2° is negligible for OCR quality.
    """
    try:
        gray_temp = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(
            gray_temp, config="--psm 0 -c min_characters_to_try=5")
        angle_m = re.search(r"Rotate: (\d+)", osd)
        conf_m  = re.search(r"Orientation confidence: ([\d\.]+)", osd)
        if angle_m and (float(conf_m.group(1)) if conf_m else 0) >= 2.0:
            a = int(angle_m.group(1))
            if a == 90:    img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif a == 180: img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_180)
            elif a == 270: img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    except Exception:
        pass
    return img_bgr


def erase_colored_ink(img_bgr):
    hsv    = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    result = img_bgr.copy()
    cm = cv2.inRange(hsv, np.array([0,25,40]), np.array([180,255,255]))
    k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
    cm = cv2.dilate(cm, k, iterations=1)
    dark = (gray < 100)
    result[(cm>0) & ~dark] = [230,230,230]
    result[(cm>0) &  dark] = [0,0,0]
    return result


def binarize(gray):
    return cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY,blockSize=25,C=8)


def remove_long_lines(binary):
    inv = cv2.bitwise_not(binary)
    h_k = cv2.getStructuringElement(cv2.MORPH_RECT,(80,1))
    v_k = cv2.getStructuringElement(cv2.MORPH_RECT,(1,80))
    lm  = cv2.add(cv2.morphologyEx(inv,cv2.MORPH_OPEN,h_k),
                  cv2.morphologyEx(inv,cv2.MORPH_OPEN,v_k))
    nl, labels, stats, _ = cv2.connectedComponentsWithStats(inv,8)
    tp = np.zeros_like(binary)
    for i in range(1,nl):
        bw=stats[i,cv2.CC_STAT_WIDTH]; bh=stats[i,cv2.CC_STAT_HEIGHT]; ar=stats[i,cv2.CC_STAT_AREA]
        if 5<=bw<=120 and 5<=bh<=120 and 20<=ar<=8000: tp[labels==i]=255
    pk   = cv2.getStructuringElement(cv2.MORPH_RECT,(3,3))
    tp   = cv2.dilate(tp,pk,iterations=1)
    safe = cv2.bitwise_and(lm, cv2.bitwise_not(tp))
    inv[safe>0]=0
    return cv2.bitwise_not(inv)


def stroke_cv(blob):
    ek=cv2.getStructuringElement(cv2.MORPH_CROSS,(3,3))
    cur,counts=blob.copy(),[]
    for _ in range(15):
        cur=cv2.erode(cur,ek); n=cv2.countNonZero(cur); counts.append(n)
        if n==0: break
    if len(counts)<2: return 999.0
    nz=np.array(counts,dtype=float); nz=nz[nz>0]
    return float(np.std(nz)/(np.mean(nz)+1e-5)) if len(nz) else 999.0


def build_keep_mask(binary):
    inv=cv2.bitwise_not(binary)
    nl,labels,stats,_=cv2.connectedComponentsWithStats(inv,8)
    km=np.zeros_like(binary)
    for i in range(1,nl):
        bx=stats[i,cv2.CC_STAT_LEFT]; by=stats[i,cv2.CC_STAT_TOP]
        bw=stats[i,cv2.CC_STAT_WIDTH]; bh=stats[i,cv2.CC_STAT_HEIGHT]
        area=stats[i,cv2.CC_STAT_AREA]
        asp=max(bw,bh)/(min(bw,bh)+1e-5)
        if area<15 or area>15000: continue
        if asp>20 and area>200: continue
        if area<80: km[labels==i]=255; continue
        if area>3000:
            if area/(bw*bh+1e-5)>0.15: km[labels==i]=255
            continue
        if area/(bw*bh+1e-5)<0.12: continue
        blob=(labels[by:by+bh,bx:bx+bw]==i).astype(np.uint8)*255
        if stroke_cv(blob)<1.5: km[labels==i]=255
    return km


def enhance_kept_text(binary, km):
    ek=cv2.getStructuringElement(cv2.MORPH_RECT,(2,2))
    km=cv2.dilate(km,ek,iterations=1)
    r=np.full_like(binary,255); r[km>0]=0
    return r


# ═══════════════════════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════════════════════

def ocr_full_page(img):
    return pytesseract.image_to_string(img, lang="fra+eng", config="--psm 6 --oem 1").strip()

def ocr_header_zone(img):
    h=img.shape[0]
    return pytesseract.image_to_string(img[:int(h*0.30),:],
                                       lang="fra+eng", config="--psm 4 --oem 1").strip()


def ocr_header_layout_lines(img):
    h, w = img.shape[:2]
    header = img[:int(h*0.30), :]
    data = pytesseract.image_to_data(
        header, lang="fra+eng", config="--psm 4 --oem 1", output_type=pytesseract.Output.DICT
    )
    rows = len(data.get("text", []))
    groups = {}
    for i in range(rows):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        left = int(data["left"][i]); top = int(data["top"][i]); wid = int(data["width"][i]); hei = int(data["height"][i])
        g = groups.setdefault(key, {"parts": [], "left": left, "right": left + wid, "top": top, "bottom": top + hei})
        g["parts"].append((left, txt))
        g["left"] = min(g["left"], left)
        g["right"] = max(g["right"], left + wid)
        g["top"] = min(g["top"], top)
        g["bottom"] = max(g["bottom"], top + hei)

    out = []
    for g in groups.values():
        parts = [t for _, t in sorted(g["parts"], key=lambda x: x[0])]
        text_line = clean_ocr_text(" ".join(parts)).strip()
        if not text_line:
            continue
        x_center = (g["left"] + g["right"]) / 2.0
        out.append({
            "text": text_line,
            "x_center": round(float(x_center), 2),
            "x_norm": round(float(x_center / max(1, w)), 4),
            "left": int(g["left"]),
            "right": int(g["right"]),
        })
    return sorted(out, key=lambda x: (x["x_norm"], x["left"]))

def ocr_body_zone(img):
    h=img.shape[0]
    return pytesseract.image_to_string(img[int(h*0.22):int(h*0.92),:],
                                       lang="fra+eng", config="--psm 6 --oem 1").strip()

def clean_ocr_text(text):
    text=re.sub(r'\(cid:\d+\)','',text)
    text=re.sub(r'(?<!\w)([A-Z] ){3,}([A-Z])(?!\w)',lambda m:m.group(0).replace(' ',''),text)
    text=re.sub(r'(?<!\w)((?:[A-Z0-9] ){4,}[A-Z0-9])(?!\w)',lambda m:m.group(0).replace(' ',''),text)
    text=re.sub(r'(?<=\d)l(?=\d)','1',text)
    text=re.sub(r'(?<=\d)I(?=\d)','1',text)
    text=re.sub(r'(\d)°o',r'\g<1>0',text)
    text=re.sub(r'(\d)°(?=\d)',r'\g<1>0',text)
    text=re.sub(r'(?<=[A-Za-z0-9])\|(?=[A-Za-z0-9])',' ',text)
    text=re.sub(r'^\s*\|\s*$','',text,flags=re.MULTILINE)
    text=re.sub(r'(?i)\b(on de commande)\b','Bon de commande',text)
    text=re.sub(r'(?i)\b(on de livraison)\b','Bon de livraison',text)
    text=re.sub(r'[=~_—]{2,}',' ',text)
    text=re.sub(r'[ \t]{2,}',' ',text)
    lines=[]
    for line in text.splitlines():
        s=line.strip()
        if not s: lines.append(''); continue
        alnum=len(re.findall(r'[A-Za-z0-9]',s))
        total=len(s)
        if alnum<3: continue
        if 1-alnum/(total+1e-5)>0.60: continue
        if not re.search(r'[A-Za-z]{3,}|\d',s): continue
        lines.append(s)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# TABLE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

def extract_tables_pdfplumber(pdf_path):
    all_tables=[]
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables=page.extract_tables({"vertical_strategy":"lines",
                                        "horizontal_strategy":"lines",
                                        "intersection_tolerance":5})
            for table in (tables or []):
                clean=[]
                for row in table:
                    r=[str(c or '').strip() for c in row]
                    if any(c for c in r): clean.append(r)
                if clean: all_tables.append(clean)
    return all_tables

def detect_pdf_native(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        total=sum(len((p.extract_text() or '').strip()) for p in pdf.pages)
    return total>100


# ═══════════════════════════════════════════════════════════════════════════
# REGEX BASELINE
# ═══════════════════════════════════════════════════════════════════════════

DOC_TYPES = {
    "Proforma":           ["proforma","b.c. interne","incoterms","date/heure livraison"],
    "Bon de Commande":    ["bon de commande","commande fournisseur","bcn-","bc n°"],
    "Facture":            ["facture","invoice","facture numéro"],
    "Statistiques":       ["statistique","quantitatif des ventes","stat. ventes",
                           "quantité proposée","moyenne des ventes"],
    "Chiffre d'Affaires": ["chiffre d'affaire","ventes et chiffre"],
}

def detect_doc_type(text):
    tl=text.lower()
    for dtype,kws in DOC_TYPES.items():
        if any(k in tl for k in kws): return dtype
    return "Document"


def extract_address(header_text: str) -> str:
    """
    Find ONE address block from the fournisseur header (top-left area).

    Rules:
    - A line qualifies as an address anchor if it contains a street keyword.
    - Accept at most 1 continuation line (for 2-line addresses).
    - Stop immediately when we hit a field label (Tel, MF, date, etc.)
      or a client-side keyword (MEDIS, TUNIS, Code FRS, etc.).
    - Return as soon as the first complete block is found — no more joining
      multiple blocks from different columns into one giant string.
    - Hard cap: result truncated to 120 characters.
    """
    lines = [l.strip() for l in header_text.splitlines() if l.strip()]

    # Expanded stop pattern — includes client-company names and column markers
    STOP = re.compile(
        r'^(tel|t[eé]l|fax|m\.?f|r\.?c|sfax|tunis|nabeul|sousse|monastir'
        r'|bizerte|gab[eè]s|gafsa|kairouan|medenine|ariana'
        r'|date|page|code|email|pr[eé]par|[eé]dit[eé]'
        r'|bon\s+de|facture|proforma|commande'
        r'|medis|omnipharm|pharma|distribution|laboratoire'
        r'|code\s+frs|code\s+pct|sfax\s+le|page\s+n)',
        re.IGNORECASE)

    for i, line in enumerate(lines):
        if not _ADDR_ANCHOR.search(line):
            continue
        # Found an anchor line — collect it + at most 1 safe continuation
        block = [line]
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if not STOP.match(nxt) and 4 < len(nxt) < 100:
                block.append(nxt)
        result = " — ".join(block)
        # Hard cap so a runaway never produces a screen-wide string
        return result[:120].rstrip(" —")

    return ""


def _to_float(s):
    if not s: return None
    s=str(s).strip(); s=re.sub(r'[^\d,.]','',s)
    if not s: return None
    if ',' in s and '.' in s:
        s=s.replace(',','') if s.rfind('.')>s.rfind(',') else s.replace('.','').replace(',','.')
    elif ',' in s:
        p=s.split(',')
        s=s.replace(',','.') if len(p)==2 and len(p[1])<=3 else s.replace(',','')
    try: return round(float(s),3)
    except: return None


def _fix_ocr_digits(token: str) -> tuple[str, bool]:
    repaired = False
    repl = {
        "O": "0", "D": "0", "Q": "0",
        "I": "1", "L": "1", "|": "1",
        "S": "5", "B": "8"
    }
    out = []
    for ch in (token or "").upper():
        if ch in repl:
            out.append(repl[ch])
            repaired = True
        elif ch.isdigit():
            out.append(ch)
    return "".join(out), repaired


def _normalize_mf(raw: str) -> tuple[str, bool]:
    if not raw:
        return "", False
    cleaned = re.sub(r'[^A-Za-z0-9]', '', raw).upper()
    m = re.match(r'^([0-9ODQILS|B]{6,9})([A-Z0-9])([A-Z0-9])([A-Z0-9])([0-9ODQILS|B]{3,4})$', cleaned)
    if not m:
        return "", False
    d1_raw, l1, l2, l3, d2_raw = m.groups()
    d1, repaired1 = _fix_ocr_digits(d1_raw)
    d2, repaired2 = _fix_ocr_digits(d2_raw)
    if len(d1) > 8:
        d1 = d1[:8]
    if len(d2) > 3:
        d2 = d2[-3:]
    if not (6 <= len(d1) <= 8 and len(d2) == 3 and l1.isalpha() and l2.isalpha() and l3.isalpha()):
        return "", (repaired1 or repaired2)
    return f"{d1}{l1}/{l2}/{l3}/{d2}", (repaired1 or repaired2)


def _split_line_segments(line: str) -> list:
    return [seg.strip() for seg in re.split(r'\s{2,}|\|', line) if seg.strip()]


def _mf_score_context(context: str, zone: str, match_at_start: bool) -> tuple[float, float, list]:
    l = context.lower()
    supplier_kw = ("fourn", "vendeur", "expediteur", "societe", "ste", "sarl", "code frs", "frs")
    client_kw = ("client", "destinataire", "acheteur", "medis", "code pct")
    reasons = []
    supplier_score = 0.0
    client_score = 0.0

    if zone == "header":
        supplier_score += 0.20
        client_score += 0.20
        reasons.append("header_zone")
    if match_at_start:
        supplier_score += 0.22
        reasons.append("line_starts_with_mf")
    if any(k in l for k in supplier_kw):
        supplier_score += 0.60
        reasons.append("supplier_keyword")
    if any(k in l for k in client_kw):
        client_score += 0.65
        reasons.append("client_keyword")
    if "nabeul" in l or "tunis" in l or "sfax" in l:
        client_score += 0.12
        reasons.append("city_context")
    if "code pct" in l:
        client_score += 0.20
        reasons.append("code_pct_context")
    if "code frs" in l:
        supplier_score += 0.20
        reasons.append("code_frs_context")
    return supplier_score, client_score, reasons


def _extract_mf_candidates(text: str, zone: str) -> list:
    candidates = []
    rejections = []
    mf_pat = re.compile(
        r'(?:m\.?\s*f\.?\s*[:\-]?\s*)?([0-9ODQILS|B]{6,9})[/\\|\s\-]*([A-Z0-9])[/\\|\s\-]*([A-Z0-9])[/\\|\s\-]*([A-Z0-9])[/\\|\s\-]*([0-9ODQILS|B]{3,4})\b',
        re.IGNORECASE
    )
    for line_idx, line in enumerate(text.splitlines()):
        segments = _split_line_segments(line) or [line]
        for seg_idx, seg in enumerate(segments):
            for m in mf_pat.finditer(seg):
                raw = "".join(m.groups())
                norm, repaired = _normalize_mf(raw)
                if not norm:
                    rejections.append({
                        "kind": "mf",
                        "zone": zone,
                        "line_idx": line_idx,
                        "segment_idx": seg_idx,
                        "raw": raw,
                        "reason": "normalize_failed"
                    })
                    continue
                context = seg[max(0, m.start()-40):m.end()+40]
                match_at_start = bool(re.search(r'^\s*m\.?\s*f\.?\s*[:\-]', seg, re.I))
                supplier_score, client_score, reasons = _mf_score_context(context, zone, match_at_start)
                candidates.append({
                    "value": norm,
                    "line": line.strip(),
                    "segment": seg,
                    "line_idx": line_idx,
                    "segment_idx": seg_idx,
                    "zone": zone,
                    "supplier_score": round(supplier_score, 3),
                    "client_score": round(client_score, 3),
                    "reasons": reasons + (["ocr_digit_repair"] if repaired else []),
                    "repaired": repaired
                })
    return candidates, rejections


def _extract_mf_candidates_with_layout(header_layout_lines: list) -> tuple[list, list]:
    if not header_layout_lines:
        return [], []
    candidates = []
    rejections = []
    mf_pat = re.compile(
        r'(?:m\.?\s*f\.?\s*[:\-]?\s*)?([0-9ODQILS|B]{6,9})[/\\|\s\-]*([A-Z0-9])[/\\|\s\-]*([A-Z0-9])[/\\|\s\-]*([A-Z0-9])[/\\|\s\-]*([0-9ODQILS|B]{3,4})\b',
        re.IGNORECASE
    )
    for line_idx, row in enumerate(header_layout_lines):
        line = row.get("text", "")
        x_norm = float(row.get("x_norm", 0.5))
        for m in mf_pat.finditer(line):
            raw = "".join(m.groups())
            norm, repaired = _normalize_mf(raw)
            if not norm:
                rejections.append({
                    "kind": "mf",
                    "zone": "header_layout",
                    "line_idx": line_idx,
                    "raw": raw,
                    "reason": "normalize_failed"
                })
                continue
            supplier_score, client_score, reasons = _mf_score_context(
                line[max(0, m.start()-40):m.end()+40], "header", bool(re.search(r'^\s*m\.?\s*f\.?\s*[:\-]', line, re.I))
            )
            # Deterministic policy from user: left side supplier, right side client.
            if x_norm < 0.50:
                supplier_score += 0.80
                reasons.append("left_side_supplier_policy")
            else:
                client_score += 0.80
                reasons.append("right_side_client_policy")
            candidates.append({
                "value": norm,
                "line": line,
                "segment": line,
                "line_idx": line_idx,
                "segment_idx": 0,
                "zone": "header_layout",
                "x_norm": round(x_norm, 4),
                "supplier_score": round(supplier_score, 3),
                "client_score": round(client_score, 3),
                "reasons": reasons + (["ocr_digit_repair"] if repaired else []),
                "repaired": repaired
            })
    return candidates, rejections


def _resolve_mf_roles(header_text: str, full_text: str, header_layout_lines: list | None = None) -> tuple[str, str, list, list]:
    c_h, r_h = _extract_mf_candidates(header_text, "header")
    c_f, r_f = _extract_mf_candidates(full_text, "full")
    c_l, r_l = _extract_mf_candidates_with_layout(header_layout_lines or [])
    candidates = c_l + c_h + c_f
    rejections = r_l + r_h + r_f
    if not candidates:
        return "", "", [], rejections

    # Prefer header-layout candidates with explicit x ordering.
    by_x = sorted(
        [c for c in candidates if c.get("zone") == "header_layout"],
        key=lambda x: x.get("x_norm", 0.5)
    )
    supplier_mf, client_mf = "", ""
    if by_x:
        supplier_mf = by_x[0]["value"]
        # pick right-most distinct value for client if available
        distinct = [c for c in by_x if c["value"] != supplier_mf]
        if distinct:
            client_mf = distinct[-1]["value"]
        else:
            rejections.append({"kind": "mf", "reason": "client_unresolved_single_value_layout"})
    else:
        supplier = max(candidates, key=lambda x: (x["supplier_score"], x["zone"] == "header"))
        client = max(candidates, key=lambda x: (x["client_score"], x["zone"] == "header"))
        supplier_mf = supplier["value"] if supplier["supplier_score"] >= 0.42 else ""
        client_mf = client["value"] if client["client_score"] >= 0.42 else ""

    if not supplier_mf and client_mf:
        rejections.append({"kind": "mf", "reason": "supplier_unresolved"})
    if not client_mf and supplier_mf:
        rejections.append({"kind": "mf", "reason": "client_unresolved"})

    return supplier_mf, client_mf, sorted(
        candidates,
        key=lambda x: (max(x["supplier_score"], x["client_score"]), x["zone"] == "header", x["line_idx"]),
        reverse=True), rejections


def _is_likely_table_or_product_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if re.match(r'^[A-Z]{2,4}\d{2,12}\b', s, re.I) or re.match(r'^\d{6}\b', s):
        return True
    if len(re.findall(r'\d{3,}', s)) >= 3 and not re.search(r'total|tva|montant|net', s, re.I):
        return True
    return False


def _amount_context_strength(line: str) -> float:
    l = line.lower()
    score = 0.0
    if re.search(r'total|montant|net|tva|hors taxe|ttc|payer', l):
        score += 0.7
    if re.search(r':', line):
        score += 0.1
    if re.search(r'\d+[,.]\d{2,3}', line):
        score += 0.25
    return score


def _extract_amount_candidates(text: str, field: str, keywords: list[str]) -> list:
    candidates = []
    rejections = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        lline = line.lower()
        if _is_likely_table_or_product_line(line):
            continue
        kw = next((k for k in keywords if k.strip().lower() in f" {lline} "), None)
        if not kw:
            continue
        context = line + (" " + lines[i+1] if i+1 < len(lines) and not _is_likely_table_or_product_line(lines[i+1]) else "")
        ctx_strength = _amount_context_strength(context)
        nums = re.findall(r'\d[\d\s,\.]{0,14}\d|\b\d{1,8}\b', context)
        for raw in nums:
            val = _to_float(raw)
            if not val or not (100 < val < 50_000_000) or (1900 <= val <= 2100):
                rejections.append({"kind":"amount","field":field,"raw":raw,"reason":"range_or_year"})
                continue
            is_bare_six = bool(re.fullmatch(r'\d{6}', re.sub(r'\s+', '', raw)))
            has_decimal = bool(re.search(r'[,.]\d{2,3}', raw))
            if is_bare_six and not has_decimal and ctx_strength < 0.85:
                rejections.append({"kind":"amount","field":field,"raw":raw,"reason":"product_code_like"})
                continue
            distance = max(1, abs(context.lower().find(raw.lower()) - context.lower().find(kw.lower())))
            score = (1.0 / distance) * 45 + ctx_strength + (0.25 if has_decimal else 0.05)
            if field == "tva" and val > 1_000_000:
                score *= 0.55
            candidates.append({
                "value": val,
                "raw": raw,
                "label": kw.strip(),
                "distance": distance,
                "score": round(float(score), 4),
                "context_strength": round(ctx_strength, 3)
            })
    return sorted(candidates, key=lambda x: x["score"], reverse=True), rejections


def _repair_numero_token(token: str) -> tuple[str, bool]:
    t = (token or "").upper()
    repaired = False
    # safe OCR repairs only in doc-number context
    for a, b in (("O", "0"), ("I", "1"), ("L", "1"), ("S", "5")):
        if a in t:
            t = t.replace(a, b)
            repaired = True
    t = re.sub(r'[^A-Z0-9/\-]', '', t)
    return t, repaired


def _extract_numero_with_repair(text: str) -> tuple[str, dict]:
    trace = {
        "raw_numero": "",
        "repaired_numero": "",
        "numero_repair_applied": False,
        "numero_candidate_list": [],
        "numero_reject_reasons": []
    }
    patterns = [
        (r'(?:document|doc|bon\s+de\s+commande|commande|proforma|facture)\s*(?:n[°o])?\s*[:\-]?\s*([A-Z0-9\-/]{3,25})', "labeled_inline", 1.00),
        (r'(?:bon\s+de\s+commande|commande|proforma|facture)[^\n]{0,40}\n\s*([A-Z0-9]{2,6}\s*/\s*\d{4})', "title_next_line", 0.95),
        (r'\b(BCN-[A-Z0-9]{2}-\d{4})\b', "bcn", 0.90),
        (r'\b(BCM?-[A-Z0-9]{2}-\d{4})\b', "bcm", 0.90),
        (r'\b([A-Z0-9]{3,6}\s*/\s*\d{4})\b', "generic_ratio", 0.40),
    ]
    best = None
    for pat, source, base_score in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            raw = re.sub(r'\s+', '', m.group(1)).strip(".,;:")
            fixed, repaired = _repair_numero_token(raw)
            looks_ok = bool(
                re.match(r'^\d{2,6}/\d{4}$', fixed) or
                re.match(r'^(BCN|BCM)-[A-Z0-9]{2}-\d{4}$', fixed, re.I) or
                re.match(r'^[A-Z]{2,5}[0-9\-/]{3,20}$', fixed)
            )
            if not looks_ok:
                trace["numero_reject_reasons"].append({"candidate": raw, "reason": "invalid_shape", "source": source})
                continue
            # Reject month/year-like candidates unless strongly anchored to a label/title.
            mm = re.match(r'^(\d{2})/(\d{4})$', fixed)
            if mm and 1 <= int(mm.group(1)) <= 12 and source not in ("labeled_inline", "title_next_line"):
                trace["numero_reject_reasons"].append({"candidate": fixed, "reason": "month_year_like", "source": source})
                continue
            score = base_score + (0.08 if repaired else 0.0) + (0.12 if re.match(r'^\d{3,6}/\d{4}$', fixed) else 0.0)
            cand = {"raw": raw, "fixed": fixed, "repaired": repaired, "source": source, "score": round(score, 3)}
            trace["numero_candidate_list"].append(cand)
            if best is None or cand["score"] > best["score"]:
                best = cand

    if best:
        trace["raw_numero"] = best["raw"]
        trace["repaired_numero"] = best["fixed"]
        trace["numero_repair_applied"] = best["repaired"]
        return best["fixed"], trace
    return "", trace


def extract_info(text: str, header_text: str, header_layout_lines: list | None = None) -> tuple[dict, dict]:
    """
    Regex baseline.
    FIX 1: Doc N° also catches 'NNN/YYYY' on the line right below the doc-type heading.
            e.g.  "Bon de commande\n445 / 2023"  →  numero = "445/2023"
    FIX 2: MF searched in header_text only (top-left fournisseur block).
            This prevents picking up the CLIENT's MF from the right side of page 1.
    """
    info={}
    trace={"mf_candidates": [], "amount_candidates": {}, "selected": {}, "rejections": []}
    info["type"]=detect_doc_type(text)

    numero, numero_trace = _extract_numero_with_repair(text)
    if numero:
        info["numero"] = numero
        trace["selected"]["numero"] = numero
    trace["selected"].update({k: v for k, v in numero_trace.items() if v})

    # Date
    m=re.search(r'Date\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',text,re.I)
    if not m: m=re.search(r'\b(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})\b',text)
    if m: info["date"]=m.group(1)

    supplier_mf, client_mf, mf_candidates, mf_rejections = _resolve_mf_roles(header_text, text, header_layout_lines)
    trace["selected"]["mf_resolution_policy"] = "left_right_layout"
    trace["mf_candidates"] = mf_candidates[:8]
    trace["rejections"].extend(mf_rejections[:20])
    if supplier_mf:
        info["supplier_mf"] = supplier_mf
        info["matricule_fiscal"] = supplier_mf  # backward-compatible alias
        trace["selected"]["supplier_mf"] = supplier_mf
    if client_mf:
        info["client_mf"] = client_mf
        trace["selected"]["client_mf"] = client_mf
    if supplier_mf == client_mf and supplier_mf:
        trace["rejections"].append({
            "kind": "mf",
            "reason": "ambiguous_role_context_same_value",
            "value": supplier_mf
        })

    # Contact
    m=re.search(r'T[eé]l[:\.\s/]*(\d[\d\s\.\-]{6,20}\d)',text,re.I)
    if m:
        tel_digits = re.sub(r'[\s\.\-]','',m.group(1))
        if len(tel_digits) in (8, 10, 11):
            info["tel"] = tel_digits
        else:
            trace["rejections"].append({
                "kind":"contact","field":"tel","raw":m.group(1),"digits":len(tel_digits),"reason":"invalid_length"
            })
    m=re.search(r'Fax[:\.\s]*([\d][\d\s\.\-]{6,24}\d)',text,re.I)
    if m:
        fax_digits = re.sub(r'[\s\.\-]','',m.group(1))
        if len(fax_digits) in (8, 10, 11):
            info["fax"] = fax_digits
        else:
            trace["rejections"].append({
                "kind":"contact","field":"fax","raw":m.group(1),"digits":len(fax_digits),"reason":"invalid_length"
            })
    m=re.search(r'[\w\.-]+@[\w\.-]+\.\w{2,}',text)
    if m: info["email"]=m.group(0)
    m=re.search(r'R\.?C\.?\s*[:\-]?\s*([A-Z][A-Z0-9]{5,14})',text,re.I)
    if m: info["rc"]=m.group(1)

    addr=extract_address(header_text)
    if addr: info["adresse"]=addr

    # Totals — multi-candidate ranking with deterministic selection.
    amount_labels = {
        "total_ht":  ["total ht","total hors taxe","montant ht","total net ht"],
        "tva":       [" tva "," t.v.a ","valeur tva"],
        "total_ttc": ["total ttc","net à payer","montant ttc"],
    }
    for field, kws in amount_labels.items():
        cands, amount_rejections = _extract_amount_candidates(text, field, kws)
        trace["amount_candidates"][field] = cands[:6]
        trace["rejections"].extend(amount_rejections[:20])
        if cands:
            info[field] = cands[0]["value"]
            trace["selected"][field] = cands[0]["value"]

    if {"total_ht", "tva", "total_ttc"}.issubset(info):
        if abs((info["total_ht"] + info["tva"]) - info["total_ttc"]) > max(2.0, 0.03 * info["total_ttc"]):
            trace["selected"]["amount_consistency_warning"] = "HT + TVA does not match TTC tolerance"

    return {k:v for k,v in info.items() if v}, trace


def extract_product_lines(text):
    items=[]; seen=set(); qty_trace=[]
    CODE_PCT  =re.compile(r'^([A-Z]{2,4}\d{2,12}|\d{6})',re.IGNORECASE)
    CODE_ART  =re.compile(r'^([A-Z]{2,4}\d{5,12})\b',    re.IGNORECASE)
    QTY_PFX   =re.compile(r'^(\d{1,5})[\s\|,;._~\-]+(?=[A-Za-z])')
    PRICE_STOP=re.compile(r'\b\d{1,6}[,\.]\d{2,3}\b')
    QTY_END   =re.compile(r'\b(\d{1,5})\b')

    for raw_line in text.splitlines():
        line=raw_line.strip()
        if not line: continue
        line=re.sub(r'^[\|.\-\s]+','',line).strip()
        if not line or len(line)<5: continue
        m_code=CODE_PCT.match(line)
        if not m_code: continue
        code=m_code.group(1).upper()
        if code in seen: continue
        rest=line[len(m_code.group(0)):].strip()
        if len(rest)<2: continue

        code_article=None
        m_art=CODE_ART.match(rest)
        if m_art:
            code_article=m_art.group(1).upper()
            rest=rest[len(code_article):].strip().lstrip('-').strip()

        # Strip leading OCR garbage characters (add _ to the set)
        rest=re.sub(r"^[\|\.'\"()\[\]\-_\s]+",'',rest).strip()
        # Strip 3+ digit column bleed before a small qty+text
        rest=re.sub(r'^\d{3,}\s+(?=\d{1,3}[\s\|,;._~\-]+[A-Za-z])','',rest)
        # Strip 1-2 digit OCR noise before a real qty+text  (e.g. "0 7 BIGFER" → "7 BIGFER")
        rest=re.sub(r'^\d{1,2}\s+(?=\d{1,5}[\s\|,;._~\-]+[A-Za-z])','',rest)
        if not rest: continue
        qty_prefix=None
        m_pfx=QTY_PFX.match(rest)
        if m_pfx:
            v=int(m_pfx.group(1))
            if 1<=v<=99999:
                qty_prefix=float(v); rest=rest[m_pfx.end():].strip()
        else:
            # Pipe fallback: "garbage 7 | DESIGNATION" (e.g. "_to8 7 | DESIIOR")
            # Scan for the pattern "N | text" anywhere in rest and use it
            m_pipe=re.search(r'\b(\d{1,5})\s*\|\s*([A-Za-z].{3,})', rest)
            if m_pipe:
                qty_prefix=float(int(m_pipe.group(1))); rest=m_pipe.group(2).strip()

        price_m=PRICE_STOP.search(rest)
        dz=rest[:price_m.start()].strip() if price_m else rest
        pz=rest[price_m.start():] if price_m else ""

        desc=re.sub(r'^[\|,;.\-\s]+','',dz).strip()
        desc=re.sub(r'[\|,;.\-_*~\s]+$','',desc).strip()   # also strips trailing _ * ~
        desc=re.sub(r'\s*\|\s*',' ',desc).strip()
        desc=re.sub(r'\s{2,}',' ',desc).strip()             # collapse double spaces
        if not desc or len(desc)<3: continue

        qty=qty_prefix
        qty_source = "prefix" if qty_prefix else ""
        if not qty:
            for qm in QTY_END.finditer(dz):
                v=int(qm.group(1))
                if 1<=v<=99999:
                    tail=dz[qm.start():].strip()
                    # Do not use designation-tail quantity unless row clearly looks columnized.
                    row_has_columns = ("|" in raw_line) or (len(re.findall(r'\s{2,}', raw_line)) >= 2)
                    packsize_like = bool(re.search(r'\b(bt|bte|cp|g[eé]lules|amp|fl)\s*$', dz[:qm.end()], re.I))
                    if re.fullmatch(r'\d{1,5}',tail) and row_has_columns and not packsize_like:
                        qty=float(v)
                        qty_source = "designation_tail"
                        desc=re.sub(r'^[\|,;.\-\s]+|[\|,;.\-\s]+$','',
                                    dz[:qm.start()].strip()).strip()
                        break
            if not qty and pz:
                for qm in QTY_END.finditer(pz):
                    v=int(qm.group(1))
                    if 1<=v<=99999:
                        qty=float(v)
                        qty_source = "price_zone"
                        break

        if not desc or len(desc)<3: continue
        seen.add(code)
        item={"code":code,"designation":desc}
        if code_article: item["code_article"]=code_article
        if qty:
            item["quantite"]=qty
        else:
            pack_nums = re.findall(r'\b(?:bt|bte|cp|g[eé]lules|amp|fl)\s*(\d{1,4})\b', rest, re.I)
            reason = "qty_rejected_packsize_like" if pack_nums else "qty_ambiguous_or_missing"
            qty_trace.append({"code": code, "reason": reason})
        if qty_source:
            item["qty_source"] = qty_source
        items.append(item)
    return items, qty_trace


# ═══════════════════════════════════════════════════════════════════════════
# PDF → IMAGE
# ═══════════════════════════════════════════════════════════════════════════

def pdf_page_to_image(pdf_path, page_index, dpi=200):
    doc =fitz.open(pdf_path)
    page=doc[page_index]
    mat =fitz.Matrix(dpi/72,dpi/72)
    pix =page.get_pixmap(matrix=mat,alpha=False)
    img =np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)


# ═══════════════════════════════════════════════════════════════════════════
# UI HELPER — single HTML block for ALL metric cards
# ═══════════════════════════════════════════════════════════════════════════

def render_info_grid(fields, confidence, show_conf):
    """
    Renders every metric card as ONE st.markdown call using CSS grid.

    WHY ONE BLOCK: Streamlit's st.columns() + unsafe_allow_html has a rendering
    bug where HTML content in certain column positions is shown as raw text
    (e.g. you see '<div class="metric-card">...' literally on screen).
    Bypassing columns entirely and using CSS grid inside a single markdown call
    avoids this completely.
    """
    html = "<div class='info-grid'>"
    for label, key, value in fields:
        conf     = confidence.get(key)
        is_empty = str(value) in ("—","","None")
        badge    = (_conf_badge_html(conf)
                    if show_conf and conf is not None and not is_empty else "")
        val_cls  = ("empty-val" if is_empty
                    else "warn-val" if (conf is not None and conf < 0.55) else "")
        disp     = "—" if is_empty else str(value)
        html += (
            f"<div class='metric-card'>{badge}"
            f"<div class='metric-label'>{label}</div>"
            f"<div class='metric-value {val_cls}'>{disp}</div>"
            f"</div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


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
    dpi_choice  = st.radio("DPI", options=[150,200,300], index=1,
                           help="200 DPI ≈ 40% faster than 300. Use 300 only for very small or faded text.")
    split_zones = st.checkbox("Split Header / Body OCR", value=True)
    show_raw    = st.checkbox("Show Raw OCR Text",       value=False)
    st.markdown("---")
    st.markdown("**NLP**")
    use_nlp       = st.checkbox("Enable NLP Enrichment",    value=True)
    show_conf     = st.checkbox(
        "Show Confidence Scores",
        value=False,
        help="Each field gets a % score: 🟢 ≥80% = reliable, 🟡 55–79% = check it, 🔴 <55% = likely wrong")
    show_warnings = st.checkbox("Show Validation Warnings", value=True)
    show_trace    = st.checkbox("Show Extraction Trace",    value=False)
    st.markdown("---")
    st.markdown("**Output**")
    show_tables   = st.checkbox("Show pdfplumber Tables", value=True)
    show_products = st.checkbox("Show Product Lines",     value=True)
    show_json     = st.checkbox("Show Full JSON",         value=False)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("# 🔬 Invoice OCR Pipeline")
st.markdown("*Preprocessing → OCR → Regex → 🧠 NLP enrichment → Structured output*")
st.markdown("---")

nlp_model, nlp_model_name = load_nlp()

with st.sidebar:
    st.markdown("---")
    st.markdown("**NLP Model**")
    mc = "#7ee8a2" if nlp_model_name != "blank_fr" else "#e8c87e"
    st.markdown(
        f"<span style='font-family:JetBrains Mono;font-size:11px;color:{mc}'>"
        f"{'✓' if nlp_model_name != 'blank_fr' else '⚠'} {nlp_model_name}</span>",
        unsafe_allow_html=True)
    if nlp_model_name == "blank_fr":
        st.caption("Install: `python -m spacy download fr_core_news_sm`")

uploaded = st.file_uploader(
    "Drop a PDF or image file",
    type=["pdf","png","jpg","jpeg"],
    label_visibility="collapsed")
run_btn = st.button("▶  Run Pipeline", use_container_width=True)

if not uploaded:
    st.markdown("""
    <div style='text-align:center;padding:60px 0;color:#444;'>
        <div style='font-size:48px;margin-bottom:16px'>📄</div>
        <div style='font-size:14px'>Upload a PDF or image to begin</div>
        <div style='font-size:11px;color:#333;margin-top:8px'>
        Supports: Bon de Commande · Proforma · Facture · Statistiques
        </div>
    </div>""", unsafe_allow_html=True)

if uploaded and run_btn:

    _log_init()
    _log_ph=st.empty()
    _log_render(_log_ph)

    is_pdf=uploaded.type=="application/pdf"
    suffix=".pdf" if is_pdf else Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as tmp:
        tmp.write(uploaded.read()); tmp_path=tmp.name

    file_kb=round(len(uploaded.getvalue())/1024,1)
    _log_set("load","done",f"{uploaded.name}  ({file_kb} KB)"); _log_render(_log_ph)

    if is_pdf:
        _log_set("detect","running","reading PDF…"); _log_render(_log_ph)
        is_native  =detect_pdf_native(tmp_path)
        doc_fitz   =fitz.open(tmp_path)
        total_pages=len(doc_fitz)
        _log_set("detect","done",
                 f"{'Native' if is_native else 'Scanned'} PDF — {total_pages} page(s)")
        _log_render(_log_ph)
    else:
        is_native=False; total_pages=1
        _log_set("detect","done","Image file — 1 page"); _log_render(_log_ph)

    if is_pdf:
        c1,c2=st.columns([2,1])
        with c1:
            col="#7ee8a2" if is_native else "#e8c87e"
            st.markdown(f"<div class='metric-card'><div class='metric-label'>PDF type</div>"
                        f"<div class='metric-value' style='color:{col}'>"
                        f"{'📄 Native (digital)' if is_native else '📷 Scanned'}"
                        f"</div></div>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>Pages</div>"
                        f"<div class='metric-value'>{total_pages}</div></div>",
                        unsafe_allow_html=True)
    st.markdown("---")

    all_header_texts=[]; all_body_texts=[]; all_full_texts=[]
    all_clean_imgs  =[]; all_orig_imgs =[]
    all_header_clean_imgs = []
    all_header_layout_lines = []
    all_product_lines=[]; seen_codes=set()
    all_qty_trace = []
    prog=st.progress(0,text="Processing pages…")

    for page_i in range(total_pages):

        _log_set("preprocess","running",
                 f"page {page_i+1}/{total_pages}  DPI={dpi_choice}  "
                 f"rotation={use_fix_rotation}  color={use_erase_color}  "
                 f"lines={use_remove_lines}  blob={use_keep_mask}")
        _log_render(_log_ph)
        _pp_t0=_time.time()

        if is_pdf:
            img_bgr=pdf_page_to_image(tmp_path,page_i,dpi=dpi_choice)
        else:
            fb=np.frombuffer(uploaded.getvalue(),dtype=np.uint8)
            img_bgr=cv2.imdecode(fb,1)

        all_orig_imgs.append(cv2.cvtColor(img_bgr,cv2.COLOR_BGR2RGB))
        work=img_bgr.copy()
        if use_fix_rotation: work=fix_rotation(work)
        if use_erase_color:  work=erase_colored_ink(work)
        gray  =cv2.cvtColor(work,cv2.COLOR_BGR2GRAY)
        binary=binarize(gray)

        # Dual preprocessing:
        # - header_binary keeps box/border context for fragile identifiers (MF/RC/etc.)
        # - clean applies stronger cleanup for general OCR and products
        header_binary = binary.copy()
        if use_keep_mask:
            header_clean = enhance_kept_text(header_binary, build_keep_mask(header_binary))
        else:
            header_clean = header_binary

        if use_remove_lines:
            binary = remove_long_lines(binary)
        clean =enhance_kept_text(binary,build_keep_mask(binary)) if use_keep_mask else binary
        all_clean_imgs.append(clean)
        all_header_clean_imgs.append(header_clean)
        _log_set("preprocess","done",f"{total_pages} page(s) cleaned",t0=_pp_t0)
        _log_render(_log_ph)

        _log_set("ocr","running",
                 f"page {page_i+1}/{total_pages}  split={split_zones}  DPI={dpi_choice}")
        _log_render(_log_ph)
        _ocr_t0=_time.time()
        if split_zones:
            # Conservative header OCR preserves text near rectangles and border lines.
            h_text_soft = clean_ocr_text(ocr_header_zone(header_clean))
            h_text_std = clean_ocr_text(ocr_header_zone(clean))
            h_text = clean_ocr_text((h_text_soft + "\n" + h_text_std).strip())
            if page_i == 0:
                all_header_layout_lines = ocr_header_layout_lines(header_clean)
            b_text=clean_ocr_text(ocr_body_zone(clean))
            f_text=clean_ocr_text((h_text + "\n" + b_text).strip())
        else:
            f_text=clean_ocr_text(ocr_full_page(clean))
            h_text=b_text=f_text
        all_header_texts.append(h_text)
        all_body_texts.append(b_text)
        all_full_texts.append(f_text)
        _log_set("ocr","done",
                 f"{total_pages} page(s)  {len(f_text.split())} words",t0=_ocr_t0)
        _log_render(_log_ph)

        _log_set("products","running",f"page {page_i+1}/{total_pages}"); _log_render(_log_ph)
        if show_products:
            page_items, page_qty_trace = extract_product_lines(b_text)
            all_qty_trace.extend(page_qty_trace)
            for item in page_items:
                code=item.get("code","")
                if code and code not in seen_codes:
                    seen_codes.add(code); all_product_lines.append(item)
                elif not code:
                    all_product_lines.append(item)
        _log_set("products","done",f"{len(all_product_lines)} item(s)"); _log_render(_log_ph)
        prog.progress((page_i+1)/total_pages,text=f"Page {page_i+1}/{total_pages}…")

    prog.empty()
    combined_full  ="\n\n".join(all_full_texts)
    combined_header="\n\n".join(all_header_texts)

    plumber_tables=[]
    if is_pdf and is_native and show_tables:
        _log_set("pdfplumber","running","reading vector tables…"); _log_render(_log_ph)
        _pl_t0=_time.time()
        with st.spinner("Extracting tables…"):
            plumber_tables=extract_tables_pdfplumber(tmp_path)
        _log_set("pdfplumber","done",f"{len(plumber_tables)} table(s)",t0=_pl_t0)
        _log_render(_log_ph)
    else:
        reason=("scanned PDF" if (is_pdf and not is_native)
                else "image file" if not is_pdf else "disabled")
        _log_set("pdfplumber","skip",reason); _log_render(_log_ph)

    _log_set("regex","running",f"{len(combined_full.split())} words"); _log_render(_log_ph)
    _rx_t0=_time.time()
    # Pass header_text so MF search stays in fournisseur zone (top-left)
    regex_info, extraction_trace = extract_info(combined_full, combined_header, all_header_layout_lines)
    extraction_trace["quantity"] = {
        "missing_count": len(all_qty_trace),
        "missing_examples": all_qty_trace[:20]
    }
    _log_set("regex","done",
             f"type={regex_info.get('type','?')}  date={regex_info.get('date','—')}  "
             f"fields={len(regex_info)}",t0=_rx_t0)
    _log_render(_log_ph)

    confidence={}; warnings_nlp=[]; extracted_info=regex_info

    if use_nlp:
        _log_set("nlp","running",
                 f"model={nlp_model_name}  NER·fuzzy·date…"); _log_render(_log_ph)
        _nlp_t0=_time.time()
        extracted_info,confidence,warnings_nlp=nlp_enrich(
            regex_info,combined_full,combined_header,nlp_model)
        filled=sum(1 for k in extracted_info if k not in regex_info)
        fixed =len([w for w in warnings_nlp if "corrected" in w or "NLP" in w])
        status="warn" if warnings_nlp else "done"
        _log_set("nlp",status,
                 f"+{filled} filled  {fixed} corrected  {len(warnings_nlp)} warn",t0=_nlp_t0)
        _log_render(_log_ph)
    else:
        _log_set("nlp","skip","disabled"); _log_render(_log_ph)

    _log_set("done","done",
             f"{total_pages} page(s) · {len(all_product_lines)} items · "
             f"{len(plumber_tables)} tables · {len(warnings_nlp)} NLP warn")
    _log_render(_log_ph)

    # ── Display pages ─────────────────────────────────────────────────
    st.markdown("## 🖼️ Pages — Original & Cleaned")
    for page_i,(orig,clean) in enumerate(zip(all_orig_imgs,all_clean_imgs)):
        label=f"Page {page_i+1}/{total_pages}" if total_pages>1 else "Document"
        st.markdown(f"<div class='page-label'>{label}</div>",unsafe_allow_html=True)
        c1,c2=st.columns(2)
        with c1:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#888;"
                        "text-align:center;margin-bottom:4px'>📷 Original</div>",
                        unsafe_allow_html=True)
            st.image(orig,use_container_width=True)
        with c2:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#7ee8a2;"
                        "text-align:center;margin-bottom:4px'>✨ After Cleaning</div>",
                        unsafe_allow_html=True)
            st.image(clean,use_container_width=True)
        if page_i<len(all_clean_imgs)-1:
            st.markdown("<hr style='border-color:#1e2130;margin:12px 0;'>",unsafe_allow_html=True)

    st.markdown("---")

    dtype    =extracted_info.get("type","Document")
    tag_class={"Bon de Commande":"tag-bc","Proforma":"tag-proforma",
               "Facture":"tag-facture"}.get(dtype,"tag-stat")
    st.markdown(f"<span class='{tag_class}'>{dtype}</span>",unsafe_allow_html=True)
    st.markdown("## 📋 Extracted Information")

    if show_conf:
        st.markdown(
            "<div class='conf-hint'>"
            "🟢 ≥80% reliable &nbsp;·&nbsp; 🟡 55–79% double-check &nbsp;·&nbsp; "
            "🔴 &lt;55% likely wrong"
            "</div>", unsafe_allow_html=True)

    if show_warnings and warnings_nlp:
        ih="".join(f"<li>{w}</li>" for w in warnings_nlp)
        st.markdown(
            f"<div class='warn-box'>⚠ <strong>Validation warnings</strong><ul>{ih}</ul></div>",
            unsafe_allow_html=True)

    # All cards in one HTML block — no raw-tag bug
    fields_to_show=[
        ("Type de document", "type",            extracted_info.get("type",            "—")),
        ("Document N°",      "numero",           extracted_info.get("numero",          "—")),
        ("Date",             "date",             extracted_info.get("date",            "—")),
        ("Supplier MF",      "supplier_mf",      extracted_info.get("supplier_mf",     "—")),
        ("Client MF",        "client_mf",        extracted_info.get("client_mf",       "—")),
        ("Matricule Fiscal", "matricule_fiscal", extracted_info.get("matricule_fiscal","—")),
        ("Téléphone",        "tel",              extracted_info.get("tel",             "—")),
        ("Fax",              "fax",              extracted_info.get("fax",             "—")),
        ("Email",            "email",            extracted_info.get("email",           "—")),
        ("RC",               "rc",               extracted_info.get("rc",              "—")),
        ("Total HT",         "total_ht",         extracted_info.get("total_ht",        "—")),
        ("Total TTC",        "total_ttc",        extracted_info.get("total_ttc",       "—")),
    ]
    render_info_grid(fields_to_show, confidence, show_conf)

    if extracted_info.get("adresse"):
        conf_a=confidence.get("adresse")
        badge_a=_conf_badge_html(conf_a) if (show_conf and conf_a is not None) else ""
        st.markdown(
            f"<div class='metric-card addr-card'>{badge_a}"
            f"<div class='metric-label'>Adresse</div>"
            f"<div class='metric-value addr-val'>{extracted_info['adresse']}</div>"
            f"</div>", unsafe_allow_html=True)

    if show_products and all_product_lines:
        st.markdown(f"## 📦 Product Lines ({len(all_product_lines)} items)")
        tbl=("<div class='table-container'><table><thead><tr>"
             "<th>#</th><th>Code</th><th>Designation</th><th>Qty</th>"
             "</tr></thead><tbody>")
        for i,item in enumerate(all_product_lines,1):
            qty=item.get("quantite","—")
            qs=f"{qty:.0f}" if isinstance(qty,float) else str(qty)
            tbl+=(f"<tr><td style='color:#555'>{i}</td>"
                  f"<td style='color:#7ee8a2'>{item.get('code','')}</td>"
                  f"<td>{item.get('designation','')}</td>"
                  f"<td style='text-align:right;color:#e8c87e'>{qs}</td></tr>")
        tbl+="</tbody></table></div>"
        st.markdown(tbl,unsafe_allow_html=True)
    elif show_products:
        st.info("No product lines detected. Enable 'Show Raw OCR Text' to debug.")

    if plumber_tables:
        st.markdown(f"## 🗃️ pdfplumber Tables ({len(plumber_tables)} found)")
        for t_idx,table in enumerate(plumber_tables):
            if not table: continue
            st.markdown(f"**Table {t_idx+1}**")
            tbl="<div class='table-container'><table><thead><tr>"
            for h in table[0]:
                tbl+=f"<th>{str(h).replace('&','&amp;').replace('<','&lt;')}</th>"
            tbl+="</tr></thead><tbody>"
            for row in table[1:]:
                if any(str(c).strip() for c in row):
                    tbl+="<tr>"
                    for cell in row:
                        tbl+=f"<td>{str(cell).replace('&','&amp;').replace('<','&lt;')}</td>"
                    tbl+="</tr>"
            tbl+="</tbody></table></div>"
            st.markdown(tbl,unsafe_allow_html=True)

    if show_raw:
        st.markdown("## 📝 Raw OCR Text")
        for page_i in range(total_pages):
            label=f"Page {page_i+1}" if total_pages>1 else "Full text"
            with st.expander(label,expanded=(page_i==0)):
                if split_zones:
                    c1,c2=st.columns(2)
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

    if show_json:
        st.markdown("## 🗂️ Full JSON")
        st.json({
            "informations_document": extracted_info,
            "confidence":            confidence,
            "validation_warnings":   warnings_nlp,
            "extraction_trace":      extraction_trace,
            "ligne_articles":        all_product_lines,
            "nlp_model":             nlp_model_name,
        })

    if show_trace:
        st.markdown("## 🧭 Extraction Trace")
        st.caption("Candidate ranking used for MF and key numeric fields.")
        st.json(extraction_trace)

    st.markdown("---")
    c1,c2=st.columns(2)
    with c1:
        st.download_button(
            "⬇ Download JSON",
            data=json.dumps({
                "informations_document": extracted_info,
                "confidence":            confidence,
                "validation_warnings":   warnings_nlp,
                "extraction_trace":      extraction_trace,
                "ligne_articles":        all_product_lines,
                "nlp_model":             nlp_model_name,
            },ensure_ascii=False,indent=2),
            file_name=f"{Path(uploaded.name).stem}_extracted.json",
            mime="application/json",use_container_width=True)
    with c2:
        st.download_button(
            "⬇ Download OCR Text",
            data=combined_full,
            file_name=f"{Path(uploaded.name).stem}_ocr.txt",
            mime="text/plain",use_container_width=True)

    try: os.unlink(tmp_path)
    except: pass