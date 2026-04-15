"""
<<<<<<< HEAD
Invoice OCR Pipeline — Streamlit App v5-final
SE24D2 — Automated Invoice Intelligence System

Integrates invoice_extractor_v2.py for:
  - Dynamic table mapping with bounding boxes (solves Qty/Designation merge)
  - Matricule Fiscale top-left rule
  - Document number below "Bon de commande" title
=======
Invoice OCR Pipeline — v4.4
════════════════════════════
v4.4:
  • Doc type: NLP no longer overwrites a specific regex type (e.g. Bon de Commande).
  • MF: search full page-1 text; no truncation at Code FRS (fixes wrong/missing MF when
    OCR column order differs); OCR confusions i:/l: for M.F; back-fill for JSON/UI.
  • Product lines: parsed from full-page OCR per page (not body-only) so table rows in
    the top band are not dropped; 5–8 digit numeric codes; qty fallback from line ints.
v4.3: title-adjacent doc N°; MF compact form; product dedupe relaxed; header crop.
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
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

<<<<<<< HEAD
st.set_page_config(page_title="Invoice OCR Pipeline", page_icon="🔬",
                   layout="wide", initial_sidebar_state="expanded")
=======

# ═══════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Invoice OCR Pipeline",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
    code, .stCode, pre { font-family: 'JetBrains Mono', monospace !important; }
    .stApp { background: #0f1117; color: #e8e8e2; }
<<<<<<< HEAD
    h1 { font-family:'Syne';font-weight:700;letter-spacing:-1px;color:#f0f0ea; }
    h2,h3 { font-family:'Syne';font-weight:600;color:#d4d4ce; }
    .metric-card{background:#1a1d26;border:1px solid #2a2d3a;border-radius:8px;padding:16px 20px;margin:6px 0;}
    .metric-label{font-size:11px;color:#666;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;}
    .metric-value{font-family:'JetBrains Mono';font-size:18px;font-weight:600;color:#7ee8a2;}
    .tag-bc{background:#1a3a2a;color:#7ee8a2;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #2a5a3a;}
    .tag-proforma{background:#1a2a3a;color:#7ec8e8;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #2a4a5a;}
    .tag-facture{background:#3a2a1a;color:#e8c87e;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #5a4a2a;}
    .tag-stat{background:#2a1a3a;color:#c87ee8;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #4a2a5a;}
    div[data-testid="stSidebar"]{background:#13151f;border-right:1px solid #1e2130;}
    .stButton>button{background:#7ee8a2;color:#0f1117;border:none;font-family:'Syne';font-weight:700;
                     letter-spacing:0.5px;padding:10px 28px;border-radius:6px;width:100%;transition:all 0.2s;}
    .stButton>button:hover{background:#a0f0b8;transform:translateY(-1px);}
    .raw-text{background:#1a1d26;border:1px solid #2a2d3a;border-radius:8px;padding:16px;
              font-family:'JetBrains Mono';font-size:11px;color:#b0b0a8;
              max-height:400px;overflow-y:auto;white-space:pre-wrap;}
    .table-container{overflow-x:auto;}
    table{width:100%;border-collapse:collapse;font-size:12px;font-family:'JetBrains Mono';}
    th{background:#1e2130;color:#7ee8a2;padding:8px 12px;text-align:left;border-bottom:1px solid #2a2d3a;font-weight:600;}
    td{padding:7px 12px;border-bottom:1px solid #1e2130;color:#c8c8c2;vertical-align:top;}
    tr:hover td{background:#1a1d26;}
    .page-label{font-family:'Syne';font-size:12px;color:#555;text-transform:uppercase;letter-spacing:1px;margin:12px 0 4px 0;}
    .pl-wrap{background:#0d0f17;border:1px solid #1e2130;border-radius:10px;padding:14px 16px;margin-bottom:12px;}
    .pl-title{font-family:'Syne';font-size:11px;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px;}
    .pl-step{display:flex;align-items:flex-start;gap:10px;padding:7px 0;border-bottom:1px solid #141720;}
    .pl-step:last-child{border-bottom:none;}
    .pl-icon{font-size:13px;flex-shrink:0;width:18px;text-align:center;margin-top:1px;}
    .pl-info{flex:1;min-width:0;}
    .pl-name{font-family:'Syne';font-size:12px;}
    .pl-detail{font-family:'JetBrains Mono';font-size:10px;color:#445;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .pl-time{font-family:'JetBrains Mono';font-size:10px;color:#445;flex-shrink:0;padding-left:8px;align-self:center;}
    .s-pending .pl-name{color:#383c50;} .s-running .pl-name{color:#7ee8a2;}
    .s-done .pl-name{color:#c8c8c2;} .s-skip .pl-name{color:#333849;font-style:italic;}
    .s-warn .pl-name{color:#e8c87e;}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE LOG
# ─────────────────────────────────────────────────────────────────────────────

_STEPS = [
    ("load",        "📂", "Load file"),
    ("detect",      "🔍", "Detect PDF type"),
    ("preprocess",  "🧹", "Preprocess image(s)"),
    ("ocr",         "🔤", "OCR text extraction"),
    ("pdfplumber",  "📊", "pdfplumber tables"),
    ("regex",       "🔎", "Regex field extraction"),
    ("products",    "📦", "Product line extraction"),
    ("bbox_table",  "🧮", "BBox table extraction"),
    ("s3_spacy",    "🧠", "SpaCy NER extraction"),
    ("s3_layoutlm", "🗺️",  "LayoutLM visual extraction"),
    ("s3_scoring",  "📊", "Confidence scoring"),
    ("done",        "✅", "Pipeline complete"),
]

def _log_init():
    st.session_state["_pl"] = {k:{"status":"pending","detail":"","t":""} for k,*_ in _STEPS}

def _log_set(key, status, detail="", t0=0.0):
    if "_pl" not in st.session_state: _log_init()
    elapsed=""
    if status=="done" and t0:
        ms=int((_time.time()-t0)*1000)
        elapsed=f"{ms}ms" if ms<1000 else f"{ms/1000:.1f}s"
    st.session_state["_pl"][key]={"status":status,"detail":detail,"t":elapsed}

def _log_render(ph):
    if "_pl" not in st.session_state: return
    pl=st.session_state["_pl"]
    icons={"pending":"○","running":"⏳","done":"✓","skip":"–","warn":"⚠"}
    html="<div class='pl-wrap'><div class='pl-title'>⚡ Pipeline</div>"
    for key,_,label in _STEPS:
        s=pl.get(key,{"status":"pending","detail":"","t":""})
        st_=s["status"]
        html+=(f"<div class='pl-step s-{st_}'><span class='pl-icon'>{icons.get(st_,'○')}</span>"
               f"<div class='pl-info'><div class='pl-name'>{label}</div>"
               +(f"<div class='pl-detail'>{s['detail']}</div>" if s['detail'] else "")
               +"</div>"+(f"<span class='pl-time'>{s['t']}</span>" if s['t'] else "")+"</div>")
    html+="</div>"
=======
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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
    ph.markdown(html, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# KNOWN SUPPLIERS
# ─────────────────────────────────────────────────────────────────────────────

<<<<<<< HEAD
KNOWN_SUPPLIERS = [
    "MEDIS","OPALIA","PHARMANOVA","ADWYA","SIPHAT","UNIMED","SAIPH",
    "PHYTO-THER","COFAT","STIP","SOTUVER","SOTUMAG","SOTACIB","SOTETEL",
    "SOPAL","DELICE","SFBT","POULINA","TUNISAIR","TOPNET",
]

# ─────────────────────────────────────────────────────────────────────────────
# PREPROCESSING
# ─────────────────────────────────────────────────────────────────────────────

def fix_rotation(img_bgr):
    major_rotated=False
    try:
        gray_temp=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2GRAY)
        osd=pytesseract.image_to_osd(gray_temp,config="--psm 0 -c min_characters_to_try=5")
        angle_m=re.search(r"Rotate: (\d+)",osd)
        conf_m=re.search(r"Orientation confidence: ([\d\.]+)",osd)
        confidence=float(conf_m.group(1)) if conf_m else 0.0
        if angle_m and confidence>=3.5:
            a=int(angle_m.group(1))
            if a==90:   img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_90_COUNTERCLOCKWISE);major_rotated=True
            elif a==180:img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_180);major_rotated=True
            elif a==270:img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_90_CLOCKWISE);major_rotated=True
    except: pass
    if not major_rotated:
        gray=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2GRAY)
        coords=np.column_stack(np.where(gray<200))
        if len(coords)>=500:
            angle=cv2.minAreaRect(coords)[-1]
            if angle<-45: angle=90+angle
            if 0.3<=abs(angle)<=3.0:
                h,w=gray.shape
                M=cv2.getRotationMatrix2D((w//2,h//2),angle,1.0)
                img_bgr=cv2.warpAffine(img_bgr,M,(w,h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE)
    h_f,w_f=img_bgr.shape[:2]
    if w_f>h_f: img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_90_COUNTERCLOCKWISE)
=======
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

    # 1. Doc type — keep regex classification when it is specific; NLP often
    #    mislabels invoices (e.g. Bon de commande → Proforma) and must not erase type.
    nlp_type, type_conf = _fuzzy_doc_type(text)
    regex_type = regex_info.get("type", "Document")
    if regex_type == "Document" and nlp_type != "Document":
        enriched["type"] = nlp_type
        confidence["type"] = type_conf
    elif nlp_type == regex_type:
        confidence["type"] = max(type_conf, 0.90)
    else:
        if regex_type != "Document":
            enriched["type"] = regex_type
            confidence["type"] = max(0.88, type_conf * 0.5)
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

    # 5. Matricule fiscal
    mf = enriched.get("matricule_fiscal","")
    if mf:
        if re.match(r'^\d{6,8}[A-Z]/[A-Z]/[A-Z]/\d{3}$', mf):
            confidence["matricule_fiscal"] = 0.98
        else:
            confidence["matricule_fiscal"] = 0.55
            warnings.append(f"Matricule fiscal format unusual: '{mf}'")
    else:
        confidence["matricule_fiscal"] = 0.0

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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
    return img_bgr

def erase_colored_ink(img_bgr):
<<<<<<< HEAD
    hsv=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2HSV)
    gray=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2GRAY)
    result=img_bgr.copy()
    color_mask=cv2.inRange(hsv,np.array([0,25,40]),np.array([180,255,255]))
    k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
    color_mask=cv2.dilate(color_mask,k,iterations=1)
    dark=(gray<100)
    result[(color_mask>0)&~dark]=[230,230,230]
    result[(color_mask>0)&dark]=[0,0,0]
=======
    hsv    = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    result = img_bgr.copy()
    cm = cv2.inRange(hsv, np.array([0,25,40]), np.array([180,255,255]))
    k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
    cm = cv2.dilate(cm, k, iterations=1)
    dark = (gray < 100)
    result[(cm>0) & ~dark] = [230,230,230]
    result[(cm>0) &  dark] = [0,0,0]
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
    return result

def binarize(gray):
    return cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY,blockSize=25,C=8)
<<<<<<< HEAD

def remove_long_lines(binary):
    inverted=cv2.bitwise_not(binary)
    h_k=cv2.getStructuringElement(cv2.MORPH_RECT,(80,1))
    v_k=cv2.getStructuringElement(cv2.MORPH_RECT,(1,80))
    lines_mask=cv2.add(cv2.morphologyEx(inverted,cv2.MORPH_OPEN,h_k),
                       cv2.morphologyEx(inverted,cv2.MORPH_OPEN,v_k))
    num_labels,labels,stats,_=cv2.connectedComponentsWithStats(inverted,8)
    text_protect=np.zeros_like(binary)
    for i in range(1,num_labels):
        bw=stats[i,cv2.CC_STAT_WIDTH]; bh=stats[i,cv2.CC_STAT_HEIGHT]; ar=stats[i,cv2.CC_STAT_AREA]
        if 5<=bw<=120 and 5<=bh<=120 and 20<=ar<=8000: text_protect[labels==i]=255
    pk=cv2.getStructuringElement(cv2.MORPH_RECT,(3,3))
    text_protect=cv2.dilate(text_protect,pk,iterations=1)
    safe=cv2.bitwise_and(lines_mask,cv2.bitwise_not(text_protect))
    inverted[safe>0]=0
    return cv2.bitwise_not(inverted)
=======


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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

def stroke_cv(blob):
    ek=cv2.getStructuringElement(cv2.MORPH_CROSS,(3,3))
    cur,counts=blob.copy(),[]
    for _ in range(15):
        cur=cv2.erode(cur,ek); n=cv2.countNonZero(cur); counts.append(n)
        if n==0: break
    if len(counts)<2: return 999.0
    nz=np.array(counts,dtype=float); nz=nz[nz>0]
    return float(np.std(nz)/(np.mean(nz)+1e-5)) if len(nz) else 999.0
<<<<<<< HEAD

def build_keep_mask(binary):
    inverted=cv2.bitwise_not(binary)
    num_labels,labels,stats,_=cv2.connectedComponentsWithStats(inverted,8)
    keep_mask=np.zeros_like(binary)
    for i in range(1,num_labels):
        bx=stats[i,cv2.CC_STAT_LEFT]; by=stats[i,cv2.CC_STAT_TOP]
        bw=stats[i,cv2.CC_STAT_WIDTH]; bh=stats[i,cv2.CC_STAT_HEIGHT]
        area=stats[i,cv2.CC_STAT_AREA]
        aspect=max(bw,bh)/(min(bw,bh)+1e-5)
        if area<15 or area>15000: continue
        if aspect>20 and area>200: continue
        if area<80: keep_mask[labels==i]=255; continue
        if area>3000:
            if area/(bw*bh+1e-5)>0.15: keep_mask[labels==i]=255
            continue
        if area/(bw*bh+1e-5)<0.12: continue
        blob=(labels[by:by+bh,bx:bx+bw]==i).astype(np.uint8)*255
        if stroke_cv(blob)<1.5: keep_mask[labels==i]=255
    return keep_mask

def enhance_kept_text(binary,keep_mask):
    ek=cv2.getStructuringElement(cv2.MORPH_RECT,(2,2))
    km=cv2.dilate(keep_mask,ek,iterations=1)
    result=np.full_like(binary,255); result[km>0]=0
    return result
=======


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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────

<<<<<<< HEAD
def ocr_full_page(c):
    return pytesseract.image_to_string(c,lang="fra+eng",config="--psm 6 --oem 1").strip()

def ocr_header_zone(c):
    h=c.shape[0]
    return pytesseract.image_to_string(c[:int(h*.25),:],lang="fra+eng",config="--psm 4 --oem 1").strip()

def ocr_body_zone(c):
    h=c.shape[0]
    return pytesseract.image_to_string(c[int(h*.22):int(h*.88),:],lang="fra+eng",config="--psm 6 --oem 1").strip()

def ocr_footer_zone(c):
    h=c.shape[0]
    return pytesseract.image_to_string(c[int(h*.75):,:],lang="fra+eng",config="--psm 6 --oem 1").strip()
=======
# ═══════════════════════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════════════════════

def ocr_full_page(img):
    return pytesseract.image_to_string(img, lang="fra+eng", config="--psm 6 --oem 1").strip()

def ocr_header_zone(img):
    h=img.shape[0]
    # Top ~38%: keeps centered doc title + line below (e.g. "445 / 2023") and
    # fournisseur M.F. under the address without pushing too far into the table.
    return pytesseract.image_to_string(img[:int(h * 0.38), :],
                                       lang="fra+eng", config="--psm 4 --oem 1").strip()

def ocr_body_zone(img):
    h=img.shape[0]
    return pytesseract.image_to_string(img[int(h*0.20):int(h*0.92),:],
                                       lang="fra+eng", config="--psm 6 --oem 1").strip()
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

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
<<<<<<< HEAD
        alnum=len(re.findall(r'[A-Za-z0-9]',s)); total=len(s)
=======
        alnum=len(re.findall(r'[A-Za-z0-9]',s))
        total=len(s)
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
        if alnum<3: continue
        if 1-alnum/(total+1e-5)>0.60: continue
        if not re.search(r'[A-Za-z]{3,}|\d',s): continue
        lines.append(s)
    return "\n".join(lines)

<<<<<<< HEAD
# ─────────────────────────────────────────────────────────────────────────────
# PDFPLUMBER
# ─────────────────────────────────────────────────────────────────────────────
=======

# ═══════════════════════════════════════════════════════════════════════════
# TABLE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

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

<<<<<<< HEAD
# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(s):
    if not s: return None
    s=str(s).strip()
    s=re.sub(r'[€$£\s]','',s)
    s=re.sub(r'[^\d,.]','',s)
    if not s: return None
    dot_p=s.split('.')
    if '.' in s and ',' not in s:
        if len(dot_p)>2: s=s.replace('.','')
        elif len(dot_p)==2 and len(dot_p[1])==3: s=s.replace('.','')
    elif ',' in s and '.' in s:
        if s.rfind('.')>s.rfind(','): s=s.replace(',','')
        else: s=s.replace('.','').replace(',','.')
    elif ',' in s:
        p=s.split(',')
        if len(p)==2 and len(p[1])<=3: s=s.replace(',','.')
        else: s=s.replace(',','')
    try: return round(float(s),3)
    except: return None

DOC_TYPES={
    "Proforma":["proforma","b.c. interne","incoterms","date/heure livraison"],
    "Bon de Commande":["bon de commande","commande fournisseur","bcn-","bc n°"],
    "Facture":["facture","invoice","facture numéro"],
    "Bon de Livraison":["bon de livraison","bl n°","n° bl"],
    "Statistiques":["statistique","quantitatif des ventes","stat. ventes","quantité proposée"],
    "Chiffre d'Affaires":["chiffre d'affaire","ventes et chiffre"],
}

def detect_doc_type(text):
    tl=text.lower()
    for dtype,kws in DOC_TYPES.items():
        if any(k in tl for k in kws): return dtype
    return "Document"

_ADDR_ANCHOR=re.compile(
    r'\b(route|rue|avenue|av\.?|bd\.?|boulevard|cit[eé]|zone\s+ind'
    r'|lot\s+n?[°o]?|lotissement|impasse|r[eé]sidence|quartier|km\s*\d'
    r'|n[°o]\s*\d{1,4}\s+(?:rue|route|av))\b',re.IGNORECASE)

def extract_address(header_text):
    lines=[l.strip() for l in header_text.splitlines() if l.strip()]
    found=[]; in_block=False
    for line in lines:
        if _ADDR_ANCHOR.search(line): found.append(line); in_block=True
        elif in_block:
            is_label=re.match(r'^(tel|fax|m\.?f|r\.?c|sfax|tunis|nabeul|sousse'
                              r'|date|page|code|email|prépar|edité)',line,re.I)
            if not is_label and 6<len(line)<120: found.append(line)
            in_block=False
    return " — ".join(found) if found else ""

def extract_supplier(header_text,full_text):
    for name in KNOWN_SUPPLIERS:
        if name.upper() in header_text.upper(): return name
        if name.upper() in full_text.upper()[:500]: return name
    m=re.search(r'(?:fournisseur|supplier|vendeur)\s*[:\-]\s*(.+)',header_text,re.I)
    if m:
        c=m.group(1).strip().split('\n')[0].strip()
        if 3<len(c)<80: return c
    cpat=re.compile(r'\b(SARL|SA\b|SPA|SUARL|SOCIÉTÉ|SOCIETE|GROUP|HOLDING)\b',re.I)
    for line in header_text.splitlines()[:15]:
        line=line.strip()
        if not line or len(line)<4 or len(line)>90: continue
        if _ADDR_ANCHOR.search(line): break
        if cpat.search(line): return line
    return ""

_MF_PAT=re.compile(
    r'\b(\d{6,8})[/\\|\s]?([A-Z])[/\\|\s]?([A-Z])[/\\|\s]?([A-Z])[/\\|\s]?(\d{3})\b',
    re.IGNORECASE)

def _parse_mf(m):
    d1,l1,l2,l3,d2=(m.group(1),m.group(2).upper(),m.group(3).upper(),
                    m.group(4).upper(),m.group(5))
    return f"{d1}{l1}/{l2}/{l3}/{d2}" if 6<=len(d1)<=8 and len(d2)==3 else None

def extract_doc_number(text):
    for pat in [
        r'N[°o]\s*(?:Commande|Facture|BL|Livraison|Proforma|Cmd|Cde)\s*[:\-]?\s*([A-Z]{2,5}-\d{2,4}\/\d{3,6})',
        r'N[°o]\s*(?:Commande|Facture|BL|Livraison|Proforma|Cmd|Cde)\s*[:\-]?\s*(\d{2,6}\/\d{2,6})',
        r'N[°o]\s*(?:Commande|Facture|BL|Livraison|Proforma|Cmd|Cde)\s*[:\-]?\s*(\d{2,4})\b',
        r'N[°o]\s*:\s*([A-Z]{2,5}-\d{2,4}\/\d{3,6})',
        r'N[°o]\s*:\s*(\d{2,6}\/\d{2,6})',
        r'N[°o]\s*:\s*(\d{2,6})\b',
        r'(?:Bon\s+de\s+commande|Bon\s+de\s+livraison|Facture|Proforma|Avoir)'
        r'[^\n]{0,50}[\r\n]+\s*(?:N[°o][°\s:]*)?([A-Z]{0,5}-?\d{2,6}\/\d{3,6})',
        r'\b(CDA-\d{2}\/\d{4,6})\b',
        r'\b(BCN-\d{2}-\d{4})\b',
        r'\b(BCM?-\d{2}-\d{4})\b',
        r'N[°o][:\s]+([A-Z0-9][A-Z0-9\-\/]{2,20})',
    ]:
        m=re.search(pat,text,re.IGNORECASE|re.MULTILINE)
        if m:
            num=re.sub(r'\s+','',m.group(1)).strip(".,;:")
            if len(num)>=2: return num
    return None

def extract_totals_from_footer(ft):
    res={}
    for pats,key in [
        ([r'Total\s+H\.T\.?\s*[:\-]?\s*([\d][\d\s\.\,]+)',
          r'Total\s+HT\s*[:\-]?\s*([\d][\d\s\.\,]+)',
          r'Total\s+Hors\s+Taxe\s*[:\-]?\s*([\d][\d\s\.\,]+)',
          r'Montant\s+HT\s*[:\-]?\s*([\d][\d\s\.\,]+)',
          r'Total\s+Net\s+HT\s*[:\-]?\s*([\d][\d\s\.\,]+)'], "total_ht"),
        ([r'T\.?V\.?A\.?\s*(?:\d{1,2}\s*%\s*)?[:\-]?\s*([\d][\d\s\.\,]+)',
          r'Valeur\s+TVA\s*[:\-]?\s*([\d][\d\s\.\,]+)'], "tva"),
        ([r'Total\s+T\.?T\.?C\.?\s*[:\-]?\s*([\d][\d\s\.\,]+)',
          r'Net\s+[àa]\s+[Pp]ayer\s*[:\-]?\s*([\d][\d\s\.\,]+)',
          r'Montant\s+TTC\s*[:\-]?\s*([\d][\d\s\.\,]+)'], "total_ttc"),
    ]:
        for pat in pats:
            m=re.search(pat,ft,re.IGNORECASE)
            if m:
                val=_to_float(m.group(1).strip())
                if val and val>0: res[key]=val; break
    return res

def extract_info(text, header_text=None, footer_text=None):
    info={"type":detect_doc_type(text)}
    num=extract_doc_number(text)
    if num: info["numero"]=num
    m=re.search(r'Date\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',text,re.I)
    if not m: m=re.search(r'\b(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})\b',text)
    if m: info["date"]=m.group(1)
    mf_m=None
    if header_text:
        hm=list(_MF_PAT.finditer(header_text))
        if hm: mf_m=hm[0]
    if mf_m is None:
        fm=list(_MF_PAT.finditer(text))
        if fm: mf_m=fm[0]
    if mf_m:
        v=_parse_mf(mf_m)
        if v: info["matricule_fiscal"]=v
    m=re.search(r'T[eé]l[:\.\s/]*(\d[\d\s\.\-]{6,14}\d)',text,re.I)
    if m: info["tel"]=re.sub(r'[\s\.\-]','',m.group(1))
    m=re.search(r'Fax[:\.\s]*([\d][\d\s\.\-]{6,14}\d)',text,re.I)
    if m: info["fax"]=re.sub(r'[\s\.\-]','',m.group(1))
    m=re.search(r'[\w\.-]+@[\w\.-]+\.\w{2,}',text)
    if m: info["email"]=m.group(0)
    m=re.search(r'R\.?C\.?\s*[:\-]?\s*([A-Z][A-Z0-9]{5,14})',text,re.I)
    if m: info["rc"]=m.group(1)
    addr=extract_address(header_text or text)
    if addr: info["adresse"]=addr
    totals=extract_totals_from_footer(footer_text) if footer_text else {}
    if not totals.get("total_ht") or not totals.get("total_ttc"):
        last=text[-2000:] if len(text)>2000 else text
        for k,v in extract_totals_from_footer(last).items():
            if k not in totals: totals[k]=v
    info.update(totals)
    return {k:v for k,v in info.items() if v not in (None,"",0)}

# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT LINE EXTRACTION — text-based (fallback when bbox table fails)
# ─────────────────────────────────────────────────────────────────────────────

PRICE_PAT=re.compile(r'\b\d{1,10}[,\.]\d{2,3}\b')
CODE_PCT =re.compile(r'^([A-Z]{2,4}\d{2,12}|\d{5,8})',re.IGNORECASE)
=======

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


def _page1_block(combined: str) -> str:
    """First page OCR when pages are joined with \\n\\n."""
    if not combined:
        return ""
    parts = combined.split("\n\n")
    return parts[0].strip() if parts else combined.strip()


def _normalize_doc_num(raw: str) -> str:
    s = re.sub(r"\s+", "", (raw or "").strip())
    s = s.strip(".,;:")
    return s


def _is_plausible_doc_num(s: str) -> bool:
    if not s or len(s) < 5:
        return False
    m = re.fullmatch(r"(\d{1,6})/(\d{4})", s)
    if not m:
        return False
    year = int(m.group(2))
    return 1990 <= year <= 2035


def extract_numero_document(text: str) -> str:
    """
    Find document reference like 445/2023: often directly under the doc title,
    or on the same line (OCR layout varies). Ignores Page N°, Code PCT, etc.
    """
    head = text[:8000] if len(text) > 8000 else text

    # 1) Explicit labels (high precision)
    labeled = [
        r"(?:doc(?:ument)?|bon|facture|commande)\s+n[°o]\s*[:\s]*(\d{1,6}\s*/\s*\d{4})",
        r"r[ée]f(?:[ée]rence)?\.?\s*[:\s]*(\d{1,6}\s*/\s*\d{4})",
        r"n[°o]\s*(?:du\s+)?(?:bon|document|facture)\s*[:\s]*(\d{1,6}\s*/\s*\d{4})",
    ]
    for pat in labeled:
        m = re.search(pat, head, re.IGNORECASE)
        if m:
            n = _normalize_doc_num(m.group(1))
            if _is_plausible_doc_num(n):
                return n

    # 2) Title-adjacent: same line OR next 1–3 lines after a known heading
    title_rx = re.compile(
        r"(bon\s+de\s+(?:commande|livraison)|"
        r"facture(?:\s+d['’]?\s*accompagnement)?|"
        r"proforma|avoir|"
        r"note\s+de\s+(?:cr[eé]dit|d[eé]bit)|"
        r"commande\s+fournisseur)",
        re.IGNORECASE,
    )
    m = title_rx.search(head)
    if m:
        after = head[m.end() : m.end() + 220]
        # Same physical line (before newline)
        line0 = after.split("\n", 1)[0]
        for mm in re.finditer(r"\b(\d{1,6}\s*/\s*\d{4})\b", line0):
            if re.search(r"page|pct|code\s*pct", line0[: mm.start()], re.I):
                continue
            n = _normalize_doc_num(mm.group(1))
            if _is_plausible_doc_num(n):
                return n
        # Following lines (title often stacked above the number)
        chunk = after
        for mm in re.finditer(r"(?m)^\s*(\d{1,6}\s*/\s*\d{4})\s*$", chunk):
            ctx = chunk[max(0, mm.start() - 80) : mm.end() + 40]
            if re.search(r"page\s+n|code\s+pct|sfax\s+le", ctx, re.I):
                continue
            n = _normalize_doc_num(mm.group(1))
            if _is_plausible_doc_num(n):
                return n
        for mm in re.finditer(r"\b(\d{1,6}\s*/\s*\d{4})\b", chunk):
            ctx = chunk[max(0, mm.start() - 100) : mm.end() + 60]
            if re.search(r"page\s+n|code\s+pct|sfax\s+le", ctx, re.I):
                continue
            n = _normalize_doc_num(mm.group(1))
            if _is_plausible_doc_num(n):
                return n

    return ""


def _format_mf_from_groups(d1: str, l1: str, l2: str, l3: str, d2: str) -> str:
    return f"{d1}{l1.upper()}/{l2.upper()}/{l3.upper()}/{d2}"


def _mf_from_compact_match(m: re.Match) -> str:
    d1, letters, d2 = m.group(1), m.group(2).upper(), m.group(3)
    if len(letters) == 3 and len(d2) == 3 and 6 <= len(d1) <= 8:
        return _format_mf_from_groups(d1, letters[0], letters[1], letters[2], d2)
    return ""


def extract_supplier_matricule_fiscal(mf_zone: str) -> str:
    """
    Tunisian MF (fournisseur): compact/spaced forms. OCR order varies — do not
    truncate at 'Code FRS' (client block sometimes appears first in reading order).
    Prefer matches in text *before* the first 'Code FRS', else first valid MF line
    that is not on the same line as 'Code FRS'.
    """
    if not mf_zone:
        return ""

    # Spaced: M.F : 01286496 E / A / M / 000
    _MF_SPACED = re.compile(
        r"M\.?F\.?\s*[:\-]?\s*"
        r"(\d{6,8})[/\\|\s]?([A-Z])[/\\|\s]?([A-Z])[/\\|\s]?([A-Z])[/\\|\s]?(\d{3})\b",
        re.IGNORECASE,
    )
    _MF_COMPACT = re.compile(
        r"M\.?F\.?\s*[:\-]?\s*(\d{6,8})([A-Z]{3})(\d{3})\b",
        re.IGNORECASE,
    )
    # OCR reads M.F as I: / l: / 1: (common on scans)
    _MF_OCR_CONFUSE = re.compile(
        r"(?:^|[\s|])([iIl1])\s*[:\.;]\s*(\d{6,8})([A-Z]{3})(\d{3})\b",
        re.IGNORECASE,
    )
    _LOOSE = re.compile(
        r"M\.?F\.?\s*[:\-]?\s*([0-9A-Z]{10,18})\b",
        re.IGNORECASE,
    )

    def _try_line(ln: str) -> str:
        if re.search(r"\bcode\s+frs\b", ln, re.I):
            return ""
        m = _MF_SPACED.search(ln)
        if m:
            d1, a, b, c, d2 = (
                m.group(1),
                m.group(2),
                m.group(3),
                m.group(4),
                m.group(5),
            )
            if 6 <= len(d1) <= 8 and len(d2) == 3:
                return _format_mf_from_groups(d1, a, b, c, d2)
        m = _MF_COMPACT.search(ln)
        if m:
            s = _mf_from_compact_match(m)
            if s:
                return s
        m = _MF_OCR_CONFUSE.search(ln)
        if m:
            d1, letters, d2 = m.group(2), m.group(3).upper(), m.group(4)
            if len(letters) == 3 and len(d2) == 3 and 6 <= len(d1) <= 8:
                return _format_mf_from_groups(
                    d1, letters[0], letters[1], letters[2], d2
                )
        m = _LOOSE.search(ln)
        if m:
            raw = re.sub(r"[^0-9A-Za-z]", "", m.group(1))
            mc = re.fullmatch(r"(\d{6,8})([A-Z]{3})(\d{3})", raw, re.I)
            if mc:
                L = mc.group(2).upper()
                return f"{mc.group(1)}{L[0]}/{L[1]}/{L[2]}/{mc.group(3)}"
        return ""

    lines = [ln.strip() for ln in mf_zone.splitlines() if ln.strip()]
    cf_i = next(
        (i for i, ln in enumerate(lines) if re.match(r"^code\s+frs\b", ln, re.I)),
        None,
    )

    # 1) Lines strictly before first 'Code FRS' heading (supplier column)
    if cf_i is not None and cf_i > 0:
        for ln in lines[:cf_i]:
            got = _try_line(ln)
            if got:
                return got

    # 2) Any line (except same-line as Code FRS) — handles reversed column OCR
    for ln in lines:
        got = _try_line(ln)
        if got:
            return got

    # 3) Whole-text search before first 'Code FRS' substring (multiline layouts)
    cf_m = re.search(r"\bcode\s+frs\b", mf_zone, re.I)
    head = mf_zone[: cf_m.start()] if cf_m else mf_zone
    for rx in (_MF_COMPACT, _MF_SPACED):
        m = rx.search(head)
        if m:
            if rx is _MF_COMPACT:
                s = _mf_from_compact_match(m)
            else:
                s = _format_mf_from_groups(
                    m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
                )
            if s:
                return s
    return ""


def extract_info(text: str, header_text: str) -> dict:
    """
    Regex baseline.
    FIX 1: Doc N° also catches 'NNN/YYYY' on the line right below the doc-type heading.
            e.g.  "Bon de commande\n445 / 2023"  →  numero = "445/2023"
    FIX 2: MF searched in header_text only (top-left fournisseur block).
            This prevents picking up the CLIENT's MF from the right side of page 1.
    """
    info={}
    info["type"]=detect_doc_type(text)

    # Doc number — title-adjacent + labeled patterns first (see extract_numero_document).
    num = extract_numero_document(text)
    if num:
        info["numero"] = num
    if not info.get("numero"):
        for pat in [
            r"PROFORMA\s+N[°o][:\s]*([A-Z0-9\-]{6,25})",
            r"Commande\s+(?:Fournisseur\s+)?N[°o][:\s]*(\d{4,10})",
            r"N[°o]\s*Facture[:\s]*([A-Z0-9\-]{4,20})",
            r"Facture\s+num[eé]ro\s+([0-9\s]{3,15})",
            r"\b(BCN-\d{2}-\d{4})\b",
            r"\b(BCM?-\d{2}-\d{4})\b",
            r"(?:bon\s+de\s+commande|proforma|facture|commande)[^\n]{0,50}\n\s*(\d{2,6}\s*/\s*\d{4})",
            r"(?:bon\s+de\s+commande|bon\s+de\s+livraison|facture|proforma)\s+(\d{1,6}\s*/\s*\d{4})\b",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                raw = m.group(1)
                num = _normalize_doc_num(raw) if "/" in raw else re.sub(r"\s+", "", raw).strip(".,;:")
                if len(num) >= 3:
                    info["numero"] = num
                    break

    # Date
    m=re.search(r'Date\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',text,re.I)
    if not m: m=re.search(r'\b(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})\b',text)
    if m: info["date"]=m.group(1)

    # MF — full page-1 OCR (header+body); logic inside extract_supplier_matricule_fiscal
    page1_full = _page1_block(text)
    mf_val = extract_supplier_matricule_fiscal(page1_full[:12000])
    if mf_val:
        info["matricule_fiscal"] = mf_val

    # Contact
    m=re.search(r'T[eé]l[:\.\s/]*(\d[\d\s\.\-]{6,14}\d)',text,re.I)
    if m: info["tel"]=re.sub(r'[\s\.\-]','',m.group(1))
    m=re.search(r'Fax[:\.\s]*([\d][\d\s\.\-]{6,14}\d)',text,re.I)
    if m: info["fax"]=re.sub(r'[\s\.\-]','',m.group(1))
    m=re.search(r'[\w\.-]+@[\w\.-]+\.\w{2,}',text)
    if m: info["email"]=m.group(0)
    m=re.search(r'R\.?C\.?\s*[:\-]?\s*([A-Z][A-Z0-9]{5,14})',text,re.I)
    if m: info["rc"]=m.group(1)

    addr=extract_address(header_text)
    if addr: info["adresse"]=addr

    # Totals — search in a window AFTER the keyword, not the whole document.
    # The old code did re.findall on the whole text and took nums[-1], which
    # grabbed the year "2023" from the document number or date.
    tl = text.lower()
    for field, kws in {
        "total_ht":  ["total ht","total hors taxe","montant ht","total net ht"],
        "tva":       [" tva "," t.v.a ","valeur tva"],
        "total_ttc": ["total ttc","net à payer","montant ttc"],
    }.items():
        for kw in kws:
            pos = (" " + tl + " ").find(kw)
            if pos < 0: continue
            # Grab up to 150 chars after the keyword label
            snippet = text[pos + len(kw): pos + len(kw) + 150]
            nums = re.findall(r'\d[\d\s,\.]{0,12}\d|\b\d{1,8}\b', snippet)
            for raw in reversed(nums):
                val = _to_float(raw)
                # Reject plausible years (1900-2100) and tiny numbers
                if val and 100 < val < 50_000_000 and not (1900 <= val <= 2100):
                    info[field] = val
                    break
            if field in info: break  # found it, stop trying keywords

    out = {k: v for k, v in info.items() if v}
    # Never drop document type — empty UI cells when 'if v' stripped a key
    if not out.get("type"):
        out["type"] = info.get("type") or detect_doc_type(text)
    return out


def _clean_product_designation(desc: str) -> str:
    """Strip common OCR/table artifacts from line-item descriptions."""
    d = (desc or "").strip()
    d = re.sub(r"^[\|\\/._~\-]+", "", d)
    d = re.sub(r"[\|\\/._~\-]+$", "", d)
    d = re.sub(r"^(?:nan|NaN|none|null|\$0[\.,]?\s*|re\s+)\s*", "", d, flags=re.I)
    d = re.sub(r"\s+(?:cd|id)\s*$", "", d, flags=re.I)
    d = re.sub(r"\s{2,}", " ", d).strip()
    return d


def _infer_qty_fallback(rest: str):
    """
    When qty is not the last token in the description column, take the last
    standalone integer in the line that is not part of a decimal price.
    """
    s = re.sub(r"\b\d{1,6}[,\.]\d{2,3}\b", " ", rest)
    best = None
    for m in re.finditer(r"\b(\d{1,5})\b", s):
        v = int(m.group(1))
        if 1 <= v <= 99999 and not (1900 <= v <= 2035):
            best = v
    return float(best) if best is not None else None
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

def _detect_col_order(lines):
    combined=" ".join(lines[:8]).lower()
    qty_kws=["qté","qty","quantité","quantite","qte","nbre"]
    des_kws=["désignation","designation","libellé","article","description"]
    qty_pos=min((combined.find(k) for k in qty_kws if k in combined),default=9999)
    des_pos=min((combined.find(k) for k in des_kws if k in combined),default=9999)
    return "qty_first" if qty_pos<des_pos and qty_pos<9999 else "des_first"

def extract_product_lines(text):
<<<<<<< HEAD
    items=[]; seen=set()
    lines=text.splitlines()
    col_order=_detect_col_order(lines[:10])
    for raw_line in lines:
=======
    items = []
    # 5–8 digit numeric codes common in pharma; PFxxxx + 6-digit codes
    CODE_PCT = re.compile(r"^([A-Z]{2,4}\d{2,12}|\d{5,8})\b", re.IGNORECASE)
    CODE_ART = re.compile(r"^([A-Z]{2,4}\d{5,12})\b", re.IGNORECASE)
    QTY_PFX = re.compile(r"^(\d{1,5})[\s\|,;._~\-]+(?=[A-Za-z])")
    PRICE_STOP = re.compile(r"\b\d{1,6}[,\.]\d{2,3}\b")
    QTY_END = re.compile(r"\b(\d{1,5})\b")

    for raw_line in text.splitlines():
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
        line=raw_line.strip()
        if not line: continue
        line=re.sub(r'^[\|.\-\s]+','',line).strip()
        if not line or len(line)<5: continue
        m_code=CODE_PCT.match(line)
        if not m_code: continue
        code=m_code.group(1).upper()
<<<<<<< HEAD
        if code in seen: continue
        rest=line[len(m_code.group(0)):].strip()
        rest=re.sub(r"^[\|\.'\"()\[\]\-\s]+",'',rest).strip()
        if len(rest)<2: continue
        all_prices=PRICE_PAT.findall(rest)
        if col_order=="qty_first":
            qty=None; designation=rest
            fm=re.match(r'^(\d{1,5})\s+(.+)',rest)
            if fm:
                v=int(fm.group(1))
                if 1<=v<=99999: qty=float(v); designation=fm.group(2).strip()
            pm=PRICE_PAT.search(designation)
            if pm: designation=designation[:pm.start()].strip()
        else:
            qty=None
            pm=PRICE_PAT.search(rest)
            if pm:
                designation=rest[:pm.start()].strip()
                price_zone=rest[pm.start():]
                qm=re.search(r'\b(\d{1,5})\b',price_zone)
                if qm:
                    v=int(qm.group(1))
                    if 1<=v<=99999: qty=float(v)
            else:
                designation=rest
                qm=re.search(r'\s+(\d{1,5})\s*$',rest)
                if qm:
                    v=int(qm.group(1))
                    if 1<=v<=99999: qty=float(v); designation=rest[:qm.start()].strip()
        designation=re.sub(r'^[\|,;.\-\s]+','',designation)
        designation=re.sub(r'[\|,;.\-\s]+$','',designation)
        designation=re.sub(r'\s{2,}',' ',designation).strip()
        if not designation or len(designation)<2: continue
        seen.add(code)
        item={"code":code,"designation":designation}
        if qty is not None: item["quantite"]=qty
        if len(all_prices)>=2:
            item["prix_unitaire"]=_to_float(all_prices[-2])
            item["montant"]=_to_float(all_prices[-1])
        elif len(all_prices)==1:
            item["montant"]=_to_float(all_prices[0])
        items.append(item)
    # Second pass: QTE-first lines without a product code
    seen_desig={it.get("designation","").lower()[:20] for it in items}
    QTE_FIRST=re.compile(r'^(\d{1,5})\s{1,4}([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\s\-\/\(\)\.]{4,70})',re.IGNORECASE)
    for raw_line in lines:
        line=raw_line.strip()
        if not line or len(line)<7: continue
        line=re.sub(r'^[\|.\-\s]+','',line).strip()
        if CODE_PCT.match(line): continue
        mqf=QTE_FIRST.match(line)
        if not mqf: continue
        qty_v=int(mqf.group(1))
        if not (1<=qty_v<=9999): continue
        rest=mqf.group(2).strip()
        pm=PRICE_PAT.search(rest)
        desc=rest[:pm.start()].strip() if pm else rest
        desc=re.sub(r'[\s\d,\.]+$','',desc).strip()
        if len(desc)<4: continue
        if desc.lower()[:20] in seen_desig: continue
        seen_desig.add(desc.lower()[:20])
        item={"designation":desc,"quantite":float(qty_v)}
        if pm:
            prices=PRICE_PAT.findall(rest[pm.start():])
            if len(prices)>=2:
                item["prix_unitaire"]=_to_float(prices[-2])
                item["montant"]=_to_float(prices[-1])
            elif len(prices)==1:
                item["montant"]=_to_float(prices[0])
=======
        rest=line[len(m_code.group(0)):].strip()
        if len(rest)<2: continue

        code_article=None
        m_art=CODE_ART.match(rest)
        if m_art:
            code_article=m_art.group(1).upper()
            rest=rest[len(code_article):].strip().lstrip('-').strip()

        rest=re.sub(r"^[\|\.'\"()\[\]\-\s]+",'',rest).strip()
        rest=re.sub(r'^\d{3,}\s+(?=\d{1,3}[\s\|,;._~\-]+[A-Za-z])','',rest)
        if not rest: continue
        qty_prefix=None
        m_pfx=QTY_PFX.match(rest)
        if m_pfx:
            v=int(m_pfx.group(1))
            if 1<=v<=99999:
                qty_prefix=float(v); rest=rest[m_pfx.end():].strip()

        price_m=PRICE_STOP.search(rest)
        dz=rest[:price_m.start()].strip() if price_m else rest
        pz=rest[price_m.start():] if price_m else ""

        desc=re.sub(r'^[\|,;.\-\s]+','',dz).strip()
        desc=re.sub(r'[\|,;.\-_*~\s]+$','',desc).strip()   # also strips trailing _ * ~
        desc=re.sub(r'\s*\|\s*',' ',desc).strip()
        desc=re.sub(r'\s{2,}',' ',desc).strip()             # collapse double spaces
        desc = _clean_product_designation(desc)
        if not desc or len(desc)<3: continue

        qty=qty_prefix
        if not qty:
            for qm in QTY_END.finditer(dz):
                v=int(qm.group(1))
                if 1<=v<=99999:
                    tail=dz[qm.start():].strip()
                    if re.fullmatch(r'\d{1,5}',tail):
                        qty=float(v)
                        desc=re.sub(r'^[\|,;.\-\s]+|[\|,;.\-\s]+$','',
                                    dz[:qm.start()].strip()).strip()
                        break
            if not qty and pz:
                for qm in QTY_END.finditer(pz):
                    v=int(qm.group(1))
                    if 1<=v<=99999: qty=float(v); break
        if not qty:
            qfb = _infer_qty_fallback(rest)
            if qfb is not None:
                qty = qfb
                desc = re.sub(rf"\s+{int(qfb)}\s*$", "", desc).strip()

        if not desc or len(desc)<3: continue
        item={"code":code,"designation":desc}
        if code_article: item["code_article"]=code_article
        if qty:          item["quantite"]=qty
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
        items.append(item)
    return items

def pdf_page_to_image(pdf_path,page_index,dpi=300):
    doc=fitz.open(pdf_path); page=doc[page_index]
    mat=fitz.Matrix(dpi/72,dpi/72); pix=page.get_pixmap(matrix=mat,alpha=False)
    img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
    return cv2.cvtColor(img,cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)

<<<<<<< HEAD
# ─────────────────────────────────────────────────────────────────────────────
=======
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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Options")
    st.markdown("---")
    st.markdown("**Preprocessing**")
    use_fix_rotation=st.checkbox("Fix Rotation",value=True)
    use_erase_color =st.checkbox("Erase Colored Ink",value=True)
    use_remove_lines=st.checkbox("Remove Borders",value=True)
    use_keep_mask   =st.checkbox("Blob Filter (CV)",value=True)
    st.markdown("---")
    st.markdown("**OCR**")
<<<<<<< HEAD
    split_zones=st.checkbox("Split Header / Body / Footer OCR",value=True)
    show_raw   =st.checkbox("Show Raw OCR Text",value=False)
=======
    dpi_choice  = st.radio("DPI", options=[150,200,300], index=1,
                           help="200 DPI ≈ 40% faster than 300. Use 300 only for very small or faded text.")
    split_zones = st.checkbox("Split Header / Body OCR", value=True)
    show_raw    = st.checkbox("Show Raw OCR Text",       value=False)
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
    st.markdown("---")
    st.markdown("**NLP**")
    use_nlp       = st.checkbox("Enable NLP Enrichment",    value=True)
    show_conf     = st.checkbox(
        "Show Confidence Scores",
        value=False,
        help="Each field gets a % score: 🟢 ≥80% = reliable, 🟡 55–79% = check it, 🔴 <55% = likely wrong")
    show_warnings = st.checkbox("Show Validation Warnings", value=True)
    st.markdown("---")
    st.markdown("**Output**")
    show_tables  =st.checkbox("Show pdfplumber Tables",value=True)
    show_products=st.checkbox("Show Product Lines",value=True)
    show_json    =st.checkbox("Show Full JSON",value=False)
    st.markdown("---")
    st.markdown("**Sprint 3 — AI Extraction**")
    run_sprint3 =st.checkbox("Run AI Extraction (SpaCy + LayoutLM)",value=False)
    show_s3_json=st.checkbox("Show Sprint 3 Full JSON",value=False)

<<<<<<< HEAD
# ─────────────────────────────────────────────────────────────────────────────
# MAIN UI
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("# 🔬 Invoice OCR Pipeline")
st.markdown("*Preprocessing → OCR → BBox Table → Regex → AI Extraction*")
st.markdown("---")

uploaded=st.file_uploader("Drop a PDF or image file",
                           type=["pdf","png","jpg","jpeg"],
                           label_visibility="collapsed")
run_btn=st.button("▶  Run Pipeline",use_container_width=True)

if not uploaded:
    st.markdown("<div style='text-align:center;padding:60px 0;color:#444;'>"
                "<div style='font-size:48px;margin-bottom:16px'>📄</div>"
                "<div style='font-size:14px'>Upload a PDF or image to begin</div>"
                "<div style='font-size:11px;color:#333;margin-top:8px'>"
                "Supports: Bon de Commande · Proforma · Facture · Bon de Livraison"
                "</div></div>", unsafe_allow_html=True)

if uploaded and run_btn:

    _log_init(); _log_ph=st.empty(); _log_render(_log_ph)
=======

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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

    is_pdf=uploaded.type=="application/pdf"
    suffix=".pdf" if is_pdf else Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as tmp:
        tmp.write(uploaded.read()); tmp_path=tmp.name

    file_kb=round(len(uploaded.getvalue())/1024,1)
    _log_set("load","done",f"{uploaded.name}  ({file_kb} KB)"); _log_render(_log_ph)

    if is_pdf:
        _log_set("detect","running","reading PDF…"); _log_render(_log_ph)
<<<<<<< HEAD
        is_native=detect_pdf_native(tmp_path)
        doc_fitz=fitz.open(tmp_path); total_pages=len(doc_fitz)
        _log_set("detect","done",
                 f"{'Native' if is_native else 'Scanned'} PDF  —  {total_pages} page(s)")
        _log_render(_log_ph)
    else:
        is_native=False; total_pages=1
        _log_set("detect","done","Image file  —  1 page"); _log_render(_log_ph)

    if is_pdf:
        c1,c2=st.columns([2,1]); color="#7ee8a2" if is_native else "#e8c87e"
        with c1:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>PDF type</div>"
                        f"<div class='metric-value' style='color:{color}'>"
                        f"{'📄 Native (digital)' if is_native else '📷 Scanned (image-based)'}"
=======
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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
                        f"</div></div>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>Pages</div>"
                        f"<div class='metric-value'>{total_pages}</div></div>",
                        unsafe_allow_html=True)
<<<<<<< HEAD

    st.markdown("---")

    all_header_texts=[]; all_body_texts=[]; all_footer_texts=[]; all_full_texts=[]
    all_clean_imgs=[]; all_orig_imgs=[]; all_pil_imgs=[]
    all_product_lines=[]; seen_codes=set()

=======
    st.markdown("---")

    all_header_texts=[]; all_body_texts=[]; all_full_texts=[]
    all_clean_imgs  =[]; all_orig_imgs =[]
    all_product_lines=[]
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
    prog=st.progress(0,text="Processing pages…")

    for page_i in range(total_pages):

<<<<<<< HEAD
        # ── Preprocess ────────────────────────────────────────────────
        _log_set("preprocess","running",
                 f"page {page_i+1}/{total_pages}  |  "
                 f"rotation={use_fix_rotation}  color={use_erase_color}  "
                 f"lines={use_remove_lines}  blob={use_keep_mask}")
        _log_render(_log_ph); _pp_t0=_time.time()

        if is_pdf: img_bgr=pdf_page_to_image(tmp_path,page_i,dpi=300)
        else: img_bgr=cv2.imdecode(np.frombuffer(uploaded.getvalue(),dtype=np.uint8),1)
=======
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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

        all_orig_imgs.append(cv2.cvtColor(img_bgr,cv2.COLOR_BGR2RGB))
        work=img_bgr.copy()
        if use_fix_rotation: work=fix_rotation(work)
        if use_erase_color:  work=erase_colored_ink(work)
<<<<<<< HEAD
        gray=cv2.cvtColor(work,cv2.COLOR_BGR2GRAY)
        binary=binarize(gray)
        if use_remove_lines: binary=remove_long_lines(binary)
        clean=enhance_kept_text(binary,build_keep_mask(binary)) if use_keep_mask else binary
        all_clean_imgs.append(clean)
        all_pil_imgs.append(Image.fromarray(clean))

        _log_set("preprocess","done",f"{total_pages} page(s) cleaned",t0=_pp_t0)
        _log_render(_log_ph)

        # ── OCR ───────────────────────────────────────────────────────
        _log_set("ocr","running",
                 f"page {page_i+1}/{total_pages}  |  LSTM  split={split_zones}")
        _log_render(_log_ph); _ocr_t0=_time.time()

        if split_zones:
            h_text=clean_ocr_text(ocr_header_zone(clean))
            b_text=clean_ocr_text(ocr_body_zone(clean))
            ft_text=clean_ocr_text(ocr_footer_zone(clean))
            f_text=h_text+"\n"+b_text+"\n"+ft_text
        else:
            f_text=clean_ocr_text(ocr_full_page(clean))
            h_text=b_text=ft_text=f_text

        all_header_texts.append(h_text); all_body_texts.append(b_text)
        all_footer_texts.append(ft_text); all_full_texts.append(f_text)

        _log_set("ocr","done",
                 f"{total_pages} page(s)  |  {len(f_text.split())} words",t0=_ocr_t0)
        _log_render(_log_ph)

        # ── Text-based product lines (fallback) ───────────────────────
        _log_set("products","running",
                 f"page {page_i+1}/{total_pages}  |  scanning product codes…")
=======
        gray  =cv2.cvtColor(work,cv2.COLOR_BGR2GRAY)
        binary=binarize(gray)
        if use_remove_lines: binary=remove_long_lines(binary)
        clean =enhance_kept_text(binary,build_keep_mask(binary)) if use_keep_mask else binary
        all_clean_imgs.append(clean)
        _log_set("preprocess","done",f"{total_pages} page(s) cleaned",t0=_pp_t0)
        _log_render(_log_ph)

        _log_set("ocr","running",
                 f"page {page_i+1}/{total_pages}  split={split_zones}  DPI={dpi_choice}")
        _log_render(_log_ph)
        _ocr_t0=_time.time()
        if split_zones:
            h_text=clean_ocr_text(ocr_header_zone(clean))
            b_text=clean_ocr_text(ocr_body_zone(clean))
            f_text=h_text+"\n"+b_text
        else:
            f_text=clean_ocr_text(ocr_full_page(clean))
            h_text=b_text=f_text
        all_header_texts.append(h_text)
        all_body_texts.append(b_text)
        all_full_texts.append(f_text)
        _log_set("ocr","done",
                 f"{total_pages} page(s)  {len(f_text.split())} words",t0=_ocr_t0)
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
        _log_render(_log_ph)

        _log_set("products","running",f"page {page_i+1}/{total_pages}"); _log_render(_log_ph)
        if show_products:
<<<<<<< HEAD
            for item in extract_product_lines(b_text):
                code=item.get("code","")
                if code and code not in seen_codes:
                    seen_codes.add(code); all_product_lines.append(item)
                elif not code:
                    all_product_lines.append(item)

        _log_set("products","done",
                 f"{len(all_product_lines)} unique product line(s) so far")
        _log_render(_log_ph)

        prog.progress((page_i+1)/total_pages,
                      text=f"Processing page {page_i+1} / {total_pages}…")
=======
            # Full-page line text — body-only OCR drops table rows that fall in the top band
            for item in extract_product_lines(f_text):
                all_product_lines.append(item)
        _log_set("products","done",f"{len(all_product_lines)} item(s)"); _log_render(_log_ph)
        prog.progress((page_i+1)/total_pages,text=f"Page {page_i+1}/{total_pages}…")
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

    prog.empty()
    combined_full  ="\n\n".join(all_full_texts)
    combined_header="\n\n".join(all_header_texts)

<<<<<<< HEAD
    combined_full  ="\n\n".join(all_full_texts)
    combined_header="\n\n".join(all_header_texts)
    combined_body  ="\n\n".join(all_body_texts)
    combined_footer="\n\n".join(all_footer_texts)

    # ── pdfplumber ────────────────────────────────────────────────────
    plumber_tables=[]
    if is_pdf and is_native and show_tables:
        _log_set("pdfplumber","running","reading PDF vector table data…")
        _log_render(_log_ph); _pl_t0=_time.time()
        with st.spinner("Extracting tables with pdfplumber…"):
            plumber_tables=extract_tables_pdfplumber(tmp_path)
        _log_set("pdfplumber","done",f"{len(plumber_tables)} table(s) found",t0=_pl_t0)
        _log_render(_log_ph)
    else:
        reason=("scanned PDF — OCR used" if (is_pdf and not is_native)
                else "image file" if not is_pdf else "disabled in sidebar")
        _log_set("pdfplumber","skip",reason); _log_render(_log_ph)

    # ── Regex extraction ──────────────────────────────────────────────
    _log_set("regex","running",
             f"scanning {len(combined_full.split())} words  |  "
             f"supplier · MF · date · N° · totals…")
    _log_render(_log_ph); _rx_t0=_time.time()

    extracted_info=extract_info(combined_full,
                                header_text=combined_header,
                                footer_text=combined_footer)
    supplier=extract_supplier(combined_header,combined_full)
    if supplier: extracted_info["supplier"]=supplier

    _log_set("regex","done",
             f"type={extracted_info.get('type','?')}  "
             f"date={extracted_info.get('date','—')}  "
             f"N°={extracted_info.get('numero','—')}  "
             f"HT={extracted_info.get('total_ht','—')}",
             t0=_rx_t0)
    _log_render(_log_ph)

    # ── BBox table extraction (invoice_extractor_v2) ──────────────────
    _log_set("bbox_table","running",
             "detecting column headers via bounding boxes…")
    _log_render(_log_ph); _bbox_t0=_time.time()

    bbox_col_names=[]
    bbox_items=[]

    try:
        from sprint3.invoice_extractor_universal import extract_invoice_data
        
        result = extract_invoice_data(tmp_path, page_index=0)
        
        bbox_items = result.get("lignes_facture", [])
        bbox_col_names = result.get("_meta", {}).get("lanes_detected", [])
        
        # Override regex results with spatial extraction when available
        if result["header"].get("document_number"):
            extracted_info["numero"] = result["header"]["document_number"]
        if result["header"].get("matricule_fiscale"):
            extracted_info["matricule_fiscal"] = result["header"]["matricule_fiscale"]
        if result["header"].get("type"):
            extracted_info["type"] = result["header"]["type"]
        
        # NEW: only map keys that actually exist in the extracted item
        raw_items = result.get("lignes_facture", [])
        bbox_items = []
        for it in raw_items:
            mapped = {}
            if "code" in it:          mapped["Code"]       = it["code"]
            if "designation" in it:   mapped["LibProd"]    = it["designation"]
            if "quantite" in it:      mapped["Quantité"]   = it["quantite"]
            if "prix_unitaire" in it: mapped["PrixVente"]  = it["prix_unitaire"]
            if "montant" in it:       mapped["line_total"] = it["montant"]
            bbox_items.append(mapped)

        bbox_col_names = result.get("_meta", {}).get("lanes_detected", [])
        
        _log_set("bbox_table", "done",
                f"{len(bbox_items)} rows  ·  lanes={bbox_col_names}",
                t0=_bbox_t0)
    except Exception as e:
        _log_set("bbox_table", "warn", f"universal extractor failed: {e}")
        _log_render(_log_ph)

    # Sprint 3 bridge
    parsed_sections_s3={"header":combined_header,"body":combined_body,"footer":combined_footer}
    regex_fields_s3={
        "invoice_number": extracted_info.get("numero"),
        "date":           extracted_info.get("date"),
        "total_ht":       str(extracted_info.get("total_ht","")) or None,
        "total_ttc":      str(extracted_info.get("total_ttc","")) or None,
        "tva_rate":       None,
        "tva_amount":     str(extracted_info.get("tva","")) or None,
        "fodec_rate":     None,
        "fodec_amount":   None,
    }
    pil_image_s3=all_pil_imgs[0] if all_pil_imgs else None
    invoice_type_s3={"value":extracted_info.get("type","UNKNOWN"),"confidence":95,"method":"REGEX"}

    _log_set("done","done",
             f"{total_pages} page(s)  |  "
             f"{len(all_product_lines)} text items  |  "
             f"{len(bbox_items)} bbox items  |  "
             f"{len(plumber_tables)} tables")
    _log_render(_log_ph)

    # ── Sprint 3: SpaCy ───────────────────────────────────────────────
    _log_set("s3_spacy","running","loading fr_core_news_md model…")
    _log_render(_log_ph); _s3_t0=_time.time()
    from sprint3.spacy_extractor import extract_entities
    spacy_fields=extract_entities(parsed_sections_s3)
    _log_set("s3_spacy","done",
             f"vendor={spacy_fields.get('vendor_name',{}).get('value','—')}  "
             f"city={spacy_fields.get('vendor_city',{}).get('value','—')}",
             t0=_s3_t0)
    _log_render(_log_ph)

    # ── Sprint 3: LayoutLM ────────────────────────────────────────────
    _s3_lm_t0=_time.time()
    if run_sprint3 and pil_image_s3:
        _log_set("s3_layoutlm","running","running LayoutLM inference (~30s first time)…")
        _log_render(_log_ph)
        from sprint3.layoutlm_extractor import extract_with_layoutlm
        layoutlm_fields=extract_with_layoutlm(pil_image_s3)
        _log_set("s3_layoutlm","done",
                 f"{len(layoutlm_fields)} field(s) extracted",t0=_s3_lm_t0)
        _log_render(_log_ph)
    else:
        layoutlm_fields={}
        _log_set("s3_layoutlm","skip",
                 "disabled — enable 'Run AI Extraction' in sidebar for LayoutLM")
        _log_render(_log_ph)

    # ── Sprint 3: Scoring ─────────────────────────────────────────────
    _log_set("s3_scoring","running","scoring fields and assembling JSON…")
    _log_render(_log_ph); _s3_sc_t0=_time.time()
    from sprint3.confidence_scorer import score_all_fields,compute_invoice_confidence
    from sprint3.json_builder import (build_invoice_json,invoice_json_to_string,
                                      get_fields_for_display,apply_accountant_corrections,
                                      mark_as_validated)
    scored=score_all_fields(regex_fields_s3,spacy_fields,layoutlm_fields)
    summary=compute_invoice_confidence(scored)
    st.session_state["s3_result"]=build_invoice_json(
        parsed_sections=parsed_sections_s3,
        regex_fields=regex_fields_s3,
        image=pil_image_s3 if run_sprint3 else None,
        invoice_type=invoice_type_s3)
    _log_set("s3_scoring","done",
             f"avg={summary['confidence_avg']}%  "
             f"review={len(summary['low_confidence_fields'])} field(s)",
             t0=_s3_sc_t0)
    _log_render(_log_ph)

    if "s3_corrections" not in st.session_state:
        st.session_state["s3_corrections"]={}

    # ─────────────────────────────────────────────────────────────────
    # DISPLAY: PAGES
    # ─────────────────────────────────────────────────────────────────

    st.markdown("## 🖼️ Pages — Original & Cleaned")
    for page_i,(orig_img,clean_img) in enumerate(zip(all_orig_imgs,all_clean_imgs)):
        label=f"Page {page_i+1} / {total_pages}" if total_pages>1 else "Document"
=======
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
    regex_info=extract_info(combined_full, combined_header)
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

    if not extracted_info.get("type"):
        extracted_info["type"] = detect_doc_type(combined_full)
    if not extracted_info.get("matricule_fiscal"):
        mf_fill = extract_supplier_matricule_fiscal(_page1_block(combined_full)[:12000])
        if mf_fill:
            extracted_info["matricule_fiscal"] = mf_fill

    _log_set("done","done",
             f"{total_pages} page(s) · {len(all_product_lines)} items · "
             f"{len(plumber_tables)} tables · {len(warnings_nlp)} NLP warn")
    _log_render(_log_ph)

    # ── Display pages ─────────────────────────────────────────────────
    st.markdown("## 🖼️ Pages — Original & Cleaned")
    for page_i,(orig,clean) in enumerate(zip(all_orig_imgs,all_clean_imgs)):
        label=f"Page {page_i+1}/{total_pages}" if total_pages>1 else "Document"
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
        st.markdown(f"<div class='page-label'>{label}</div>",unsafe_allow_html=True)
        c1,c2=st.columns(2)
        with c1:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#888;"
                        "text-align:center;margin-bottom:4px'>📷 Original</div>",
                        unsafe_allow_html=True)
<<<<<<< HEAD
            st.image(orig_img,use_container_width=True)
=======
            st.image(orig,use_container_width=True)
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
        with c2:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#7ee8a2;"
                        "text-align:center;margin-bottom:4px'>✨ After Cleaning</div>",
                        unsafe_allow_html=True)
<<<<<<< HEAD
            st.image(clean_img,use_container_width=True)
        if page_i<len(all_clean_imgs)-1:
            st.markdown("<hr style='border-color:#1e2130;margin:12px 0;'>",
                        unsafe_allow_html=True)

    st.markdown("---")

    # ─────────────────────────────────────────────────────────────────
    # EXTRACTED INFORMATION
    # ─────────────────────────────────────────────────────────────────

    dtype=extracted_info.get("type","Document")
    tag_class={"Bon de Commande":"tag-bc","Proforma":"tag-proforma",
               "Facture":"tag-facture","Bon de Livraison":"tag-bc"}.get(dtype,"tag-stat")
    st.markdown(f"<span class='{tag_class}'>{dtype}</span>",unsafe_allow_html=True)
    st.markdown("## 📋 Extracted Information")

    info_cols=st.columns(3)
    fields_display=[
        ("Supplier",         extracted_info.get("supplier",        "—")),
        ("Type de document", extracted_info.get("type",            "—")),
        ("Document N°",      extracted_info.get("numero",          "—")),
        ("Date",             extracted_info.get("date",            "—")),
        ("Matricule Fiscal", extracted_info.get("matricule_fiscal","—")),
        ("Téléphone",        extracted_info.get("tel",             "—")),
        ("Fax",              extracted_info.get("fax",             "—")),
        ("Email",            extracted_info.get("email",           "—")),
        ("RC",               extracted_info.get("rc",              "—")),
        ("Total HT",         extracted_info.get("total_ht",        "—")),
        ("TVA",              extracted_info.get("tva",             "—")),
        ("Total TTC",        extracted_info.get("total_ttc",       "—")),
    ]
    for idx,(label,value) in enumerate(fields_display):
        with info_cols[idx%3]:
            st.markdown(f"<div class='metric-card'>"
                        f"<div class='metric-label'>{label}</div>"
                        f"<div class='metric-value' style='font-size:14px'>{value}</div>"
                        f"</div>", unsafe_allow_html=True)

    if extracted_info.get("adresse"):
        st.markdown(f"<div class='metric-card' style='margin-top:6px'>"
                    f"<div class='metric-label'>Adresse</div>"
                    f"<div class='metric-value' style='font-size:13px;color:#7ec8e8'>"
                    f"{extracted_info['adresse']}</div></div>",
                    unsafe_allow_html=True)

    # ─────────────────────────────────────────────────────────────────
    # PRODUCT TABLE — BBox version (primary) then text fallback
    # ─────────────────────────────────────────────────────────────────

    if show_products:
        if bbox_items:
            # ── BBox-extracted table ───────────────────────────────
            st.markdown(f"## 📦 Product Lines — BBox Table ({len(bbox_items)} rows)")
            st.markdown(f"*Columns detected in invoice: **{', '.join(bbox_col_names)}***")

            # Determine which DB columns have actual data
            has_code =any(r.get("Code")      for r in bbox_items)
            has_lib  =any(r.get("LibProd")   for r in bbox_items)
            has_qty  =any(r.get("Quantité")  for r in bbox_items)
            has_pu   =any(r.get("PrixVente") for r in bbox_items)
            has_mt   =any(r.get("line_total")for r in bbox_items)
            has_forme=any(r.get("Forme")     for r in bbox_items)
            has_pct  =any(r.get("Code_PCT")  for r in bbox_items)
            has_yn   =any(r.get("YN")        for r in bbox_items)
            has_emp  =any(r.get("Emp_FRS")   for r in bbox_items)

            tbl="<div class='table-container'><table><thead><tr><th>#</th>"
            if has_code:  tbl+="<th>Code</th>"
            if has_lib:   tbl+="<th>Désignation</th>"
            if has_qty:   tbl+="<th style='text-align:right'>Qté</th>"
            if has_pu:    tbl+="<th style='text-align:right'>Prix Unitaire</th>"
            if has_mt:    tbl+="<th style='text-align:right'>Montant</th>"
            if has_forme: tbl+="<th>Forme</th>"
            if has_pct:   tbl+="<th>Code PCT</th>"
            if has_yn:    tbl+="<th>Y/N</th>"
            if has_emp:   tbl+="<th>Emp FRS</th>"
            tbl+="</tr></thead><tbody>"

            for i,row in enumerate(bbox_items,1):
                qty=row.get("Quantité",  0)
                pu =row.get("PrixVente", 0)
                mt =row.get("line_total",None)
                qty_s=f"{qty:.0f}" if isinstance(qty,float) else str(qty)
                pu_s =f"{pu:,.6f}" if isinstance(pu,float)  else str(pu)
                mt_s =f"{mt:,.3f}" if isinstance(mt,float)  else ("—" if mt is None else str(mt))

                tbl+=f"<tr><td style='color:#555'>{i}</td>"
                if has_code:  tbl+=f"<td style='color:#7ee8a2'>{row.get('Code','')}</td>"
                if has_lib:   tbl+=f"<td>{row.get('LibProd','')}</td>"
                if has_qty:   tbl+=f"<td style='text-align:right;color:#e8c87e'>{qty_s}</td>"
                if has_pu:    tbl+=f"<td style='text-align:right;color:#7ec8e8'>{pu_s}</td>"
                if has_mt:    tbl+=f"<td style='text-align:right'>{mt_s}</td>"
                if has_forme: tbl+=f"<td>{row.get('Forme','')}</td>"
                if has_pct:   tbl+=f"<td>{row.get('Code_PCT','')}</td>"
                if has_yn:    tbl+=f"<td>{row.get('YN','')}</td>"
                if has_emp:   tbl+=f"<td>{row.get('Emp_FRS','')}</td>"
                tbl+="</tr>"
            tbl+="</tbody></table></div>"
            st.markdown(tbl,unsafe_allow_html=True)

        elif all_product_lines:
            # ── Text-based fallback ────────────────────────────────
            st.markdown(f"## 📦 Product Lines — Text Extraction ({len(all_product_lines)} items)")
            st.caption("BBox table not detected — showing text-based extraction")

            has_code=any(item.get("code")         for item in all_product_lines)
            has_qty =any(item.get("quantite")      for item in all_product_lines)
            has_pu  =any(item.get("prix_unitaire") for item in all_product_lines)
            has_mt  =any(item.get("montant")       for item in all_product_lines)

            tbl="<div class='table-container'><table><thead><tr><th>#</th>"
            if has_code: tbl+="<th>Code</th>"
            tbl+="<th>Designation</th>"
            if has_qty:  tbl+="<th style='text-align:right'>Qté</th>"
            if has_pu:   tbl+="<th style='text-align:right'>Prix Unitaire</th>"
            if has_mt:   tbl+="<th style='text-align:right'>Montant</th>"
            tbl+="</tr></thead><tbody>"

            for i,item in enumerate(all_product_lines,1):
                qty=item.get("quantite"); pu=item.get("prix_unitaire"); mt=item.get("montant")
                qty_s=f"{qty:.0f}" if isinstance(qty,float) else (str(qty) if qty else "—")
                pu_s =f"{pu:,.3f}" if isinstance(pu,float)  else (str(pu)  if pu  else "—")
                mt_s =f"{mt:,.3f}" if isinstance(mt,float)  else (str(mt)  if mt  else "—")
                tbl+=f"<tr><td style='color:#555'>{i}</td>"
                if has_code: tbl+=f"<td style='color:#7ee8a2'>{item.get('code','')}</td>"
                tbl+=f"<td>{item.get('designation','')}</td>"
                if has_qty:  tbl+=f"<td style='text-align:right;color:#e8c87e'>{qty_s}</td>"
                if has_pu:   tbl+=f"<td style='text-align:right;color:#7ec8e8'>{pu_s}</td>"
                if has_mt:   tbl+=f"<td style='text-align:right'>{mt_s}</td>"
                tbl+="</tr>"
            tbl+="</tbody></table></div>"
            st.markdown(tbl,unsafe_allow_html=True)
        else:
            st.info("No product lines detected. Enable 'Show Raw OCR Text' to debug.")

    # ─────────────────────────────────────────────────────────────────
    # PDFPLUMBER TABLES
    # ─────────────────────────────────────────────────────────────────
=======
            st.image(clean,use_container_width=True)
        if page_i<len(all_clean_imgs)-1:
            st.markdown("<hr style='border-color:#1e2130;margin:12px 0;'>",unsafe_allow_html=True)

    st.markdown("---")

    dtype = extracted_info.get("type") or detect_doc_type(combined_full)
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
        ("Type de document", "type",            dtype),
        ("Document N°",      "numero",           extracted_info.get("numero",          "—")),
        ("Date",             "date",             extracted_info.get("date",            "—")),
        ("Matricule Fiscal", "matricule_fiscal", extracted_info.get("matricule_fiscal", "—")),
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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

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
<<<<<<< HEAD
            st.markdown("")

    # ─────────────────────────────────────────────────────────────────
    # RAW OCR
    # ─────────────────────────────────────────────────────────────────

=======

>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
    if show_raw:
        st.markdown("## 📝 Raw OCR Text")
        for page_i in range(total_pages):
            label=f"Page {page_i+1}" if total_pages>1 else "Full text"
            with st.expander(label,expanded=(page_i==0)):
                if split_zones:
<<<<<<< HEAD
                    c1,c2,c3=st.columns(3)
=======
                    c1,c2=st.columns(2)
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7
                    with c1:
                        st.markdown("**Header zone**")
                        st.markdown(f"<div class='raw-text'>{all_header_texts[page_i]}</div>",
                                    unsafe_allow_html=True)
                    with c2:
                        st.markdown("**Body zone**")
                        st.markdown(f"<div class='raw-text'>{all_body_texts[page_i]}</div>",
                                    unsafe_allow_html=True)
                    with c3:
                        st.markdown("**Footer zone**")
                        st.markdown(f"<div class='raw-text'>{all_footer_texts[page_i]}</div>",
                                    unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='raw-text'>{all_full_texts[page_i]}</div>",
                                unsafe_allow_html=True)

    if show_json:
        st.markdown("## 🗂️ Full JSON")
        st.json({
            "informations_document": extracted_info,
<<<<<<< HEAD
            "bbox_table": {"columns":bbox_col_names,"rows":bbox_items},
            "ligne_articles": all_product_lines,
        })

# ─────────────────────────────────────────────────────────────────────────────
# SPRINT 3 RESULTS (persists across reruns)
# ─────────────────────────────────────────────────────────────────────────────

if "s3_result" in st.session_state:
    from sprint3.json_builder import (get_fields_for_display,apply_accountant_corrections,
                                      invoice_json_to_string,mark_as_validated)
    s3=st.session_state["s3_result"]
    val=s3.get("validation",{})

    st.markdown("---")
    st.markdown("## 🤖 Sprint 3 — AI Extraction Results")

    avg_conf=val.get("confidence_avg",0)
    bar_color="#7ee8a2" if avg_conf>=80 else "#e8c87e" if avg_conf>=60 else "#e87e7e"
    st.markdown(f"""
    <div class='metric-card' style='margin-bottom:12px'>
        <div class='metric-label'>Invoice confidence</div>
        <div style='display:flex;align-items:center;gap:12px;margin-top:6px'>
            <div style='flex:1;background:#1e2130;border-radius:4px;height:8px'>
                <div style='width:{avg_conf}%;background:{bar_color};
                            height:8px;border-radius:4px;transition:width 0.4s'></div>
            </div>
            <div style='font-family:JetBrains Mono;font-size:16px;
                        font-weight:600;color:{bar_color}'>{avg_conf}%</div>
        </div>
        <div style='font-size:11px;color:#555;margin-top:6px'>
            Fields needing review:
            {", ".join(val.get("low_confidence_fields",[])) or "None ✅"}
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("### 📝 Field Review")
    st.markdown("*Edit any field below. Orange = below 80% confidence.*")

    display_rows=get_fields_for_display(s3)
    corrections=st.session_state.get("s3_corrections",{})

    for row in display_rows:
        field=row["field"]; confidence=row["confidence"]
        method=row["method"]; needs_review=row["needs_review"]
        current_val=corrections.get(field,row["value"] or "")
        conf_color="#7ee8a2" if confidence>=80 else "#e8c87e" if confidence>=60 else "#e87e7e"
        icon="✅" if confidence>=80 else "⚠️" if confidence>=60 else "🔴"
        cl,ci,cc,cm=st.columns([2,4,1,1])
        with cl:
            st.markdown(f"<div style='padding-top:8px;font-size:12px;"
                        f"color:{'#e8c87e' if needs_review else '#888'}'>"
                        f"{icon} {field}</div>", unsafe_allow_html=True)
        with ci:
            new_val=st.text_input(field,value=current_val,
                                  key=f"s3_{field}",label_visibility="collapsed")
            if new_val!=(row["value"] or ""): corrections[field]=new_val
        with cc:
            st.markdown(f"<div style='padding-top:8px;text-align:center;"
                        f"font-family:JetBrains Mono;font-size:12px;color:{conf_color}'>"
                        f"{confidence}%</div>", unsafe_allow_html=True)
        with cm:
            st.markdown(f"<div style='padding-top:8px;text-align:center;"
                        f"font-size:10px;color:#555'>{method}</div>",
                        unsafe_allow_html=True)
    st.session_state["s3_corrections"]=corrections

    line_items=s3.get("body",{}).get("line_items",[])
    if line_items:
        st.markdown(f"### 📦 Line Items — lignefac ready ({len(line_items)} rows)")
        tbl="<div class='table-container'><table><thead><tr>"
        tbl+="<th>#</th><th>Code</th><th>LibProd</th><th>Quantité</th>"
        tbl+="<th>PrixVente</th><th>TauxTVA</th><th>TauxFODEC</th>"
        tbl+="</tr></thead><tbody>"
        for i,item in enumerate(line_items,1):
            tbl+=(f"<tr><td style='color:#555'>{i}</td>"
                  f"<td style='color:#7ee8a2'>{item.get('Code','')}</td>"
                  f"<td>{item.get('LibProd','')}</td>"
                  f"<td style='text-align:right;color:#e8c87e'>{item.get('Quantité',0)}</td>"
                  f"<td style='text-align:right;color:#7ec8e8'>{item.get('PrixVente',0)}</td>"
                  f"<td style='text-align:right'>{item.get('TauxTVA',0)}</td>"
                  f"<td style='text-align:right'>{item.get('TauxFODEC',0)}</td></tr>")
        tbl+="</tbody></table></div>"
        st.markdown(tbl,unsafe_allow_html=True)

    st.markdown("### ✅ Validation")
    cv,cr=st.columns(2)
    with cv:
        if st.button("✅ Validate & Push to DB",use_container_width=True):
            if corrections: s3=apply_accountant_corrections(s3,corrections)
            s3=mark_as_validated(s3,accountant_username="accountant1")
            st.session_state["s3_result"]=s3
            st.success("✅ Invoice validated — ready for Sprint 4 DB injection.")
            st.info("📌 Sprint 4 reads st.session_state['s3_result'] and writes to "
                    "facture + lignefac.")
    with cr:
        if st.button("❌ Reject Invoice",use_container_width=True):
            s3["validation"]["status"]="REJECTED"
            st.session_state["s3_result"]=s3
            st.error("❌ Invoice marked as rejected.")

    if show_s3_json:
        st.markdown("### 🗂️ Sprint 3 Full JSON")
        st.code(invoice_json_to_string(s3),language="json")

    st.markdown("---")
    c1,c2=st.columns(2)
    with c1:
        try:
            dl_data=json.dumps({
                "sprint2":{
                    "informations_document":extracted_info,
                    "bbox_table":{"columns":bbox_col_names,"rows":bbox_items},
                    "ligne_articles":all_product_lines,
                },
                "sprint3":st.session_state.get("s3_result",{}),
            },ensure_ascii=False,indent=2)
            fname=f"{Path(uploaded.name).stem}_extracted.json"
        except Exception:
            dl_data=json.dumps({"sprint3":st.session_state.get("s3_result",{})},
                               ensure_ascii=False,indent=2)
            fname="extracted.json"
        st.download_button("⬇ Download JSON",data=dl_data,
                           file_name=fname,mime="application/json",
                           use_container_width=True)
    with c2:
        try:
            st.download_button("⬇ Download OCR Text",data=combined_full,
                               file_name=f"{Path(uploaded.name).stem}_ocr.txt",
                               mime="text/plain",use_container_width=True)
        except Exception: pass
=======
            "confidence":            confidence,
            "validation_warnings":   warnings_nlp,
            "ligne_articles":        all_product_lines,
            "nlp_model":             nlp_model_name,
        })

    st.markdown("---")
    c1,c2=st.columns(2)
    with c1:
        st.download_button(
            "⬇ Download JSON",
            data=json.dumps({
                "informations_document": extracted_info,
                "confidence":            confidence,
                "validation_warnings":   warnings_nlp,
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
>>>>>>> 27974b077d1880bd93556e71265a68d585b780a7

    try: os.unlink(tmp_path)
    except: pass