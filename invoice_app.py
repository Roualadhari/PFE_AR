# invoice_app.py — Preprocessing Visualizer + Full Pipeline UI
# Run: streamlit run invoice_app.py

import streamlit as st
import numpy as np
import cv2
import tempfile
import json
import os
import fitz  # PyMuPDF

from invoice_extractor import (
    pdf_page_to_image,
    preprocess_scanned_page,
    preprocess_scanned_page_steps,
    run_ocr,
    clean_extracted_text,
    extract_invoice,
)

# ─────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Invoice Preprocessing Visualizer",
    page_icon="🧾",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    body, .stApp { background: #0f1117; }
    .step-label {
        background: linear-gradient(135deg, #1e3a5f, #0d2137);
        border: 1px solid #1e6fff44;
        border-radius: 10px;
        padding: 8px 14px;
        font-size: 13px;
        font-weight: 600;
        color: #7ec8ff;
        text-align: center;
        margin-bottom: 6px;
        letter-spacing: 0.04em;
    }
    .step-arrow {
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 22px;
        color: #3a7bd5;
        padding: 0 2px;
    }
    .metric-box {
        background: #161b2e;
        border-radius: 10px;
        padding: 14px 20px;
        border: 1px solid #243460;
        text-align: center;
    }
    .metric-val {
        font-size: 2em;
        font-weight: 700;
        color: #4fc3f7;
    }
    .metric-lbl {
        font-size: 0.8em;
        color: #8899bb;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .section-title {
        font-size: 1.15em;
        font-weight: 700;
        color: #c5d8f6;
        border-left: 4px solid #3a7bd5;
        padding-left: 12px;
        margin: 22px 0 12px 0;
    }
    .stImage > img { border-radius: 8px; border: 1px solid #1f3060; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def bgr_to_rgb(img: np.ndarray) -> np.ndarray:
    """Convert BGR (OpenCV) to RGB (Streamlit/PIL)."""
    if len(img.shape) == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def load_page_from_pdf(tmp_path: str, page_idx: int, dpi: int = 200) -> np.ndarray:
    """Render a single PDF page to a BGR numpy array."""
    doc  = fitz.open(tmp_path)
    page = doc[page_idx]
    mat  = fitz.Matrix(dpi / 72, dpi / 72)
    pix  = page.get_pixmap(matrix=mat, alpha=False)
    img  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    elif pix.n == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    return img


def page_count(tmp_path: str) -> int:
    """Return page count of a PDF."""
    doc = fitz.open(tmp_path)
    n   = len(doc)
    doc.close()
    return n


STEP_DESCRIPTIONS = {
    "Source":       "📄 Original scanned image loaded from the PDF or uploaded file.",
    "Rotated":      "🔄 Tesseract OSD + OpenCV `minAreaRect` used to detect and correct page rotation.",
    "Color Removed":"🎨 Colored ink (stamps, annotations) detected via HSV thresholds and replaced with white. Dark ink is preserved.",
    "Binarized":    "⬛ Adaptive Gaussian threshold converts the grayscale image to pure black-and-white for OCR.",
    "Lines Removed":"📏 Morphological opening removes horizontal and vertical table borders without touching adjacent letters.",
    "Final Cleaned":"✅ Connected-component analysis keeps only text-like blobs. Noise, stamps, and large solid regions are removed.",
}

# ─────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<h1 style='text-align:center; font-size:2em; font-weight:800;
   background: linear-gradient(90deg,#3a7bd5,#7ec8ff);
   -webkit-background-clip:text; -webkit-text-fill-color:transparent;
   margin-bottom:4px;'>
  🧾 Invoice Preprocessing Visualizer
</h1>
<p style='text-align:center; color:#667; font-size:0.95em; margin-top:0;'>
  Upload a PDF or image — see every pipeline step and the final OCR + JSON result.
</p>
""", unsafe_allow_html=True)

st.divider()

# ─────────────────────────────────────────────────────────────────
# SIDEBAR — UPLOAD + OPTIONS
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Controls")
    uploaded = st.file_uploader(
        "Upload Invoice",
        type=["pdf", "png", "jpg", "jpeg", "tiff", "bmp"],
        help="Supports scanned PDFs and direct image files."
    )

    st.markdown("---")
    run_full  = st.checkbox("Run full extraction (JSON)", value=False,
                            help="Runs the complete pipeline and shows the structured JSON result.")
    show_ocr  = st.checkbox("Show OCR text panel", value=True)
    dpi_val   = st.slider("Preview DPI (PDF render)", 100, 300, 200, step=50,
                          help="Higher DPI = better quality but slower.")

    st.markdown("---")
    st.markdown("""
    <div style='color:#556; font-size:0.8em;'>
    Pipeline steps:<br>
    1 · Source → 2 · Rotate → 3 · Color Remove<br>
    4 · Binarize → 5 · Remove Lines → 6 · Clean
    </div>
    """, unsafe_allow_html=True)


if not uploaded:
    st.markdown("""
    <div style='text-align:center; padding:80px 0; color:#445;'>
      <div style='font-size:4em;'>📂</div>
      <div style='font-size:1.1em; margin-top:12px;'>Upload a PDF or image using the sidebar to begin.</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ─────────────────────────────────────────────────────────────────
# SAVE UPLOADED FILE TO TEMP
# ─────────────────────────────────────────────────────────────────
suffix = "." + uploaded.name.rsplit(".", 1)[-1].lower()
with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
    tmp.write(uploaded.read())
    tmp_path = tmp.name

is_pdf  = suffix == ".pdf"
is_img  = suffix in (".png", ".jpg", ".jpeg", ".tiff", ".bmp")

# ─────────────────────────────────────────────────────────────────
# PAGE SELECTOR (PDF only)
# ─────────────────────────────────────────────────────────────────
page_idx = 0
if is_pdf:
    n_pages = page_count(tmp_path)
    if n_pages > 1:
        page_idx = st.slider(
            f"Page  (1 – {n_pages})",
            min_value=1, max_value=n_pages, value=1
        ) - 1

# ─────────────────────────────────────────────────────────────────
# LOAD THE IMAGE
# ─────────────────────────────────────────────────────────────────
with st.spinner("Loading image…"):
    if is_pdf:
        img_bgr = load_page_from_pdf(tmp_path, page_idx, dpi=dpi_val)
    else:
        raw = np.frombuffer(open(tmp_path, "rb").read(), np.uint8)
        img_bgr = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if img_bgr is None:
            st.error("Could not read the uploaded image file.")
            st.stop()

h, w = img_bgr.shape[:2]

# ─────────────────────────────────────────────────────────────────
# QUICK METRICS
# ─────────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.markdown(f"""<div class='metric-box'><div class='metric-val'>{w}×{h}</div>
    <div class='metric-lbl'>Image Size (px)</div></div>""", unsafe_allow_html=True)
with m2:
    pg_label = f"{page_idx+1}/{page_count(tmp_path)}" if is_pdf else "—"
    st.markdown(f"""<div class='metric-box'><div class='metric-val'>{pg_label}</div>
    <div class='metric-lbl'>Page</div></div>""", unsafe_allow_html=True)
with m3:
    ftype = "PDF" if is_pdf else suffix[1:].upper()
    st.markdown(f"""<div class='metric-box'><div class='metric-val'>{ftype}</div>
    <div class='metric-lbl'>File Type</div></div>""", unsafe_allow_html=True)
with m4:
    fsize = round(os.path.getsize(tmp_path) / 1024, 1)
    st.markdown(f"""<div class='metric-box'><div class='metric-val'>{fsize} KB</div>
    <div class='metric-lbl'>File Size</div></div>""", unsafe_allow_html=True)

st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
# RUN PIPELINE STEPS
# ─────────────────────────────────────────────────────────────────
with st.spinner("Running preprocessing pipeline…"):
    steps = preprocess_scanned_page_steps(img_bgr)

# ─────────────────────────────────────────────────────────────────
# STEP VISUALIZER — GRID
# ─────────────────────────────────────────────────────────────────
st.markdown("<div class='section-title'>📷 Preprocessing Pipeline</div>", unsafe_allow_html=True)

step_names = list(steps.keys())
n_steps    = len(step_names)
cols       = st.columns(n_steps)

for i, name in enumerate(step_names):
    with cols[i]:
        st.markdown(f"<div class='step-label'>Step {i+1} · {name}</div>", unsafe_allow_html=True)
        step_img = steps[name]
        st.image(bgr_to_rgb(step_img), use_container_width=True)
        with st.expander("ℹ️ What this step does"):
            st.markdown(STEP_DESCRIPTIONS.get(name, ""))

# ─────────────────────────────────────────────────────────────────
# BEFORE / AFTER COMPARE
# ─────────────────────────────────────────────────────────────────
st.markdown("<div class='section-title'>🔍 Before / After Comparison</div>", unsafe_allow_html=True)
left_name  = st.selectbox("Left  image",  step_names, index=0, key="cmp_left")
right_name = st.selectbox("Right image", step_names, index=len(step_names)-1, key="cmp_right")

c1, c2 = st.columns(2)
with c1:
    st.markdown(f"<div class='step-label'>{left_name}</div>", unsafe_allow_html=True)
    st.image(bgr_to_rgb(steps[left_name]), use_container_width=True)
with c2:
    st.markdown(f"<div class='step-label'>{right_name}</div>", unsafe_allow_html=True)
    st.image(bgr_to_rgb(steps[right_name]), use_container_width=True)

# ─────────────────────────────────────────────────────────────────
# OCR TEXT
# ─────────────────────────────────────────────────────────────────
if show_ocr:
    st.markdown("<div class='section-title'>✨ OCR Text — All Pages</div>", unsafe_allow_html=True)

    if is_pdf:
        n_p = page_count(tmp_path)
        st.info(f"Processing all {n_p} page(s) — the visual pipeline above shows only the selected page.")
    else:
        n_p = 1

    all_raw   = []
    all_clean = []

    with st.spinner("Running OCR on all pages…"):
        for pg in range(n_p):
            if is_pdf:
                pg_img = load_page_from_pdf(tmp_path, pg, dpi=dpi_val)
            else:
                pg_img = img_bgr.copy()

            pg_clean_img = preprocess_scanned_page(pg_img)
            if len(pg_clean_img.shape) == 3:
                pg_gray = cv2.cvtColor(pg_clean_img, cv2.COLOR_BGR2GRAY)
            else:
                pg_gray = pg_clean_img

            raw   = run_ocr(pg_gray)
            clean = clean_extracted_text(raw)
            all_raw.append(raw)
            all_clean.append(clean)

    combined_raw   = "\n\n".join(all_raw)
    combined_clean = "\n\n".join(all_clean)

    tab_raw, tab_clean, tab_pages = st.tabs(["Raw OCR (all pages)", "Cleaned Text (all pages)", "Per-page view"])

    with tab_raw:
        st.text_area("Raw Tesseract output", combined_raw, height=300, key="raw_ocr")

    with tab_clean:
        st.text_area("After clean_extracted_text()", combined_clean, height=300, key="clean_ocr")

    with tab_pages:
        for pg, (raw_pg, clean_pg) in enumerate(zip(all_raw, all_clean), start=1):
            with st.expander(f"📄 Page {pg}  —  {len(clean_pg.split())} words", expanded=(pg == 1)):
                c_r, c_c = st.columns(2)
                with c_r:
                    st.caption("Raw OCR")
                    st.text(raw_pg[:1200] + (" …" if len(raw_pg) > 1200 else ""))
                with c_c:
                    st.caption("Cleaned")
                    st.text(clean_pg[:1200] + (" …" if len(clean_pg) > 1200 else ""))

    # Word-count delta
    raw_words   = len(combined_raw.split())
    clean_words = len(combined_clean.split())
    diff        = raw_words - clean_words
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Raw words",   raw_words)
    col_b.metric("Clean words", clean_words)
    col_c.metric("Removed",     diff, delta_color="inverse")

# ─────────────────────────────────────────────────────────────────
# FULL JSON EXTRACTION
# ─────────────────────────────────────────────────────────────────
if run_full:
    st.markdown("<div class='section-title'>📦 Full Structured Extraction (JSON)</div>",
                unsafe_allow_html=True)
    with st.spinner("Running full invoice extraction pipeline…"):
        try:
            result = extract_invoice(tmp_path, save_debug_images=False)

            # ── Per-page body summary ─────────────────────────────
            pages = result.get("pages", [])
            st.markdown(f"**{len(pages)} page(s) extracted — {result.get('pdf_type', '').upper()}**")
            for pg in pages:
                pnum  = pg.get("page_number", "?")
                body  = pg.get("structure", {}).get("body", [])
                hdr   = pg.get("structure", {}).get("header", [])
                ftr   = pg.get("structure", {}).get("footer", [])
                label = f"Page {pnum}  —  {len(body)} body lines, {len(hdr)} header, {len(ftr)} footer"
                with st.expander(label, expanded=(pnum == 1)):
                    if body:
                        st.markdown("**Body lines:**")
                        for i, line in enumerate(body):
                            st.markdown(f"`{i+1:02d}`  {line}")
                    if ftr:
                        st.markdown("**Footer:**")
                        for line in ftr:
                            st.markdown(f"_{line}_")

            # ── Raw JSON ──────────────────────────────────────────
            with st.expander("Raw JSON", expanded=False):
                st.json(result, expanded=1)

            # Download button
            json_str = json.dumps(result, ensure_ascii=False, indent=2)
            st.download_button(
                label="⬇️  Download JSON",
                data=json_str.encode("utf-8"),
                file_name=f"result_{uploaded.name.rsplit('.', 1)[0]}.json",
                mime="application/json",
            )
        except Exception as e:
            st.error(f"Extraction failed: {e}")
            import traceback
            st.code(traceback.format_exc())

# ─────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────
try:
    os.unlink(tmp_path)
except OSError:
    pass