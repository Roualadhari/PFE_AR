"""
Invoice OCR Pipeline — v4.6
════════════════════════════
New in v4.6 vs v4.5:
  • CRITICAL FIX: accent-stripping in _normalize_h (é→e, è→e, etc.)
    'Désignation' was becoming 'd signation' → column never mapped.
    Now uses unicodedata.normalize('NFKD') before ASCII encoding.
    Fixes designation extraction for ALL document types.
  • avenir_medis.pdf supported:
    - Columns: Code | Qté | Désignation
    - Doc number 1890/2023 (NNN > 12 rule)
    - MF 01232662F/P/M/000 normalised
    - Total H.T from footer bottom zone

Still present from v4.5:
  • JSON SPLIT: *_data.json (clean) vs *_audit.json (debug)
  • MDN-PRF-2308139 Proforma number recognised
  • Proforma footer: total_brut_ht, remise_pct, total_ht, tva, tva_detail,
    transport, timbre_fiscal, total_ttc — all accurate
  • Pharmasud columns: Qte Cmde / Nb Crt / Date P / U crt all stored
  • Omnipharm columns: Code / Qté / Promotion / Désignation
  • Dynamic columns: only columns present in the document shown
  • Fournisseur name card always shown
  • Quantity / date / year validation guards
"""

import streamlit as st
import cv2, numpy as np, pytesseract, pdfplumber, fitz
import re, json, tempfile, os, unicodedata
import time as _time
from pathlib import Path
from PIL import Image
from copy import deepcopy
import spacy
from rapidfuzz import fuzz, process as fuzz_process
import dateparser
from datetime import datetime

try:
    from client import ask_structured_json
except Exception:
    ask_structured_json = None

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════
st.set_page_config(page_title="Invoice OCR Pipeline", page_icon="🔬",
                   layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Syne:wght@400;600;700&display=swap');
html,body,[class*="css"]{font-family:'Syne',sans-serif;}
code,.stCode,pre{font-family:'JetBrains Mono',monospace!important;}
.stApp{background:#0f1117;color:#e8e8e2;}
h1{font-family:'Syne';font-weight:700;letter-spacing:-1px;color:#f0f0ea;}
h2,h3{font-family:'Syne';font-weight:600;color:#d4d4ce;}
.info-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px;}
.metric-card{background:#1a1d26;border:1px solid #2a2d3a;border-radius:8px;padding:14px 16px 12px;position:relative;min-height:72px;}
.addr-card{grid-column:1/-1;}
.metric-label{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;}
.metric-value{font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:600;color:#7ee8a2;word-break:break-word;}
.metric-value.addr-val{color:#7ec8e8;font-size:12px;}
.metric-value.warn-val{color:#e8c87e;}
.metric-value.empty-val{color:#333849;font-style:italic;}
.conf-badge{position:absolute;top:10px;right:10px;font-family:'JetBrains Mono',monospace;font-size:9px;padding:2px 6px;border-radius:6px;font-weight:600;}
.cb-high{background:#1a3a2a;color:#7ee8a2;border:1px solid #2a5a3a;}
.cb-medium{background:#3a3a1a;color:#e8e87e;border:1px solid #5a5a2a;}
.cb-low{background:#3a1a1a;color:#e87e7e;border:1px solid #5a2a2a;}
.conf-hint{font-size:11px;color:#445;margin-bottom:12px;font-family:'JetBrains Mono';}
.tag-bc{background:#1a3a2a;color:#7ee8a2;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #2a5a3a;}
.tag-proforma{background:#1a2a3a;color:#7ec8e8;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #2a4a5a;}
.tag-facture{background:#3a2a1a;color:#e8c87e;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #5a4a2a;}
.tag-stat{background:#2a1a3a;color:#c87ee8;padding:2px 10px;border-radius:12px;font-size:11px;border:1px solid #4a2a5a;}
div[data-testid="stSidebar"]{background:#13151f;border-right:1px solid #1e2130;}
.stButton>button{background:#7ee8a2;color:#0f1117;border:none;font-family:'Syne';font-weight:700;letter-spacing:0.5px;padding:10px 28px;border-radius:6px;width:100%;transition:all 0.2s;}
.stButton>button:hover{background:#a0f0b8;transform:translateY(-1px);}
.raw-text{background:#1a1d26;border:1px solid #2a2d3a;border-radius:8px;padding:16px;font-family:'JetBrains Mono';font-size:11px;color:#b0b0a8;max-height:400px;overflow-y:auto;white-space:pre-wrap;}
.table-container{overflow-x:auto;}
table{width:100%;border-collapse:collapse;font-size:12px;font-family:'JetBrains Mono';}
th{background:#1e2130;color:#7ee8a2;padding:8px 12px;text-align:left;border-bottom:1px solid #2a2d3a;font-weight:600;}
td{padding:7px 12px;border-bottom:1px solid #1e2130;color:#c8c8c2;vertical-align:top;}
tr:hover td{background:#1a1d26;}
.page-label{font-family:'Syne';font-size:12px;color:#555;text-transform:uppercase;letter-spacing:1px;margin:12px 0 4px 0;}
.warn-box{background:#2a1f0a;border:1px solid #5a3a0a;border-radius:8px;padding:10px 16px;margin:8px 0;font-size:12px;color:#e8c87e;}
.warn-box ul{margin:4px 0 0 16px;padding:0;}
.pl-wrap{background:#0d0f17;border:1px solid #1e2130;border-radius:10px;padding:14px 16px;margin-bottom:12px;}
.pl-title{font-family:'Syne';font-size:11px;font-weight:600;color:#555;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px;}
.pl-step{display:flex;align-items:flex-start;gap:10px;padding:7px 0;border-bottom:1px solid #141720;}
.pl-step:last-child{border-bottom:none;}
.pl-icon{font-size:13px;flex-shrink:0;width:18px;text-align:center;margin-top:1px;}
.pl-info{flex:1;min-width:0;}
.pl-name{font-family:'Syne';font-size:12px;}
.pl-detail{font-family:'JetBrains Mono';font-size:10px;color:#445;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.pl-time{font-family:'JetBrains Mono';font-size:10px;color:#445;flex-shrink:0;padding-left:8px;align-self:center;}
.s-pending .pl-name{color:#383c50;}.s-running .pl-name{color:#7ee8a2;}
.s-done .pl-name{color:#c8c8c2;}.s-skip .pl-name{color:#333849;font-style:italic;}
.s-warn .pl-name{color:#e8c87e;}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# PIPELINE LOG
# ═══════════════════════════════════════════════════════════════
_STEPS=[("load","📂","Load file"),("detect","🔍","Detect PDF type"),
        ("preprocess","🧹","Preprocess image(s)"),("ocr","🔤","OCR text extraction"),
        ("pdfplumber","📊","pdfplumber tables"),("regex","🔎","Regex baseline extraction"),
        ("nlp","🧠","NLP enrichment"),("products","📦","Product line extraction"),
        ("done","✅","Pipeline complete")]

def _log_init():
    st.session_state["_pl"]={k:{"status":"pending","detail":"","t":""} for k,*_ in _STEPS}

def _log_set(key,status,detail="",t0=0.0):
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
    ph.markdown(html,unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# NLP MODEL
# ═══════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def load_nlp():
    for m in ("fr_core_news_sm","en_core_web_sm"):
        try: return spacy.load(m),m
        except OSError: pass
    return spacy.blank("fr"),"blank_fr"

# ═══════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════
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

def _to_float_soft(v):
    try: return _to_float(str(v))
    except: return None

def _is_date_like(s):
    s=str(s or "").strip()
    if re.match(r'^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}$',s): return True
    if re.match(r'^\d{6,8}$',s): return True
    return False

def _is_qty_valid(val,doc_type=""):
    if val is None: return False
    try: f=float(val)
    except: return False
    if f<=0 or f>500000: return False
    if 1900<=f<=2100: return False
    if ("proforma" in doc_type.lower() or "bon de commande" in doc_type.lower()) and f>50000:
        return False
    return True

def _clean_designation(s):
    t=str(s or "").strip()
    t=re.sub(r'^[\-\*\!\~\=\+\#\|]+\s*','',t).strip()
    t=re.sub(r'[\!\~\=\*\#\|]+$','',t).strip()
    t=re.sub(r'\s{2,}',' ',t)
    return t

def _normalize_h(s):
    """FIX v4.6: NFKD unicode decomposition → ASCII so é→e, à→a, etc."""
    x=str(s or "").lower().strip()
    x=unicodedata.normalize('NFKD',x).encode('ascii','ignore').decode('ascii')
    x=re.sub(r'[^a-z0-9\s]',' ',x)
    x=re.sub(r'\s+',' ',x).strip()
    return x

def _conf_badge_html(conf):
    pct=int(conf*100)
    cls="cb-high" if conf>=0.80 else "cb-medium" if conf>=0.55 else "cb-low"
    return f"<span class='conf-badge {cls}'>{pct}%</span>"

# ═══════════════════════════════════════════════════════════════
# FOURNISSEUR NAME
# ═══════════════════════════════════════════════════════════════
_COMPANY_KW=re.compile(
    r'\b(sarl|s\.a\.r\.l|s\.a\.|s\.a\b|spa|suarl|sas|ste\b|soci[eé]t[eé]|'
    r'repartition|r[eé]partiteur|grossiste|laboratoire|pharma|distribution|'
    r'm[eé]dicament|medical|import|export|commerce|groupe|holding|avenir|rekik)\b',
    re.IGNORECASE)

def extract_fournisseur_name(header_text):
    lines=[l.strip() for l in header_text.splitlines() if l.strip()]
    STOP=re.compile(
        r'^(route|rue|avenue|av\.|bd\.|date|tel|fax|m\.f|r\.c|page|code|email'
        r'|sfax|tunis|nabeul|sousse|sfax le|edite|prepare|medis\b)',re.IGNORECASE)
    for line in lines[:12]:
        if _COMPANY_KW.search(line) and not STOP.match(line):
            return line[:120].strip()
    for line in lines[:6]:
        if STOP.match(line): continue
        words=line.split()
        if len(words)>=2 and re.search(r'[A-Za-z]{3,}',line):
            if not re.match(r'^[A-Z]{2,4}\d',line) and not re.match(r'^\d',line):
                return line[:120].strip()
    return ""

# ═══════════════════════════════════════════════════════════════
# PROFORMA FOOTER
# ═══════════════════════════════════════════════════════════════
def extract_proforma_summary(text):
    result={}
    def _grab(pattern):
        m=re.search(pattern,text,re.IGNORECASE|re.DOTALL)
        if not m: return None
        nums=re.findall(r'\d[\d\s]*[,\.]\d{2,3}|\d{4,}',m.group(1))
        for raw in reversed(nums):
            v=_to_float(raw)
            if v is not None and v>=0: return v
        return None

    v=_grab(r'Total\s+Brut\s+HT\s*[:\s]+([\d\s,\.]+)')
    if v and v>100: result['total_brut_ht']=v
    m=re.search(r'Total\s+Remis[e\xe9]\s*[:\s]*\(?\s*(\d+[,\.]?\d*)\s*%?\s*\)?',text,re.I)
    if m:
        rv=_to_float(m.group(1))
        if rv is not None: result['remise_pct']=rv
    v=_grab(r'Total\s+Net\s+HT\s*[:\s]+([\d\s,\.]+)')
    if v and v>100: result['total_ht']=v
    for line in text.splitlines():
        ln=line.strip()
        if re.match(r'^TVA\s*[:\-]',ln,re.I):
            if re.search(r'\b(base|valeur|type)\b',ln,re.I): continue
            nums=re.findall(r'\d[\d\s]*[,\.]\d{2,3}',ln)
            for raw in reversed(nums):
                v2=_to_float(raw)
                if v2 and v2>50: result['tva']=v2; break
            if 'tva' in result: break
    tva_rows=[]
    for m in re.finditer(r'%\s+(\d+[,\.]\d{1,2})\s+([\d\s,\.]+)\s+([\d\s,\.]+)',text):
        rate=_to_float(m.group(1)); base=_to_float(re.sub(r'\s','',m.group(2))); val=_to_float(re.sub(r'\s','',m.group(3)))
        if rate is not None and base is not None and val is not None:
            tva_rows.append({"taux":rate,"base":base,"valeur":val})
    if tva_rows:
        result['tva_detail']=tva_rows
        if 'tva' not in result:
            total_tva=sum(r['valeur'] for r in tva_rows)
            if total_tva>0: result['tva']=round(total_tva,3)
    v=_grab(r'Transport\s*[:\s]+([\d\s,\.]+)')
    if v is not None: result['transport']=v
    v=_grab(r'Timbre\s+Fiscal\s*[:\s]+([\d\s,\.]+)')
    if v is not None: result['timbre_fiscal']=v
    v=_grab(r'Total\s+TT[Cc]\s*[:\s]+([\d\s,\.]+)')
    if v and v>100: result['total_ttc']=v
    return result

# ═══════════════════════════════════════════════════════════════
# COLUMN SCHEMA
# ═══════════════════════════════════════════════════════════════
_HEADER_SYNONYMS={
    "code_pct":["code pct","code ptc","pct","code produit","code","code article local","no article","ref"],
    "code_article":["code article","article code","ref article","reference article","code frs","code fourn"],
    "designation":["designation","designation article","designation produit","libelle","article","produit","desig"],
    "unit":["un","u","unite","unit","u n","conditionnement","cond"],
    "quantity":["qte","qte","quantite","quantity","qty","qte cmde","qtecmde","qte commande","qte ord"],
    "nb_crt":["nb crt","nb  crt","nombre cartons","nb carton","nbre crt","nbcrt"],
    "unit_price":["prix unitaire","p u","prix u","pu","unit price","prix","pu ht"],
    "amount":["montant","mt","total ligne","amount","prix total","montant ht","mnt"],
    "date":["date p","date peremption","date limite","dluo","date exp","expiry","peremption"],
    "u_crt":["u crt","u  crt","unite carton","unites par carton","ucrt"],
    "promotion":["promotion","promo"],
}
_OUTPUT_ORDER=["code","code_article","designation","unite","quantite","nb_crt","u_crt","prix_unitaire","montant","date_peremption","promotion"]
_COL_LABELS={"code":"Code PCT","code_article":"Code Article","designation":"Désignation","unite":"U.N.","quantite":"Qté","nb_crt":"Nb Crt","u_crt":"U Crt","prix_unitaire":"Prix Unitaire","montant":"Montant","date_peremption":"Date P","promotion":"Promotion"}
_CANON_TO_KEY={"code_pct":"code","code_article":"code_article","designation":"designation","unit":"unite","quantity":"quantite","unit_price":"prix_unitaire","amount":"montant","date":"date_peremption","u_crt":"u_crt","nb_crt":"nb_crt","promotion":"promotion"}

def _score_header(hn,syn):
    if not hn or not syn: return 0.0
    if hn==syn: return 1.0
    if syn in hn: return 0.85
    h=set(hn.split()); s=set(syn.split())
    inter=len(h&s)
    return inter/max(1,len(s)) if inter else 0.0

def _map_headers(headers):
    col_map={}; dbg={}
    for idx,h in enumerate(headers):
        hn=_normalize_h(h)
        best=("",0.0)
        for canon,syns in _HEADER_SYNONYMS.items():
            for syn in syns:
                sc=_score_header(hn,_normalize_h(syn))
                if sc>best[1]: best=(canon,sc)
        selected=best[0] if best[1]>=0.45 else ""
        dbg[idx]={"raw":h,"normalized":hn,"canonical":selected,"score":round(best[1],3)}
        if selected and selected not in col_map: col_map[selected]=idx
    return col_map,dbg

# ═══════════════════════════════════════════════════════════════
# TABLE LINE ITEM EXTRACTION
# ═══════════════════════════════════════════════════════════════
def _is_valid_item_code(token,doc_type="",row_text=""):
    t=str(token or "").strip().upper()
    if re.fullmatch(r'[A-Z]{2,4}\d{2,12}',t): return True
    if re.fullmatch(r'\d{4,6}',t): return True
    if re.fullmatch(r'[A-Z]{2,3}\d{3,}',t): return True
    if re.fullmatch(r'CAM\d{3,}',t): return True
    return False

def extract_line_items_from_tables(tables,doc_type=""):
    items=[]; audit={"detected_headers":[],"column_map":{},"row_rejections":[],"structured_item_count":0,"detected_schema":set()}
    seen=set()
    for t_idx,table in enumerate(tables or []):
        if not table or len(table)<2: continue
        headers=[str(x or "").strip() for x in table[0]]
        col_map,dbg=_map_headers(headers)
        if not col_map: continue
        audit["detected_headers"].append({"table_index":t_idx,"headers":headers,"header_debug":dbg})
        audit["column_map"][str(t_idx)]={k:int(v) for k,v in col_map.items()}
        audit["detected_schema"].update(col_map.keys())
        prev_idx=-1
        for r_idx,row in enumerate(table[1:],start=1):
            if not any(str(c or "").strip() for c in row): continue
            def get(canon):
                idx=col_map.get(canon)
                if idx is None or idx>=len(row): return ""
                return str(row[idx] or "").strip()
            row_txt=" ".join(str(c or "") for c in row)
            code=get("code_pct") or get("code_article")
            if not code:
                m=re.search(r'\b([A-Z]{2,4}\d{2,12}|\d{4,6})\b',row_txt,re.I)
                code=m.group(1).upper() if m else ""
            designation=_clean_designation(get("designation"))
            if not _is_valid_item_code(code,doc_type=doc_type,row_text=row_txt):
                if prev_idx>=0 and designation and len(designation)>=3:
                    prev_desc=str(items[prev_idx].get("designation","")).strip()
                    items[prev_idx]["designation"]=(prev_desc+" "+designation).strip() if prev_desc else designation
                    audit["row_rejections"].append({"table_index":t_idx,"row_index":r_idx,"reason":"continuation_merged"})
                else:
                    audit["row_rejections"].append({"table_index":t_idx,"row_index":r_idx,"reason":"invalid_code"})
                continue
            item={"code":code}
            if designation and len(designation)>=2: item["designation"]=designation
            else:
                tail=re.sub(r'^\s*'+re.escape(str(code))+r'\b','',row_txt,flags=re.I).strip()
                if len(tail)>=3: item["designation"]=_clean_designation(tail)
            if "code_article" in col_map and get("code_article"): item["code_article"]=get("code_article")
            un=get("unit")
            if un: item["unite"]=un
            raw_qty=get("quantity")
            if raw_qty and not _is_date_like(raw_qty):
                q=_to_float_soft(raw_qty)
                if _is_qty_valid(q,doc_type): item["quantite"]=q
                else: audit["row_rejections"].append({"table_index":t_idx,"row_index":r_idx,"code":code,"reason":"invalid_qty","raw_qty":raw_qty})
            if "nb_crt" in col_map:
                raw_nb=get("nb_crt")
                if raw_nb and not _is_date_like(raw_nb):
                    nb=_to_float_soft(raw_nb)
                    if nb and 0<nb<100000: item["nb_crt"]=nb
            if "u_crt" in col_map:
                raw_uc=get("u_crt")
                if raw_uc:
                    uc=_to_float_soft(raw_uc)
                    if uc and 0<uc<100000: item["u_crt"]=uc
            if "date" in col_map:
                raw_dt=get("date")
                if raw_dt: item["date_peremption"]=raw_dt
            if "promotion" in col_map:
                promo=get("promotion")
                if promo: item["promotion"]=promo
            pu=_to_float_soft(get("unit_price")); mt=_to_float_soft(get("amount"))
            if pu and pu>0: item["prix_unitaire"]=pu
            if mt and mt>0: item["montant"]=mt
            if code not in seen: seen.add(code); items.append(item); prev_idx=len(items)-1
    audit["structured_item_count"]=len(items)
    return items,audit

def merge_line_items(primary,fallback):
    merged=[]; seen=set()
    fb={str(i.get("code","")).upper():i for i in (fallback or []) if i.get("code")}
    for p in primary or []:
        code=str(p.get("code","")).upper()
        base=deepcopy(fb.get(code,{})); base.update(p)
        merged.append(base)
        if code: seen.add(code)
    for f in fallback or []:
        code=str(f.get("code","")).upper()
        if code and code in seen: continue
        merged.append(f)
    return merged

def normalize_line_items_for_json(items,detected_schema=None):
    if not items: return []
    always={"code","designation","quantite"}
    if detected_schema:
        allowed=always.copy()
        for canon in detected_schema:
            allowed.add(_CANON_TO_KEY.get(canon,canon))
    else:
        meta={"qty_source","qty_to_order","quantity"}
        present=set()
        for item in items:
            for k,v in item.items():
                if k in meta or k.startswith("_"): continue
                if str(v).strip() not in("","None"): present.add(k)
        allowed=present|always
    schema=[k for k in _OUTPUT_ORDER if k in allowed]
    for k in sorted(allowed):
        if k not in schema: schema.append(k)
    normalized=[]
    for item in items:
        row={k:item.get(k,"") for k in schema}
        row["designation"]=_clean_designation(str(row.get("designation","")))
        qv=row.get("quantite","")
        if qv not in("",None):
            try:
                qf=float(qv)
                if not _is_qty_valid(qf): row["quantite"]=""
            except: row["quantite"]=""
        normalized.append(row)
    return normalized

# ═══════════════════════════════════════════════════════════════
# DOCUMENT PAYLOAD
# ═══════════════════════════════════════════════════════════════
def build_document_payload(extracted_info):
    doc={"type":extracted_info.get("type","") or "","numero":extracted_info.get("numero","") or "","date":extracted_info.get("date","") or "","fournisseur_nom":extracted_info.get("fournisseur_nom","") or "","supplier_mf":extracted_info.get("supplier_mf","") or "","client_mf":extracted_info.get("client_mf","") or "","tel":extracted_info.get("tel","") or "","fax":extracted_info.get("fax","") or "","email":extracted_info.get("email","") or "","rc":extracted_info.get("rc","") or "","adresse":extracted_info.get("adresse","") or "","total_brut_ht":extracted_info.get("total_brut_ht",None),"remise_pct":extracted_info.get("remise_pct",None),"total_ht":extracted_info.get("total_ht",None),"tva":extracted_info.get("tva",None),"tva_detail":extracted_info.get("tva_detail",None),"transport":extracted_info.get("transport",None),"timbre_fiscal":extracted_info.get("timbre_fiscal",None),"total_ttc":extracted_info.get("total_ttc",None)}
    clean={}
    for k,v in doc.items():
        if v is None or v=="" or v==[]: continue
        clean[k]=v
    if "type" not in clean: clean["type"]=""
    return clean

def build_clean_json(document_payload,line_items):
    return {"document":document_payload,"line_items":line_items}

def build_audit_json(confidence,warnings_nlp,extraction_trace,table_extraction_audit,rejected_candidates,llm_validation,promotion_decisions,nlp_model_name):
    return {"confidence":confidence,"validation_warnings":warnings_nlp,"extraction_trace":extraction_trace,"table_extraction":table_extraction_audit,"rejected_candidates":rejected_candidates,"llm_validation":llm_validation,"promotion_decisions":promotion_decisions,"nlp_model":nlp_model_name}

# ═══════════════════════════════════════════════════════════════
# PREPROCESSING
# ═══════════════════════════════════════════════════════════════
def fix_rotation(img_bgr):
    try:
        gray_temp=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2GRAY)
        osd=pytesseract.image_to_osd(gray_temp,config="--psm 0 -c min_characters_to_try=5")
        angle_m=re.search(r"Rotate: (\d+)",osd); conf_m=re.search(r"Orientation confidence: ([\d\.]+)",osd)
        if angle_m and (float(conf_m.group(1)) if conf_m else 0)>=2.0:
            a=int(angle_m.group(1))
            if a==90: img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif a==180: img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_180)
            elif a==270: img_bgr=cv2.rotate(img_bgr,cv2.ROTATE_90_CLOCKWISE)
    except: pass
    return img_bgr

def erase_colored_ink(img_bgr):
    hsv=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2HSV); gray=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2GRAY); result=img_bgr.copy()
    cm=cv2.inRange(hsv,np.array([0,25,40]),np.array([180,255,255])); k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5)); cm=cv2.dilate(cm,k,iterations=1)
    dark=(gray<100); result[(cm>0)&~dark]=[230,230,230]; result[(cm>0)&dark]=[0,0,0]
    return result

def binarize(gray):
    return cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,blockSize=25,C=8)

def remove_long_lines(binary):
    inv=cv2.bitwise_not(binary)
    h_k=cv2.getStructuringElement(cv2.MORPH_RECT,(80,1)); v_k=cv2.getStructuringElement(cv2.MORPH_RECT,(1,80))
    lm=cv2.add(cv2.morphologyEx(inv,cv2.MORPH_OPEN,h_k),cv2.morphologyEx(inv,cv2.MORPH_OPEN,v_k))
    nl,labels,stats,_=cv2.connectedComponentsWithStats(inv,8); tp=np.zeros_like(binary)
    for i in range(1,nl):
        bw=stats[i,cv2.CC_STAT_WIDTH]; bh=stats[i,cv2.CC_STAT_HEIGHT]; ar=stats[i,cv2.CC_STAT_AREA]
        if 5<=bw<=120 and 5<=bh<=120 and 20<=ar<=8000: tp[labels==i]=255
    pk=cv2.getStructuringElement(cv2.MORPH_RECT,(3,3)); tp=cv2.dilate(tp,pk,iterations=1)
    safe=cv2.bitwise_and(lm,cv2.bitwise_not(tp)); inv[safe>0]=0
    return cv2.bitwise_not(inv)

def stroke_cv(blob):
    ek=cv2.getStructuringElement(cv2.MORPH_CROSS,(3,3)); cur,counts=blob.copy(),[]
    for _ in range(15):
        cur=cv2.erode(cur,ek); n=cv2.countNonZero(cur); counts.append(n)
        if n==0: break
    if len(counts)<2: return 999.0
    nz=np.array(counts,dtype=float); nz=nz[nz>0]
    return float(np.std(nz)/(np.mean(nz)+1e-5)) if len(nz) else 999.0

def build_keep_mask(binary):
    inv=cv2.bitwise_not(binary); nl,labels,stats,_=cv2.connectedComponentsWithStats(inv,8); km=np.zeros_like(binary)
    for i in range(1,nl):
        bx=stats[i,cv2.CC_STAT_LEFT]; by=stats[i,cv2.CC_STAT_TOP]; bw=stats[i,cv2.CC_STAT_WIDTH]; bh=stats[i,cv2.CC_STAT_HEIGHT]
        area=stats[i,cv2.CC_STAT_AREA]; asp=max(bw,bh)/(min(bw,bh)+1e-5)
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

def enhance_kept_text(binary,km):
    ek=cv2.getStructuringElement(cv2.MORPH_RECT,(2,2)); km=cv2.dilate(km,ek,iterations=1)
    r=np.full_like(binary,255); r[km>0]=0
    return r

# ═══════════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════════
def ocr_full_page(img):
    return pytesseract.image_to_string(img,lang="fra+eng",config="--psm 6 --oem 1").strip()

def ocr_header_zone(img):
    h=img.shape[0]
    return pytesseract.image_to_string(img[:int(h*0.30),:],lang="fra+eng",config="--psm 4 --oem 1").strip()

def ocr_header_layout_lines(img):
    h,w=img.shape[:2]; header=img[:int(h*0.30),:]
    data=pytesseract.image_to_data(header,lang="fra+eng",config="--psm 4 --oem 1",output_type=pytesseract.Output.DICT)
    groups={}
    for i in range(len(data.get("text",[]))):
        txt=(data["text"][i] or "").strip()
        if not txt: continue
        key=(data["block_num"][i],data["par_num"][i],data["line_num"][i])
        left=int(data["left"][i]); wid=int(data["width"][i])
        g=groups.setdefault(key,{"parts":[],"left":left,"right":left+wid})
        g["parts"].append((left,txt)); g["left"]=min(g["left"],left); g["right"]=max(g["right"],left+wid)
    out=[]
    for g in groups.values():
        parts=[t for _,t in sorted(g["parts"],key=lambda x:x[0])]
        text_line=" ".join(parts).strip()
        if not text_line: continue
        x_center=(g["left"]+g["right"])/2.0
        out.append({"text":text_line,"x_norm":round(x_center/max(1,w),4),"left":g["left"],"right":g["right"]})
    return sorted(out,key=lambda x:(x["x_norm"],x["left"]))

def ocr_body_zone(img):
    h=img.shape[0]
    return pytesseract.image_to_string(img[int(h*0.22):int(h*0.92),:],lang="fra+eng",config="--psm 6 --oem 1").strip()

def clean_ocr_text(text):
    text=re.sub(r'\(cid:\d+\)','',text)
    text=re.sub(r'(?<!\w)([A-Z] ){3,}([A-Z])(?!\w)',lambda m:m.group(0).replace(' ',''),text)
    text=re.sub(r'(?<!\w)((?:[A-Z0-9] ){4,}[A-Z0-9])(?!\w)',lambda m:m.group(0).replace(' ',''),text)
    text=re.sub(r'(?<=\d)l(?=\d)','1',text); text=re.sub(r'(?<=\d)I(?=\d)','1',text)
    text=re.sub(r'(\d)°o',r'\g<1>0',text); text=re.sub(r'(\d)°(?=\d)',r'\g<1>0',text)
    text=re.sub(r'(?<=[A-Za-z0-9])\|(?=[A-Za-z0-9])',' ',text)
    text=re.sub(r'^\s*\|\s*$','',text,flags=re.MULTILINE)
    text=re.sub(r'(?i)\b(on de commande)\b','Bon de commande',text)
    text=re.sub(r'(?i)\b(on de livraison)\b','Bon de livraison',text)
    text=re.sub(r'[=~_—]{2,}',' ',text); text=re.sub(r'[ \t]{2,}',' ',text)
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

# ═══════════════════════════════════════════════════════════════
# PDFPLUMBER
# ═══════════════════════════════════════════════════════════════
def extract_tables_pdfplumber(pdf_path):
    strategies=[{"vertical_strategy":"lines","horizontal_strategy":"lines","intersection_tolerance":5},{"vertical_strategy":"lines","horizontal_strategy":"lines","intersection_tolerance":10},{"vertical_strategy":"text","horizontal_strategy":"lines","intersection_tolerance":5},{"vertical_strategy":"lines","horizontal_strategy":"text","intersection_tolerance":5},{"vertical_strategy":"text","horizontal_strategy":"text","intersection_tolerance":3}]
    all_tables=[]
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_tables=None
            for strat in strategies:
                try:
                    tbls=page.extract_tables(strat)
                    if tbls and any(len(t)>=3 for t in tbls): page_tables=tbls; break
                except: continue
            for table in (page_tables or []):
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

# ═══════════════════════════════════════════════════════════════
# REGEX BASELINE
# ═══════════════════════════════════════════════════════════════
DOC_TYPES={"Proforma":["proforma","b.c. interne","incoterms","date/heure livraison","bcm-"],"Bon de Commande":["bon de commande","commande fournisseur","bcn-","bc n°","bon de commande n°"],"Facture":["facture","invoice","facture numéro"],"Statistiques":["statistique","quantitatif des ventes","stat. ventes","quantité proposée","moyenne des ventes"],"Chiffre d'Affaires":["chiffre d'affaire","ventes et chiffre"]}

def detect_doc_type(text):
    tl=text.lower()
    for dtype,kws in DOC_TYPES.items():
        if any(k in tl for k in kws): return dtype
    return "Document"

_ADDR_ANCHOR=re.compile(r'\b(route|rue|avenue|av\.?|bd\.?|boulevard|cit[eé]|zone\s+ind|lot\s+n?[°o]?|lotissement|impasse|r[eé]sidence|quartier|km\s*\d|n[°o]\s*\d{1,4}\s+(?:rue|route|av))\b',re.IGNORECASE)

def extract_address(header_text):
    lines=[l.strip() for l in header_text.splitlines() if l.strip()]
    STOP=re.compile(r'^(tel|t[eé]l|fax|m\.?f|r\.?c|sfax|tunis|nabeul|sousse|monastir|date|page|code|email|pr[eé]par|[eé]dit[eé]|bon\s+de|facture|proforma|commande|medis|omnipharm|pharma|distribution|laboratoire|code\s+frs|code\s+pct|sfax\s+le|page\s+n)',re.IGNORECASE)
    for i,line in enumerate(lines):
        if not _ADDR_ANCHOR.search(line): continue
        block=[line]
        if i+1<len(lines):
            nxt=lines[i+1]
            if not STOP.match(nxt) and 4<len(nxt)<100: block.append(nxt)
        result=" — ".join(block)
        if re.search(r'\b(tel|t[eé]l|fax|email|@)\b',result,re.I): continue
        return result[:120].rstrip(" —")
    return ""

def _normalize_mf(raw):
    if not raw: return "",False
    cleaned=re.sub(r'[^A-Za-z0-9]','',raw).upper()
    m=re.match(r'^([0-9]{6,8})([A-Z])([A-Z])([A-Z])([0-9]{3})$',cleaned)
    if not m:
        cleaned2=cleaned.replace('O','0').replace('I','1').replace('L','1')
        m=re.match(r'^([0-9]{6,8})([A-Z])([A-Z])([A-Z])([0-9]{3})$',cleaned2)
        if m: cleaned=cleaned2
        else: return "",False
    d1,l1,l2,l3,d2=m.groups()
    if not(6<=len(d1)<=8 and len(d2)==3): return "",False
    return f"{d1}{l1}/{l2}/{l3}/{d2}",False

def _resolve_mf_roles(header_text,full_text,header_layout_lines=None):
    MF_PAT=re.compile(r'(?:m\.?\s*f\.?\s*[:\-]\s*)?([0-9A-Z]{6,})[/\\|\s\-]*([A-Z])[/\\|\s\-]*([A-Z])[/\\|\s\-]*([A-Z])[/\\|\s\-]*([0-9]{3,4})\b',re.IGNORECASE)
    candidates=[]
    for line in header_text.splitlines():
        ln=line.strip()
        for m in MF_PAT.finditer(ln):
            raw="".join(m.groups()); norm,_=_normalize_mf(raw)
            if not norm: continue
            at_start=bool(re.match(r'^\s*m\.?\s*f\.?\s*[:\-]',ln,re.I))
            rel_pos=m.start()/max(1,len(ln))
            candidates.append({"value":norm,"at_start":at_start,"rel_pos":rel_pos,"line":ln})
    if not candidates: return "","",[]
    supplier_cands=[c for c in candidates if c["at_start"] or c["rel_pos"]<0.45]
    client_cands=[c for c in candidates if not c["at_start"] and c["rel_pos"]>=0.45]
    supplier_mf=min(supplier_cands,key=lambda x:x["rel_pos"])["value"] if supplier_cands else ""
    client_mf=max(client_cands,key=lambda x:x["rel_pos"])["value"] if client_cands else ""
    if not client_mf and len(candidates)>=2:
        others=[c for c in candidates if c["value"]!=supplier_mf]
        if others: client_mf=max(others,key=lambda x:x["rel_pos"])["value"]
    return supplier_mf,client_mf,candidates

def _extract_numero(text):
    lines=[ln.strip() for ln in text.splitlines()]
    # 1. Line after heading
    for i,ln in enumerate(lines):
        if re.search(r'bon\s+de\s+commande|proforma|commande\b|facture',ln,re.I):
            for j in(i+1,i+2):
                if j>=len(lines): continue
                m=re.search(r'\b(\d{3,6}\s*/\s*\d{4})\b',lines[j])
                if m:
                    cand=re.sub(r'\s+','',m.group(1)); parts=cand.split('/')
                    if len(parts)==2 and int(parts[0])>12: return cand
                m=re.search(r'\b([A-Z]{2,8}-[A-Z]{2,8}-[A-Z0-9]{4,12})\b',lines[j],re.I)
                if m: return m.group(1).upper()
    # 2. Proforma N°
    m=re.search(r'PROFORMA\s+N[°o][:\s]*([A-Z0-9][\w\-]{4,25})',text,re.I)
    if m:
        cand=re.sub(r'\s+','',m.group(1)).strip(".,;:")
        if len(cand)>=4: return cand
    # 3. BCN/BCM
    for pat in(r'\b(BCN-[A-Z0-9]{2}-\d{4})\b',r'\b(BCM-[A-Z0-9]{2}-\d{4})\b',r'\b(BCM-\d{2}-\d{4})\b',r'\b(BCN\d{2}-\d{4})\b'):
        m=re.search(pat,text,re.IGNORECASE)
        if m: return m.group(1).upper()
    # 4. MDN-PRF style
    m=re.search(r'\b([A-Z]{2,8}-[A-Z]{2,8}-\d{6,12})\b',text,re.I)
    if m: return m.group(1).upper()
    # 5. Bon de commande N°
    m=re.search(r'Bon\s+de\s+commande\s+N[°o][°\.\s:]*\s*(\w[\w\-]{2,20})',text,re.I)
    if m:
        cand=re.sub(r'\s+','',m.group(1)).strip(".,;:")
        if len(cand)>=3: return cand
    # 6. Bare NNN/YYYY
    for m in re.finditer(r'\b(\d{3,6})\s*/\s*(\d{4})\b',text):
        d,y=m.group(1),m.group(2)
        if int(d)>12: return f"{d}/{y}"
    return ""

def extract_info(text,header_text,header_layout_lines=None):
    info={}; trace={"mf_candidates":[],"amount_candidates":{},"selected":{},"rejections":[]}
    info["type"]=detect_doc_type(text)
    numero=_extract_numero(text)
    if numero: info["numero"]=numero; trace["selected"]["numero"]=numero
    m=re.search(r'Date\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',text,re.I)
    if not m: m=re.search(r'\b(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})\b',text)
    if m: info["date"]=m.group(1)
    supplier_mf,client_mf,mf_cands=_resolve_mf_roles(header_text,text,header_layout_lines)
    trace["mf_candidates"]=mf_cands[:8]
    if supplier_mf: info["supplier_mf"]=supplier_mf; info["matricule_fiscal"]=supplier_mf
    if client_mf: info["client_mf"]=client_mf
    fournisseur_nom=extract_fournisseur_name(header_text)
    if fournisseur_nom: info["fournisseur_nom"]=fournisseur_nom
    m=re.search(r'T[eé]l[:\.\s/]*(\+?\d[\d\s\.\-]{6,20}\d)',text,re.I)
    if m:
        digits=re.sub(r'\D','',m.group(1))
        if digits.startswith("216") and len(digits)>8: digits=digits[-8:]
        if len(digits) in(8,10,11): info["tel"]=digits
    m=re.search(r'Fax[:\.\s]*([\d][\d\s\.\-]{6,20}\d)',text,re.I)
    if m:
        digits=re.sub(r'\D','',m.group(1))
        if len(digits) in(8,10,11): info["fax"]=digits
    m=re.search(r'[\w\.-]+@[\w\.-]+\.\w{2,}',text)
    if m: info["email"]=m.group(0)
    m=re.search(r'R\.?C\.?\s*[:\-]?\s*([A-Z][A-Z0-9]{5,14})',text,re.I)
    if m: info["rc"]=m.group(1)
    addr=extract_address(header_text)
    if addr: info["adresse"]=addr
    return {k:v for k,v in info.items() if v},trace

def _extract_totals(all_full_texts,info,doc_type):
    result=dict(info); full="\n".join(all_full_texts)
    if "proforma" in doc_type.lower():
        summary=extract_proforma_summary(full)
        result.update({k:v for k,v in summary.items() if v is not None})
        return result
    _NUM=re.compile(r'\d[\d\s]*[,\.]\d{2,3}|\d{4,}')
    def _first_val(line,minimum=500.0):
        for raw in _NUM.findall(line):
            v=_to_float(raw)
            if v and v>=minimum and not(1900<=v<=2100): return v
        return None
    bottom_lines=[]
    for pg in all_full_texts:
        plines=[l for l in pg.splitlines() if l.strip()]
        bottom_lines.extend(plines[-80:])
    for ln in bottom_lines:
        s=ln.strip()
        if not s: continue
        if "total_ht" not in result and re.match(r'^(Total\s+Net\s+HT|Total\s+HT|Montant\s+HT|Total\s+H\.T)',s,re.I):
            v=_first_val(s,500)
            if v: result["total_ht"]=v
        if "tva" not in result and re.match(r'^TVA\s*[:\-]',s,re.I):
            if not re.search(r'\b(base|valeur|type)\b',s,re.I):
                v=_first_val(s,100)
                if v: result["tva"]=v
        if "total_ttc" not in result and re.match(r'^Total\s+TT?C|^Net\s+[àa]\s+payer',s,re.I):
            v=_first_val(s,500)
            if v: result["total_ttc"]=v
    return result

def extract_product_lines(text,doc_type=""):
    items=[]; seen=set()
    CODE_PCT=re.compile(r'^([A-Z]{2,4}\d{2,12}|\d{4,6})',re.IGNORECASE)
    CODE_ART=re.compile(r'^([A-Z]{2,4}\d{5,12})\b',re.IGNORECASE)
    for raw_line in text.splitlines():
        line=raw_line.strip()
        if not line: continue
        line=re.sub(r'^[\|.\-\s]+','',line).strip()
        if not line or len(line)<5: continue
        m_code=CODE_PCT.match(line)
        if not m_code: continue
        code=m_code.group(1).upper()
        if not _is_valid_item_code(code,doc_type=doc_type,row_text=line): continue
        if code in seen: continue
        rest=line[len(m_code.group(0)):].strip()
        if len(rest)<2: continue
        code_article=""
        m_art=CODE_ART.match(rest)
        if m_art:
            code_article=m_art.group(1).upper()
            rest=rest[len(code_article):].strip().lstrip('-').strip()
        rest=re.sub(r"^[\|\.'\"()\[\]\-_\s]+",'',rest).strip()
        if not rest: continue
        price_m=re.search(r'\b\d{1,6}[,\.]\d{2,3}\b',rest)
        text_part=rest[:price_m.start()].strip() if price_m else rest
        tokens=text_part.split(); num_tail=[]; i=len(tokens)-1
        while i>=0:
            t=tokens[i]
            if re.match(r'^\d{1,5}$',t) and not _is_date_like(t): num_tail.insert(0,int(t)); i-=1
            else: break
        designation=_clean_designation(" ".join(tokens[:i+1]))
        if not designation or len(designation)<3: continue
        qty=None
        if num_tail and _is_qty_valid(num_tail[0],doc_type): qty=float(num_tail[0])
        seen.add(code)
        item={"code":code,"designation":designation}
        if code_article: item["code_article"]=code_article
        if qty: item["quantite"]=qty
        items.append(item)
    return items,[]

# ═══════════════════════════════════════════════════════════════
# NLP LAYER
# ═══════════════════════════════════════════════════════════════
_DOC_TYPE_LABELS={"Proforma":["proforma","bc interne","incoterms","pro forma"],"Bon de Commande":["bon de commande","commande fournisseur","bcn","bon commande"],"Facture":["facture","invoice","facture numero"],"Statistiques":["statistique","quantitatif des ventes","stat ventes"],"Chiffre d'Affaires":["chiffre affaire","ventes et chiffre"]}

def _fuzzy_doc_type(text):
    snippet=re.sub(r'[^\w\s]',' ',text[:400].lower())
    best_type,best_score="Document",0.0
    for dtype,labels in _DOC_TYPE_LABELS.items():
        for label in labels:
            score=fuzz.partial_ratio(label,snippet)/100.0
            if score>best_score: best_score=score; best_type=dtype
    return best_type,round(best_score,2)

def _validate_date(date_str):
    if not date_str: return date_str,False,"No date"
    parts=re.split(r'[/\-\.]',date_str.strip())
    if len(parts)==3:
        try:
            d,m=int(parts[0]),int(parts[1])
            if d>31: return date_str,False,f"Invalid day {d}"
            if m>12:
                if d<=12:
                    fixed=f"{parts[1]}/{parts[0]}/{parts[2]}"
                    return fixed,True,f"Day/month swapped → {fixed}"
                return date_str,False,f"Invalid month {m}"
        except ValueError: pass
    parsed=dateparser.parse(date_str,settings={"PREFER_DAY_OF_MONTH":"first","DATE_ORDER":"DMY","RETURN_AS_TIMEZONE_AWARE":False})
    if not parsed: return date_str,False,f"Cannot parse '{date_str}'"
    if parsed.year>datetime.now().year+1: return date_str,False,"Future date"
    return parsed.strftime("%d/%m/%Y"),True,""

def _spacy_extract(text,nlp):
    doc=nlp(text[:3000]); ents={"DATE":[],"MONEY":[],"ORG":[],"LOC":[],"PER":[]}
    for ent in doc.ents:
        if ent.label_ in ents: ents[ent.label_].append(ent.text.strip())
    return ents

def nlp_enrich(regex_info,text,header_text,nlp):
    enriched=dict(regex_info); confidence={}; warnings=[]
    nlp_type,type_conf=_fuzzy_doc_type(text)
    regex_type=regex_info.get("type","Document")
    if regex_type=="Document" and nlp_type!="Document": enriched["type"]=nlp_type; confidence["type"]=type_conf
    elif nlp_type==regex_type: confidence["type"]=max(type_conf,0.90)
    else:
        confidence["type"]=type_conf
        if type_conf>0.80 and nlp_type!="Document": enriched["type"]=nlp_type
    raw_date=regex_info.get("date","")
    if not raw_date:
        ents=_spacy_extract(text,nlp)
        for ed in ents.get("DATE",[]):
            if re.search(r'\d{4}|\d{1,2}[/\-\.]\d{1,2}',ed): raw_date=ed; break
    if raw_date:
        normed,is_valid,warn_msg=_validate_date(raw_date)
        if is_valid:
            enriched["date"]=normed; confidence["date"]=0.92 if normed!=raw_date else 0.95
            if normed!=raw_date: warnings.append(f"Date corrected: '{raw_date}' → '{normed}'")
        else: confidence["date"]=0.30; warnings.append(f"Date: {warn_msg}"); enriched["date"]=raw_date
    else: confidence["date"]=0.0
    for field in("total_ht","tva","total_ttc","total_brut_ht","transport","timbre_fiscal"):
        confidence[field]=0.90 if regex_info.get(field) is not None else 0.0
    numero=enriched.get("numero","")
    if numero:
        if re.match(r'^(BCN|BCM|FAC|PRO|CMD|INV)[\-/]\w{2}[\-/]\d{4}$',numero,re.I): confidence["numero"]=0.97
        elif re.match(r'^[A-Z]{2,8}-[A-Z]{2,8}-\d{4,12}$',numero): confidence["numero"]=0.95
        elif re.match(r'^\d{3,6}/\d{4}$',numero): confidence["numero"]=0.90
        else: confidence["numero"]=0.70
    else: confidence["numero"]=0.0
    for mf_key in("supplier_mf","client_mf","matricule_fiscal"):
        mf=enriched.get(mf_key,"")
        if mf:
            if re.match(r'^\d{6,8}[A-Z]/[A-Z]/[A-Z]/\d{3}$',mf): confidence[mf_key]=0.98
            else: confidence[mf_key]=0.55; warnings.append(f"{mf_key} unusual: '{mf}'")
        else: confidence[mf_key]=0.0
    tel=enriched.get("tel","")
    if tel:
        digs=re.sub(r'\D','',tel)
        confidence["tel"]=0.95 if len(digs)==8 else 0.80 if len(digs) in(10,11) else 0.50
    else: confidence["tel"]=0.0
    if enriched.get("email"): confidence["email"]=0.97 if re.match(r'^[\w\.\-]+@[\w\.\-]+\.\w{2,6}$',enriched["email"]) else 0.50
    if not enriched.get("adresse"):
        ents=_spacy_extract(text,nlp); locs=ents.get("LOC",[])
        if locs: enriched["adresse"]=" — ".join(locs[:2]); confidence["adresse"]=0.60
    else: confidence["adresse"]=0.75
    for key in enriched:
        if key not in confidence: confidence[key]=0.70
    return enriched,confidence,warnings

# ═══════════════════════════════════════════════════════════════
# PDF → IMAGE
# ═══════════════════════════════════════════════════════════════
def pdf_page_to_image(pdf_path,page_index,dpi=200):
    doc=fitz.open(pdf_path); page=doc[page_index]; mat=fitz.Matrix(dpi/72,dpi/72); pix=page.get_pixmap(matrix=mat,alpha=False)
    img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
    return cv2.cvtColor(img,cv2.COLOR_RGB2BGR if pix.n==3 else cv2.COLOR_RGBA2BGR)

# ═══════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════
def render_info_grid(fields,confidence,show_conf):
    html="<div class='info-grid'>"
    for label,key,value in fields:
        conf=confidence.get(key); is_empty=str(value) in("—","","None")
        badge=(_conf_badge_html(conf) if show_conf and conf is not None and not is_empty else "")
        val_cls=("empty-val" if is_empty else "warn-val" if(conf is not None and conf<0.55) else "")
        disp="—" if is_empty else str(value)
        html+=(f"<div class='metric-card'>{badge}<div class='metric-label'>{label}</div><div class='metric-value {val_cls}'>{disp}</div></div>")
    html+="</div>"
    st.markdown(html,unsafe_allow_html=True)

def render_product_table(items,detected_schema=None,doc_type=""):
    if not items: return
    present_keys=set()
    for item in items:
        for k,v in item.items():
            if str(v).strip() not in("","None","—","nan"): present_keys.add(k)
    if detected_schema:
        allowed={_CANON_TO_KEY.get(c,c) for c in detected_schema}|{"code","designation"}
    else:
        allowed=present_keys|{"code","designation"}
    schema=[k for k in _OUTPUT_ORDER if k in allowed and k in present_keys]
    if "code" not in schema: schema.insert(0,"code")
    if "designation" not in schema: schema.append("designation")
    tbl=("<div class='table-container'><table><thead><tr><th style='color:#555;width:32px'>#</th>")
    for k in schema: tbl+=f"<th>{_COL_LABELS.get(k,k)}</th>"
    tbl+="</tr></thead><tbody>"
    for i,item in enumerate(items,1):
        tbl+=f"<tr><td style='color:#555'>{i}</td>"
        for k in schema:
            val=item.get(k,"")
            if isinstance(val,float): val=f"{val:.0f}" if val==int(val) else f"{val:.3f}"
            if not str(val).strip() or str(val) in("None","nan"): val="—"
            style=""
            if k=="code": style=" style='color:#7ee8a2'"
            elif k=="code_article": style=" style='color:#7ec8e8'"
            elif k=="quantite": style=" style='text-align:right;color:#e8c87e'"
            elif k in("prix_unitaire","montant","nb_crt","u_crt"): style=" style='text-align:right'"
            tbl+=f"<td{style}>{val}</td>"
        tbl+="</tr>"
    tbl+="</tbody></table></div>"
    st.markdown(tbl,unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ⚙️ Options"); st.markdown("---")
    st.markdown("**Preprocessing**")
    use_fix_rotation=st.checkbox("Fix Rotation",value=True)
    use_erase_color=st.checkbox("Erase Colored Ink",value=True)
    use_remove_lines=st.checkbox("Remove Borders",value=True)
    use_keep_mask=st.checkbox("Blob Filter (CV)",value=True)
    st.markdown("---"); st.markdown("**OCR**")
    dpi_choice=st.radio("DPI",options=[150,200,300],index=1,help="200 ≈ 40% faster than 300")
    split_zones=st.checkbox("Split Header / Body OCR",value=True)
    show_raw=st.checkbox("Show Raw OCR Text",value=False)
    st.markdown("---"); st.markdown("**NLP**")
    use_nlp=st.checkbox("Enable NLP Enrichment",value=True)
    show_conf=st.checkbox("Show Confidence Scores",value=False,help="🟢≥80% reliable · 🟡55-79% · 🔴<55% likely wrong")
    show_warnings=st.checkbox("Show Validation Warnings",value=True)
    show_trace=st.checkbox("Show Extraction Trace",value=False)
    st.markdown("---"); st.markdown("**Output**")
    show_tables=st.checkbox("Show pdfplumber Tables",value=True)
    show_products=st.checkbox("Show Product Lines",value=True)
    show_json=st.checkbox("Show Clean JSON Preview",value=False)

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
st.markdown("# 🔬 Invoice OCR Pipeline")
st.markdown("*Preprocessing → OCR → Regex → 🧠 NLP → Structured output*")
st.markdown("---")

nlp_model,nlp_model_name=load_nlp()
with st.sidebar:
    st.markdown("---"); st.markdown("**NLP Model**")
    mc="#7ee8a2" if nlp_model_name!="blank_fr" else "#e8c87e"
    st.markdown(f"<span style='font-family:JetBrains Mono;font-size:11px;color:{mc}'>{'✓' if nlp_model_name!='blank_fr' else '⚠'} {nlp_model_name}</span>",unsafe_allow_html=True)
    if nlp_model_name=="blank_fr": st.caption("Install: `python -m spacy download fr_core_news_sm`")

uploaded=st.file_uploader("Drop a PDF or image file",type=["pdf","png","jpg","jpeg"],label_visibility="collapsed")
run_btn=st.button("▶  Run Pipeline",use_container_width=True)

if not uploaded:
    st.markdown("""<div style='text-align:center;padding:60px 0;color:#444;'><div style='font-size:48px;margin-bottom:16px'>📄</div><div style='font-size:14px'>Upload a PDF or image to begin</div><div style='font-size:11px;color:#333;margin-top:8px'>Supports: Bon de Commande · Proforma · Facture · Statistiques</div></div>""",unsafe_allow_html=True)

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
        is_native=detect_pdf_native(tmp_path); doc_fitz=fitz.open(tmp_path); total_pages=len(doc_fitz)
        _log_set("detect","done",f"{'Native' if is_native else 'Scanned'} PDF — {total_pages} page(s)"); _log_render(_log_ph)
    else:
        is_native=False; total_pages=1; _log_set("detect","done","Image file — 1 page"); _log_render(_log_ph)
    if is_pdf:
        c1,c2=st.columns([2,1])
        with c1:
            col="#7ee8a2" if is_native else "#e8c87e"
            st.markdown(f"<div class='metric-card'><div class='metric-label'>PDF type</div><div class='metric-value' style='color:{col}'>{'📄 Native (digital)' if is_native else '📷 Scanned'}</div></div>",unsafe_allow_html=True)
        with c2:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>Pages</div><div class='metric-value'>{total_pages}</div></div>",unsafe_allow_html=True)
    st.markdown("---")
    all_header_texts=[]; all_body_texts=[]; all_full_texts=[]; all_clean_imgs=[]; all_orig_imgs=[]; all_header_clean_imgs=[]; all_header_layout_lines=[]; all_product_lines=[]; seen_codes=set()
    prog=st.progress(0,text="Processing pages…")
    for page_i in range(total_pages):
        _log_set("preprocess","running",f"page {page_i+1}/{total_pages}  DPI={dpi_choice}"); _log_render(_log_ph); _pp_t0=_time.time()
        if is_pdf: img_bgr=pdf_page_to_image(tmp_path,page_i,dpi=dpi_choice)
        else:
            fb=np.frombuffer(uploaded.getvalue(),dtype=np.uint8); img_bgr=cv2.imdecode(fb,1)
        all_orig_imgs.append(cv2.cvtColor(img_bgr,cv2.COLOR_BGR2RGB))
        work=img_bgr.copy()
        if use_fix_rotation: work=fix_rotation(work)
        if use_erase_color: work=erase_colored_ink(work)
        gray=cv2.cvtColor(work,cv2.COLOR_BGR2GRAY); binary=binarize(gray)
        header_binary=binary.copy()
        header_clean=enhance_kept_text(header_binary,build_keep_mask(header_binary)) if use_keep_mask else header_binary
        if use_remove_lines: binary=remove_long_lines(binary)
        clean=enhance_kept_text(binary,build_keep_mask(binary)) if use_keep_mask else binary
        all_clean_imgs.append(clean); all_header_clean_imgs.append(header_clean)
        _log_set("preprocess","done",f"{total_pages} page(s) cleaned",t0=_pp_t0); _log_render(_log_ph)
        _log_set("ocr","running",f"page {page_i+1}/{total_pages}  split={split_zones}"); _log_render(_log_ph); _ocr_t0=_time.time()
        if split_zones:
            h_text_soft=clean_ocr_text(ocr_header_zone(header_clean)); h_text_std=clean_ocr_text(ocr_header_zone(clean))
            h_text=clean_ocr_text((h_text_soft+"\n"+h_text_std).strip())
            if page_i==0: all_header_layout_lines=ocr_header_layout_lines(header_clean)
            b_text=clean_ocr_text(ocr_body_zone(clean)); f_text=clean_ocr_text((h_text+"\n"+b_text).strip())
        else:
            f_text=clean_ocr_text(ocr_full_page(clean)); h_text=b_text=f_text
        all_header_texts.append(h_text); all_body_texts.append(b_text); all_full_texts.append(f_text)
        _log_set("ocr","done",f"{total_pages} page(s)  {len(f_text.split())} words",t0=_ocr_t0); _log_render(_log_ph)
        _log_set("products","running",f"page {page_i+1}/{total_pages}"); _log_render(_log_ph)
        if show_products:
            page_doc_type=detect_doc_type((h_text or "")+"\n"+(b_text or ""))
            page_items,_=extract_product_lines(b_text,doc_type=page_doc_type)
            for item in page_items:
                code=item.get("code","")
                if code and code not in seen_codes: seen_codes.add(code); all_product_lines.append(item)
                elif not code: all_product_lines.append(item)
        _log_set("products","done",f"{len(all_product_lines)} item(s)"); _log_render(_log_ph)
        prog.progress((page_i+1)/total_pages,text=f"Page {page_i+1}/{total_pages}…")
    prog.empty()
    combined_full="\n\n".join(all_full_texts); combined_header="\n\n".join(all_header_texts)
    predicted_doc_type=detect_doc_type(combined_full)
    plumber_tables=[]; table_extraction_audit={"detected_headers":[],"column_map":{},"row_rejections":[],"structured_item_count":0,"detected_schema":set(),"strategy":"fallback_regex_only"}
    if is_pdf and is_native and show_tables:
        _log_set("pdfplumber","running","reading vector tables…"); _log_render(_log_ph); _pl_t0=_time.time()
        with st.spinner("Extracting tables…"): plumber_tables=extract_tables_pdfplumber(tmp_path)
        _log_set("pdfplumber","done",f"{len(plumber_tables)} table(s)",t0=_pl_t0); _log_render(_log_ph)
    else:
        reason=("scanned PDF" if(is_pdf and not is_native) else "image file" if not is_pdf else "disabled")
        _log_set("pdfplumber","skip",reason); _log_render(_log_ph)
    if plumber_tables:
        structured_items,table_extraction_audit=extract_line_items_from_tables(plumber_tables,doc_type=predicted_doc_type)
        if structured_items:
            all_product_lines=merge_line_items(structured_items,all_product_lines)
            table_extraction_audit["strategy"]="structured_primary"
    _log_set("regex","running",f"{len(combined_full.split())} words"); _log_render(_log_ph); _rx_t0=_time.time()
    regex_info,extraction_trace=extract_info(combined_full,combined_header,all_header_layout_lines)
    regex_info=_extract_totals(all_full_texts,regex_info,predicted_doc_type)
    _log_set("regex","done",f"type={regex_info.get('type','?')}  date={regex_info.get('date','—')}  HT={regex_info.get('total_ht','—')}  TTC={regex_info.get('total_ttc','—')}",t0=_rx_t0); _log_render(_log_ph)
    confidence={}; warnings_nlp=[]; extracted_info=regex_info
    if use_nlp:
        _log_set("nlp","running",f"model={nlp_model_name}  NER·fuzzy·date…"); _log_render(_log_ph); _nlp_t0=_time.time()
        extracted_info,confidence,warnings_nlp=nlp_enrich(regex_info,combined_full,combined_header,nlp_model)
        filled=sum(1 for k in extracted_info if k not in regex_info); fixed=len([w for w in warnings_nlp if "corrected" in w])
        status="warn" if warnings_nlp else "done"
        _log_set("nlp",status,f"+{filled} filled  {fixed} corrected  {len(warnings_nlp)} warn",t0=_nlp_t0); _log_render(_log_ph)
    else: _log_set("nlp","skip","disabled"); _log_render(_log_ph)
    detected_schema=table_extraction_audit.get("detected_schema",set())
    all_product_lines=normalize_line_items_for_json(all_product_lines,detected_schema=detected_schema if detected_schema else None)
    llm_validation={"llm_status":"client_unavailable"}; promotion_decisions={"fields":{},"line_items":[],"llm_status":"client_unavailable"}
    _log_set("done","done",f"{total_pages} page(s) · {len(all_product_lines)} items · {len(plumber_tables)} tables · {len(warnings_nlp)} NLP warn"); _log_render(_log_ph)

    st.markdown("## 🖼️ Pages — Original & Cleaned")
    for page_i,(orig,clean) in enumerate(zip(all_orig_imgs,all_clean_imgs)):
        label=f"Page {page_i+1}/{total_pages}" if total_pages>1 else "Document"
        st.markdown(f"<div class='page-label'>{label}</div>",unsafe_allow_html=True)
        c1,c2=st.columns(2)
        with c1:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#888;text-align:center;margin-bottom:4px'>📷 Original</div>",unsafe_allow_html=True)
            st.image(orig,use_container_width=True)
        with c2:
            st.markdown("<div style='font-family:JetBrains Mono;font-size:11px;color:#7ee8a2;text-align:center;margin-bottom:4px'>✨ After Cleaning</div>",unsafe_allow_html=True)
            st.image(clean,use_container_width=True)
        if page_i<len(all_clean_imgs)-1: st.markdown("<hr style='border-color:#1e2130;margin:12px 0;'>",unsafe_allow_html=True)
    st.markdown("---")

    document_payload=build_document_payload(extracted_info)
    dtype=document_payload.get("type","Document")
    tag_class={"Bon de Commande":"tag-bc","Proforma":"tag-proforma","Facture":"tag-facture"}.get(dtype,"tag-stat")
    st.markdown(f"<span class='{tag_class}'>{dtype}</span>",unsafe_allow_html=True)
    st.markdown("## 📋 Extracted Information")
    if show_conf:
        st.markdown("<div class='conf-hint'>🟢 ≥80% reliable &nbsp;·&nbsp; 🟡 55–79% double-check &nbsp;·&nbsp; 🔴 &lt;55% likely wrong</div>",unsafe_allow_html=True)
    if show_warnings and warnings_nlp:
        ih="".join(f"<li>{w}</li>" for w in warnings_nlp)
        st.markdown(f"<div class='warn-box'>⚠ <strong>Validation warnings</strong><ul>{ih}</ul></div>",unsafe_allow_html=True)

    fields_to_show=[("Type de document","type",document_payload.get("type","—")),("Document N°","numero",document_payload.get("numero","—")),("Date","date",document_payload.get("date","—")),("Fournisseur","fournisseur_nom",document_payload.get("fournisseur_nom","—")),("Supplier MF","supplier_mf",document_payload.get("supplier_mf","—")),("Client MF","client_mf",document_payload.get("client_mf","—")),("Téléphone","tel",document_payload.get("tel","—")),("Fax","fax",document_payload.get("fax","—")),("Email","email",document_payload.get("email","—")),("RC","rc",document_payload.get("rc","—")),("Total Brut HT","total_brut_ht",document_payload.get("total_brut_ht","—")),("Remise %","remise_pct",document_payload.get("remise_pct","—")),("Total Net HT","total_ht",document_payload.get("total_ht","—")),("TVA","tva",document_payload.get("tva","—")),("Transport","transport",document_payload.get("transport","—")),("Timbre Fiscal","timbre_fiscal",document_payload.get("timbre_fiscal","—")),("Total TTC","total_ttc",document_payload.get("total_ttc","—"))]
    render_info_grid(fields_to_show,confidence,show_conf)

    if document_payload.get("adresse"):
        conf_a=confidence.get("adresse"); badge_a=_conf_badge_html(conf_a) if(show_conf and conf_a is not None) else ""
        st.markdown(f"<div class='metric-card addr-card'>{badge_a}<div class='metric-label'>Adresse</div><div class='metric-value addr-val'>{document_payload['adresse']}</div></div>",unsafe_allow_html=True)

    if show_products and all_product_lines:
        st.markdown(f"## 📦 Product Lines ({len(all_product_lines)} items)")
        render_product_table(all_product_lines,detected_schema=detected_schema,doc_type=dtype)
    elif show_products: st.info("No product lines detected. Enable 'Show Raw OCR Text' to debug.")

    if plumber_tables:
        st.markdown(f"## 🗃️ pdfplumber Tables ({len(plumber_tables)} found)")
        for t_idx,table in enumerate(plumber_tables):
            if not table: continue
            st.markdown(f"**Table {t_idx+1}**")
            tbl="<div class='table-container'><table><thead><tr>"
            for h in table[0]: tbl+=f"<th>{str(h).replace('&','&amp;').replace('<','&lt;')}</th>"
            tbl+="</tr></thead><tbody>"
            for row in table[1:]:
                if any(str(c).strip() for c in row):
                    tbl+="<tr>"
                    for cell in row: tbl+=f"<td>{str(cell).replace('&','&amp;').replace('<','&lt;')}</td>"
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
                        st.markdown("**Header zone**"); st.markdown(f"<div class='raw-text'>{all_header_texts[page_i]}</div>",unsafe_allow_html=True)
                    with c2:
                        st.markdown("**Body zone**"); st.markdown(f"<div class='raw-text'>{all_body_texts[page_i]}</div>",unsafe_allow_html=True)
                else:
                    st.markdown(f"<div class='raw-text'>{all_full_texts[page_i]}</div>",unsafe_allow_html=True)

    clean_payload=build_clean_json(document_payload,all_product_lines)
    audit_payload=build_audit_json(confidence,warnings_nlp,extraction_trace,table_extraction_audit,{},llm_validation,promotion_decisions,nlp_model_name)

    if show_json: st.markdown("## 🗂️ Clean JSON Preview"); st.json(clean_payload)
    if show_trace: st.markdown("## 🧭 Extraction Trace"); st.json(extraction_trace)

    st.markdown("---")
    c1,c2,c3=st.columns(3)
    with c1:
        st.download_button("⬇ Download Clean JSON",data=json.dumps(clean_payload,ensure_ascii=False,indent=2),file_name=f"{Path(uploaded.name).stem}_data.json",mime="application/json",use_container_width=True,help="Document info + line items only")
    with c2:
        st.download_button("⬇ Download Audit JSON",data=json.dumps(audit_payload,ensure_ascii=False,indent=2,default=str),file_name=f"{Path(uploaded.name).stem}_audit.json",mime="application/json",use_container_width=True,help="Confidence, trace, rejected candidates")
    with c3:
        st.download_button("⬇ Download OCR Text",data=combined_full,file_name=f"{Path(uploaded.name).stem}_ocr.txt",mime="text/plain",use_container_width=True)

    try: os.unlink(tmp_path)
    except: pass