"""
Invoice OCR Pipeline — Streamlit App v5-final
SE24D2 — Automated Invoice Intelligence System

Integrates invoice_extractor_v2.py for:
  - Dynamic table mapping with bounding boxes (solves Qty/Designation merge)
  - Matricule Fiscale top-left rule
  - Document number below "Bon de commande" title
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

st.set_page_config(page_title="Invoice OCR Pipeline", page_icon="🔬",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
    code, .stCode, pre { font-family: 'JetBrains Mono', monospace !important; }
    .stApp { background: #0f1117; color: #e8e8e2; }
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
    ph.markdown(html, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# KNOWN SUPPLIERS
# ─────────────────────────────────────────────────────────────────────────────

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
    return img_bgr

def erase_colored_ink(img_bgr):
    hsv=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2HSV)
    gray=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2GRAY)
    result=img_bgr.copy()
    color_mask=cv2.inRange(hsv,np.array([0,25,40]),np.array([180,255,255]))
    k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
    color_mask=cv2.dilate(color_mask,k,iterations=1)
    dark=(gray<100)
    result[(color_mask>0)&~dark]=[230,230,230]
    result[(color_mask>0)&dark]=[0,0,0]
    return result

def binarize(gray):
    return cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY,blockSize=25,C=8)

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

# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────

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
        alnum=len(re.findall(r'[A-Za-z0-9]',s)); total=len(s)
        if alnum<3: continue
        if 1-alnum/(total+1e-5)>0.60: continue
        if not re.search(r'[A-Za-z]{3,}|\d',s): continue
        lines.append(s)
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# PDFPLUMBER
# ─────────────────────────────────────────────────────────────────────────────

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

def _detect_col_order(lines):
    combined=" ".join(lines[:8]).lower()
    qty_kws=["qté","qty","quantité","quantite","qte","nbre"]
    des_kws=["désignation","designation","libellé","article","description"]
    qty_pos=min((combined.find(k) for k in qty_kws if k in combined),default=9999)
    des_pos=min((combined.find(k) for k in des_kws if k in combined),default=9999)
    return "qty_first" if qty_pos<des_pos and qty_pos<9999 else "des_first"

def extract_product_lines(text):
    items=[]; seen=set()
    lines=text.splitlines()
    col_order=_detect_col_order(lines[:10])
    for raw_line in lines:
        line=raw_line.strip()
        if not line: continue
        line=re.sub(r'^[\|.\-\s]+','',line).strip()
        if not line or len(line)<5: continue
        m_code=CODE_PCT.match(line)
        if not m_code: continue
        code=m_code.group(1).upper()
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
        items.append(item)
    return items

def pdf_page_to_image(pdf_path,page_index,dpi=300):
    doc=fitz.open(pdf_path); page=doc[page_index]
    mat=fitz.Matrix(dpi/72,dpi/72); pix=page.get_pixmap(matrix=mat,alpha=False)
    img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
    return cv2.cvtColor(img,cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)

# ─────────────────────────────────────────────────────────────────────────────
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
    split_zones=st.checkbox("Split Header / Body / Footer OCR",value=True)
    show_raw   =st.checkbox("Show Raw OCR Text",value=False)
    st.markdown("---")
    st.markdown("**Output**")
    show_tables  =st.checkbox("Show pdfplumber Tables",value=True)
    show_products=st.checkbox("Show Product Lines",value=True)
    show_json    =st.checkbox("Show Full JSON",value=False)
    st.markdown("---")
    st.markdown("**Sprint 3 — AI Extraction**")
    run_sprint3 =st.checkbox("Run AI Extraction (SpaCy + LayoutLM)",value=False)
    show_s3_json=st.checkbox("Show Sprint 3 Full JSON",value=False)

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

    is_pdf=uploaded.type=="application/pdf"
    suffix=".pdf" if is_pdf else Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as tmp:
        tmp.write(uploaded.read()); tmp_path=tmp.name

    file_kb=round(len(uploaded.getvalue())/1024,1)
    _log_set("load","done",f"{uploaded.name}  ({file_kb} KB)"); _log_render(_log_ph)

    if is_pdf:
        _log_set("detect","running","reading PDF…"); _log_render(_log_ph)
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
                        f"</div></div>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>Pages</div>"
                        f"<div class='metric-value'>{total_pages}</div></div>",
                        unsafe_allow_html=True)

    st.markdown("---")

    all_header_texts=[]; all_body_texts=[]; all_footer_texts=[]; all_full_texts=[]
    all_clean_imgs=[]; all_orig_imgs=[]; all_pil_imgs=[]
    all_product_lines=[]; seen_codes=set()

    prog=st.progress(0,text="Processing pages…")

    for page_i in range(total_pages):

        # ── Preprocess ────────────────────────────────────────────────
        _log_set("preprocess","running",
                 f"page {page_i+1}/{total_pages}  |  "
                 f"rotation={use_fix_rotation}  color={use_erase_color}  "
                 f"lines={use_remove_lines}  blob={use_keep_mask}")
        _log_render(_log_ph); _pp_t0=_time.time()

        if is_pdf: img_bgr=pdf_page_to_image(tmp_path,page_i,dpi=300)
        else: img_bgr=cv2.imdecode(np.frombuffer(uploaded.getvalue(),dtype=np.uint8),1)

        all_orig_imgs.append(cv2.cvtColor(img_bgr,cv2.COLOR_BGR2RGB))
        work=img_bgr.copy()
        if use_fix_rotation: work=fix_rotation(work)
        if use_erase_color:  work=erase_colored_ink(work)
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
        _log_render(_log_ph)

        if show_products:
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

    prog.empty()

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

    # ── BBox table extraction (universal spatial extractor) ───────────
    _log_set("bbox_table","running",
             "detecting column lanes via word bounding boxes…")
    _log_render(_log_ph); _bbox_t0=_time.time()

    bbox_col_names=[]
    bbox_items=[]

    try:
        from sprint3.invoice_extractor_universal import extract_invoice_data

        # Universal extractor reads the PDF directly (handles native + scanned)
        result = extract_invoice_data(tmp_path, page_index=0)

        # Override regex results with spatial extraction when found
        if result["header"].get("document_number"):
            extracted_info["numero"] = result["header"]["document_number"]
        if result["header"].get("matricule_fiscale"):
            extracted_info["matricule_fiscal"] = result["header"]["matricule_fiscale"]
        if result["header"].get("type"):
            extracted_info["type"] = result["header"]["type"]

        # Map universal extractor keys → DB-style keys for the display table
        raw_items = result.get("lignes_facture", [])
        bbox_items = [
            {
                "Code":       it.get("code", ""),
                "LibProd":    it.get("designation", ""),
                "Quantité":   it.get("quantite", ""),
                "PrixVente":  it.get("prix_unitaire", ""),
                "line_total": it.get("montant", ""),
            }
            for it in raw_items
        ]
        bbox_col_names = result.get("_meta", {}).get("lanes_detected", [])

        _log_set("bbox_table","done",
                 f"{len(bbox_items)} rows  ·  lanes={bbox_col_names}",
                 t0=_bbox_t0)
    except Exception as e:
        _log_set("bbox_table","warn",f"universal extractor failed: {e}")

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
        st.markdown(f"<div class='page-label'>{label}</div>",unsafe_allow_html=True)
        c1,c2=st.columns(2)
        with c1:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#888;"
                        "text-align:center;margin-bottom:4px'>📷 Original</div>",
                        unsafe_allow_html=True)
            st.image(orig_img,use_container_width=True)
        with c2:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#7ee8a2;"
                        "text-align:center;margin-bottom:4px'>✨ After Cleaning</div>",
                        unsafe_allow_html=True)
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
            st.markdown("")

    # ─────────────────────────────────────────────────────────────────
    # RAW OCR
    # ─────────────────────────────────────────────────────────────────

    if show_raw:
        st.markdown("## 📝 Raw OCR Text")
        for page_i in range(total_pages):
            label=f"Page {page_i+1}" if total_pages>1 else "Full text"
            with st.expander(label,expanded=(page_i==0)):
                if split_zones:
                    c1,c2,c3=st.columns(3)
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

    try: os.unlink(tmp_path)
    except: pass
