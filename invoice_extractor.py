# invoice_extractor.py — FIXED VERSION + IMAGE SUPPORT
# Changes from original:
#   FIX 1: remove_long_lines — larger kernels (35→80px) + no dilation on lines_mask
#          so table borders are removed without eating adjacent letters
#   FIX 2: clean_extracted_text — more OCR corrections:
#          l/I between digits → 1, stray | and ° cleaned,
#          (cid:XX) artifacts removed, space-separated letters collapsed
#   FIX 3: extract_native_pdf — post-process pdfplumber output to fix
#          spaced characters "O M N I" and (cid:10) artifacts
#   NEW: Added extract_image() and updated extract_invoice() to support direct image files.

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

import fitz
import pdfplumber
import cv2
import numpy as np
import json
import os
import re
from pathlib import Path


# ════════════════════════════════════════════════════════════════════════════
# PART 1 — PDF TYPE DETECTION
# ════════════════════════════════════════════════════════════════════════════

def detect_pdf_type(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        total_chars = sum(
            len((page.extract_text() or "").strip())
            for page in pdf.pages
        )
    return "native" if total_chars > 100 else "scanned"


# ════════════════════════════════════════════════════════════════════════════
# PART 2 — IMAGE PREPROCESSING
# ════════════════════════════════════════════════════════════════════════════

def pdf_page_to_image(pdf_path: str, page_index: int, dpi: int = 300) -> np.ndarray:
    doc  = fitz.open(pdf_path)
    page = doc[page_index]
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


def fix_rotation(img_bgr: np.ndarray) -> np.ndarray:
    try:
        gray_temp = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        osd = pytesseract.image_to_osd(
            gray_temp,
            config="--psm 0 -c min_characters_to_try=5"
        )
        angle_match = re.search(r"Rotate: (\d+)", osd)
        conf_match  = re.search(r"Orientation confidence: ([\d\.]+)", osd)

        confidence = float(conf_match.group(1)) if conf_match else 0.0
        if angle_match and confidence >= 2.0:
            a = int(angle_match.group(1))
            if a == 90:
                img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            elif a == 180:
                img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_180)
            elif a == 270:
                img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    except Exception:
        pass

    gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    coords = np.column_stack(np.where(gray < 200))
    if len(coords) < 500:  
        return img_bgr

    angle = cv2.minAreaRect(coords)[-1]

    if angle < -45:
        angle = 90 + angle

    if abs(angle) < 0.3 or abs(angle) > 3.0:
        return img_bgr

    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(
        img_bgr, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )


def erase_colored_ink(img_bgr: np.ndarray) -> np.ndarray:
    hsv    = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    result = img_bgr.copy()

    # Raised saturation min from 25→50 and value min from 40→60
    # so lightly tinted but important ink is NOT erased
    color_mask = cv2.inRange(
        hsv,
        np.array([0,  50, 60]),
        np.array([180, 255, 255])
    )
    k          = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))  # smaller dilation
    color_mask = cv2.dilate(color_mask, k, iterations=1)

    # Only erase non-dark pixels — dark colored ink may be text, keep it
    dark_pixels                = (gray < 80)   # tighter threshold: only truly dark pixels
    fade_mask                  = (color_mask > 0) & (~dark_pixels)
    result[fade_mask]          = [230, 230, 230]
    # Dark pixels inside color zones → force black (text)
    dark_in_color              = (color_mask > 0) & dark_pixels
    result[dark_in_color]      = [0, 0, 0]
    return result


def binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=25,
        C=8
    )


def remove_long_lines(binary: np.ndarray) -> np.ndarray:
    inverted = cv2.bitwise_not(binary)

    h_k     = cv2.getStructuringElement(cv2.MORPH_RECT, (80, 1))
    v_k     = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 80))
    h_lines = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, h_k)
    v_lines = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, v_k)
    lines_mask = cv2.add(h_lines, v_lines)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        inverted, connectivity=8
    )
    text_protect = np.zeros_like(binary)
    for i in range(1, num_labels):
        bw_  = stats[i, cv2.CC_STAT_WIDTH]
        bh_  = stats[i, cv2.CC_STAT_HEIGHT]
        area = stats[i, cv2.CC_STAT_AREA]
        if 5 <= bw_ <= 120 and 5 <= bh_ <= 120 and 20 <= area <= 8000:
            text_protect[labels == i] = 255

    pk           = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    text_protect = cv2.dilate(text_protect, pk, iterations=1)
    safe_lines   = cv2.bitwise_and(lines_mask, cv2.bitwise_not(text_protect))
    inverted[safe_lines > 0] = 0
    return cv2.bitwise_not(inverted)


def stroke_cv(blob: np.ndarray) -> float:
    ek      = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    current = blob.copy()
    counts  = []
    for _ in range(15):
        current = cv2.erode(current, ek)
        n       = cv2.countNonZero(current)
        counts.append(n)
        if n == 0:
            break
    if len(counts) < 2:
        return 999.0
    arr  = np.array(counts, dtype=float)
    nz   = arr[arr > 0]
    if len(nz) == 0:
        return 999.0
    return float(np.std(nz) / (np.mean(nz) + 1e-5))


def build_keep_mask(binary: np.ndarray) -> np.ndarray:
    inverted     = cv2.bitwise_not(binary)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        inverted, connectivity=8
    )
    keep_mask = np.zeros_like(binary)

    for i in range(1, num_labels):
        bx_    = stats[i, cv2.CC_STAT_LEFT]
        by_    = stats[i, cv2.CC_STAT_TOP]
        bw_    = stats[i, cv2.CC_STAT_WIDTH]
        bh_    = stats[i, cv2.CC_STAT_HEIGHT]
        area   = stats[i, cv2.CC_STAT_AREA]
        aspect = max(bw_, bh_) / (min(bw_, bh_) + 1e-5)

        # Raised lower area limit from 15→6 to keep tiny dots (accents, i-dots)
        if area < 6:
            continue
        # Raised upper area limit from 15000→30000 to keep large connected chars
        if area > 30000:
            continue

        # Only skip long thin lines; relaxed area threshold from 200→500
        if aspect > 25 and area > 500:
            continue

        # Small blobs (dots, accents): always keep
        if area < 80:
            keep_mask[labels == i] = 255
            continue

        if area > 3000:
            box_area = bw_ * bh_
            # Relaxed ratio from 0.15→0.08 to keep large open characters like 'C','G'
            if area / (box_area + 1e-5) > 0.08:
                keep_mask[labels == i] = 255
            continue

        box_area   = bw_ * bh_
        fill_ratio = area / (box_area + 1e-5)

        # Relaxed fill ratio from 0.12→0.07 to keep thin strokes (l, 1, i, :)
        if fill_ratio < 0.07:
            continue

        blob = (labels[by_:by_+bh_, bx_:bx_+bw_] == i).astype(np.uint8) * 255
        cv   = stroke_cv(blob)

        # Relaxed stroke variation from 1.5→2.5 to keep more character shapes
        if cv < 2.5:
            keep_mask[labels == i] = 255

    return keep_mask


def enhance_kept_text(binary: np.ndarray, keep_mask: np.ndarray) -> np.ndarray:
    edge_k                = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    keep_mask             = cv2.dilate(keep_mask, edge_k, iterations=1)
    result                = np.full_like(binary, 255)
    result[keep_mask > 0] = 0
    return result


def preprocess_scanned_page(img_bgr: np.ndarray) -> np.ndarray:
    img_bgr = fix_rotation(img_bgr)
    img_bgr = erase_colored_ink(img_bgr)

    gray   = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    binary = binarize(gray)
    binary = remove_long_lines(binary)

    keep_mask = build_keep_mask(binary)
    cleaned   = enhance_kept_text(binary, keep_mask)

    # Safety check: if cleaning removed too much content, fall back to simple binarize
    dark_pixels = cv2.countNonZero(cv2.bitwise_not(cleaned))
    if dark_pixels < 300:
        # Almost nothing left — the blob filter was too aggressive; use binarize only
        return binary

    return cleaned


def preprocess_scanned_page_steps(img_bgr: np.ndarray) -> dict:
    """
    Run the full preprocessing pipeline and return a dict of intermediate images
    at each stage. Used by the Streamlit UI to visualize each step.

    Returns:
        OrderedDict with keys:
            'Source'         - original BGR image
            'Rotated'        - after rotation fix
            'Color Removed'  - after colored ink erasure
            'Binarized'      - after adaptive threshold
            'Lines Removed'  - after horizontal/vertical line removal
            'Final Cleaned'  - after blob filtering (final output)
    """
    steps = {}
    steps['Source'] = img_bgr.copy()

    rotated = fix_rotation(img_bgr)
    steps['Rotated'] = rotated.copy()

    decolored = erase_colored_ink(rotated)
    steps['Color Removed'] = decolored.copy()

    gray   = cv2.cvtColor(decolored, cv2.COLOR_BGR2GRAY)
    binary = binarize(gray)
    # Convert back to BGR for consistent display
    steps['Binarized'] = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

    no_lines = remove_long_lines(binary)
    steps['Lines Removed'] = cv2.cvtColor(no_lines, cv2.COLOR_GRAY2BGR)

    keep_mask = build_keep_mask(no_lines)
    cleaned   = enhance_kept_text(no_lines, keep_mask)

    # Safety fallback
    dark_pixels = cv2.countNonZero(cv2.bitwise_not(cleaned))
    if dark_pixels < 300:
        cleaned = binary

    steps['Final Cleaned'] = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)

    return steps


# ════════════════════════════════════════════════════════════════════════════
# PART 3 — OCR
# ════════════════════════════════════════════════════════════════════════════

def run_ocr(img: np.ndarray) -> str:
    return pytesseract.image_to_string(
        img, lang="fra+eng",
        config="--psm 6 --oem 1"
    ).strip()


def _fix_pharma_codes(text: str) -> str:
    """
    Fix systematic OCR misreads inside PF/PE/PH product codes.
    Examples:
      PFO00400001 → PF000400001  (O after prefix read as O, not 0)
      PFOO1S00016 → PF001500016  (two O→0, S→5)
      FF005500001 → PF005500001  (P misread as F)
      PFO01500013'  → PF001500013 (trailing quote noise)
    The 6-digit PCT code column gets the same treatment.
    Also fixes:
      § 530,320 → 5 530,320   (§ OCR'd instead of 5 at line start)
    """
    def _fix_code(m: re.Match) -> str:
        prefix = m.group(1)
        # P misread as F when followed by F: FF → PF
        if prefix.startswith('FF'):
            prefix = 'PF' + prefix[2:]
        digits = m.group(2)
        # Within the digit sequence: O→0, S→5, I→1, B→8 (common OCR swaps)
        digits = (
            digits
            .replace('O', '0')
            .replace('S', '5')
            .replace('I', '1')
            .replace('B', '8')
        )
        # Strip trailing noise after the code  (quote, dot, asterisk)
        suffix = m.group(3) if m.lastindex >= 3 else ''
        return prefix + digits + suffix

    # Match: 2-letter prefix (PF/PE/PH/FF) + 8-12 alphanums + optional trailing noise
    text = re.sub(
        r'\b(PF|PE|PH|FF)([0-9A-Z]{7,12}?)([\'\.\*]?)\b',
        _fix_code, text
    )
    # § at the start of a numeric context → 5
    text = re.sub(r'§\s*(\d)', r'5 \1', text)
    # Stray "ND" quantity means 0 (product not delivered / non disponible)
    text = re.sub(r'\bND\b', '0', text)
    return text


def clean_extracted_text(raw_text: str) -> str:
    text = raw_text

    # Remove PDF encoding artifacts
    text = re.sub(r'\(cid:\d+\)', '', text)

    # Collapse spaced-out letters ONLY when 6+ uppercase letters separated by spaces
    # (was 3+, which incorrectly collapsed short designations like "B/30 CP")
    text = re.sub(
        r'(?<!\w)([A-Z] ){5,}([A-Z])(?!\w)',
        lambda m: m.group(0).replace(' ', ''),
        text
    )
    text = re.sub(
        r'(?<!\w)((?:[A-Z0-9] ){6,}[A-Z0-9])(?!\w)',
        lambda m: m.group(0).replace(' ', ''),
        text
    )

    # Fix pharma product codes (PF/PE/PH codes: O→0, S→5, FF→PF, § fixes)
    text = _fix_pharma_codes(text)

    # Clean stray pipe characters used as column separators
    text = re.sub(r'(?<=[A-Za-z0-9])\|(?=[A-Za-z0-9])', ' ', text)
    text = re.sub(r'^\s*\|\s*$', '', text, flags=re.MULTILINE)

    # Fix OCR degree/zero confusion
    text = re.sub(r'(\d)°o', r'\g<1>0', text)
    text = re.sub(r'(\d)°(?=\d)', r'\g<1>0', text)
    text = re.sub(r'(\d)°(?=\s|$)', r'\g<1>', text)

    # Fix l/I ↔ 1 confusion only between clear digit contexts
    text = re.sub(r'(?<=\d)l(?=\d)', '1', text)
    text = re.sub(r'(?<=\d)l(?=\s)', '1', text)
    text = re.sub(r'(?<=\s)l(?=\d)', '1', text)
    text = re.sub(r'(?<=\d)I(?=\d)', '1', text)
    text = re.sub(r'\bI(?=\d{2,})', '1', text)

    # Pharma OCR circled artifacts
    text = re.sub(r'©', '', text)
    text = re.sub(r'(?<=\d)°(?=\d)', '0', text)

    # Strip leading quote/backtick noise from quantities: '216 → 216
    text = re.sub(r'(?m)^[\"\']+(\d)', r'\1', text)

    # Fix common document keyword OCR mistakes
    text = re.sub(r'(?i)\b(on de commande)\b', 'Bon de commande', text)
    text = re.sub(r'(?i)\b(on de [Ll]ivraison)\b', 'Bon de livraison', text)
    text = re.sub(r'(?i)\b(?:[co]mmande|ommande)\b', 'Commande', text)

    # Normalize spacing/dashes
    text = re.sub(r'[=\~_—]+', ' ', text)
    text = re.sub(r'(?m)(?:^\s*-\s+|\s+-\s+)', ' ', text)
    text = re.sub(r'(?m)\s+-$', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)

    clean_lines = []
    for line in text.splitlines():
        stripped = line.strip()

        if not stripped:
            clean_lines.append('')
            continue

        alnum_count  = len(re.findall(r'[A-Za-z0-9]', stripped))
        total_count  = len(stripped)
        symbol_ratio = 1 - (alnum_count / (total_count + 1e-5))

        if alnum_count < 2:
            continue

        if symbol_ratio > 0.65:
            continue

        has_word   = bool(re.search(r'[A-Za-z]{2,}', stripped))
        has_number = bool(re.search(r'\d', stripped))
        if not has_word and not has_number:
            continue

        clean_lines.append(stripped)

    return "\n".join(clean_lines)


# ════════════════════════════════════════════════════════════════════════════
# PART 4 — TEXT STRUCTURE PARSER
# ════════════════════════════════════════════════════════════════════════════

def parse_text_structure(raw_text: str) -> dict:
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if not lines:
        return {"header": [], "body": [], "footer": []}

    table_keywords = [
        "désignation", "designation", "description", "libellé",
        "article", "code", "qté", "quantité", "montant",
        "prix", "total", "no.", "n°", "référence"
    ]
    footer_keywords = [
        "total", "tva", "ttc", "signature", "cachet", "continued",
        "timbre", "remise", "transport", "arrêté", "page", "sur"
    ]

    table_start = None
    for i, line in enumerate(lines):
        if sum(1 for kw in table_keywords if kw in line.lower()) >= 2:
            table_start = i
            break

    if table_start is None:
        split = max(1, len(lines) // 3)
        return {"header": lines[:split], "body": lines[split:], "footer": []}

    header_lines = lines[:table_start]
    remaining    = lines[table_start:]

    # Collect footer candidates from the bottom up,
    # but don't stop at the first non-footer line — keep scanning
    # so a single body line doesn't cut off the whole footer region.
    footer_indices = set()
    for i in range(len(remaining) - 1, max(-1, len(remaining) - 12), -1):
        if any(kw in remaining[i].lower() for kw in footer_keywords):
            footer_indices.add(i)

    # The footer starts at the lowest index that is a continuous
    # block going to the end (with at most 2 non-footer gaps allowed)
    if footer_indices:
        footer_start = max(footer_indices)
        for i in range(footer_start, len(remaining)):
            footer_indices.add(i)   # extend to end once found
        footer_start = min(footer_indices)
    else:
        footer_start = len(remaining)

    return {
        "header": header_lines,
        "body":   remaining[:footer_start],
        "footer": remaining[footer_start:]
    }


# ════════════════════════════════════════════════════════════════════════════
# PART 5 — NATIVE PDF EXTRACTION
# ════════════════════════════════════════════════════════════════════════════

def extract_native_pdf(pdf_path: str) -> dict:
    result = {
        "pdf_type": "native", "source_file": Path(pdf_path).name,
        "total_pages": 0, "pages": []
    }
    with pdfplumber.open(pdf_path) as pdf:
        result["total_pages"] = len(pdf.pages)
        for page_num, page in enumerate(pdf.pages, start=1):
            raw_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            clean_text = clean_extracted_text(raw_text)

            tables   = [
                [[cell or "" for cell in row] for row in t]
                for t in (page.extract_tables() or [])
            ]
            result["pages"].append({
                "page_number": page_num,
                "structure":   parse_text_structure(clean_text),
                "tables":      tables
            })
    return result


# ════════════════════════════════════════════════════════════════════════════
# PART 6 — SCANNED PDF PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def extract_scanned_pdf(pdf_path: str, save_debug_images: bool = False) -> dict:
    result = {
        "pdf_type": "scanned", "source_file": Path(pdf_path).name,
        "total_pages": 0, "pages": []
    }
    doc = fitz.open(pdf_path)
    result["total_pages"] = len(doc)
    print(f"  [{Path(pdf_path).name}] {len(doc)} page(s)...")

    for i in range(len(doc)):
        print(f"    Page {i+1}/{len(doc)}...")
        img_bgr   = pdf_page_to_image(pdf_path, i, dpi=300)
        clean_img = preprocess_scanned_page(img_bgr)

        if save_debug_images:
            path = f"debug_{Path(pdf_path).stem}_p{i+1}.png"
            cv2.imwrite(path, clean_img)
            print(f"    Debug: {path}")

        raw_text   = run_ocr(clean_img)
        clean_text = clean_extracted_text(raw_text)

        result["pages"].append({
            "page_number": i + 1,
            "structure":   parse_text_structure(clean_text)
        })
    return result


# ════════════════════════════════════════════════════════════════════════════
# PART 6.5 — DIRECT IMAGE PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def extract_image(img_path: str, save_debug_images: bool = False) -> dict:
    result = {
        "file_type": "image", "source_file": Path(img_path).name,
        "total_pages": 1, "pages": []
    }
    print(f"  [{Path(img_path).name}] 1 image...")

    # Load the image directly using OpenCV
    img_bgr = cv2.imread(img_path)
    if img_bgr is None:
        raise ValueError(f"Could not read image file: {img_path}")

    # Send straight to your existing image processing functions
    clean_img = preprocess_scanned_page(img_bgr)

    if save_debug_images:
        path = f"debug_{Path(img_path).stem}.png"
        cv2.imwrite(path, clean_img)
        print(f"    Debug: {path}")

    # Run OCR and text cleaning
    raw_text   = run_ocr(clean_img)
    clean_text = clean_extracted_text(raw_text)

    result["pages"].append({
        "page_number": 1,
        "structure":   parse_text_structure(clean_text)
    })
    return result


# ════════════════════════════════════════════════════════════════════════════
# PART 7 — MASTER ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

def extract_invoice(file_path: str, save_debug_images: bool = False) -> dict:
    print(f"\n{'='*60}")
    print(f"Processing: {Path(file_path).name}")
    
    # Grab the file extension (e.g., '.pdf', '.png')
    ext = Path(file_path).suffix.lower()

    if ext == '.pdf':
        pdf_type = detect_pdf_type(file_path)
        print(f"  Type: PDF ({pdf_type.upper()})")
        result = (extract_native_pdf(file_path) if pdf_type == "native"
                  else extract_scanned_pdf(file_path, save_debug_images))
                  
    elif ext in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp']:
        print(f"  Type: DIRECT IMAGE")
        result = extract_image(file_path, save_debug_images)
        
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    total_lines = sum(
        len(p["structure"]["header"]) +
        len(p["structure"]["body"])   +
        len(p["structure"]["footer"])
        for p in result["pages"]
    )
    print(f"  Done — {total_lines} lines, {result['total_pages']} page(s)")
    print(f"{'='*60}")
    return result


# ════════════════════════════════════════════════════════════════════════════
# PART 8 — TEST RUNNER
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess
    try:
        v = subprocess.check_output(
            [pytesseract.pytesseract.tesseract_cmd, "--version"],
            stderr=subprocess.STDOUT
        ).decode().splitlines()[0]
        print(f"Tesseract OK: {v}\n")
    except FileNotFoundError:
        print("ERROR: Run 'where tesseract' and update line 13.")
        exit(1)

    test_files = [
        "distrimed medis.pdf",
        "Etat_Stat_vente Opalia (5).pdf",
        "MODELE PROFORMA.pdf",
        "file-1677758666332-748397730.pdf",
        "pharmaservice.pdf",
        "journal_vente_labo_v2 (12).pdf",
        "smpharma medis.pdf",
        # Adding dummy image files for testing
        "invoice_scan.jpg",
        "receipt_photo.png" 
    ]

    for file_path in test_files:
        if not os.path.exists(file_path):
            print(f"[SKIP] {file_path}")
            continue

        result = extract_invoice(file_path, save_debug_images=True)

        out = f"result_{Path(file_path).stem}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"Saved: {out}")

        p1 = result["pages"][0]["structure"]
        print(f"\nPage 1 preview:")
        print(f"  HEADER: {p1['header'][:3]}")
        print(f"  BODY:   {p1['body'][:3]}")
        print(f"  FOOTER: {p1['footer'][:2]}")