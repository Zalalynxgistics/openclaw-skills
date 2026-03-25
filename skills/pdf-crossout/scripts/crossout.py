#!/usr/bin/env python3
"""Add diagonal cross-out lines, rotated overlay text, and "สำเนาถูกต้อง" certification to PDF.

Renders overlay as image and stamps onto each PDF page for pixel-perfect results.
Detects content clusters — if a page has 2 separate content blocks (e.g. ID card front+back
scanned on one A4 page), draws crossout on EACH block. Cert block appears once at bottom.

Usage:
    python3 crossout.py <input.pdf> <output.pdf> [options]
"""

import argparse
import math
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_FONT = os.path.join(SKILL_DIR, "assets", "Sarabun-Bold.ttf")


def detect_content_clusters(img, content_threshold=230, gap_threshold_ratio=0.06):
    """Detect content clusters on the page. Returns list of (left, top, right, bottom) boxes.
    If content has a big vertical gap, splits into separate clusters."""
    W, H = img.size
    gray = img.convert('L')

    # Row scan
    min_count = (W // 4) * 0.05
    row_has_content = []
    for y in range(0, H, 2):
        count = 0
        for x in range(0, W, 4):
            if gray.getpixel((x, y)) < content_threshold:
                count += 1
        row_has_content.append((y, count > min_count))

    # Find contiguous content bands
    bands = []
    in_band = False
    band_start = 0
    empty_run = 0
    # Minimum gap to split clusters (6% of page height)
    min_gap = int(H * gap_threshold_ratio)

    for y, has in row_has_content:
        if has:
            if not in_band:
                if bands and empty_run < min_gap:
                    # Gap too small — merge back with previous band
                    band_start = bands.pop()[0]
                else:
                    band_start = y
                in_band = True
            empty_run = 0
        else:
            if in_band:
                bands.append((band_start, y))
                in_band = False
            empty_run += 2
    if in_band:
        bands.append((band_start, H))

    if not bands:
        return [(0, 0, W, H)]

    # For each band, find left/right extent
    clusters = []
    for top, bot in bands:
        left, right = W, 0
        for y in range(top, bot + 1, 4):
            for x in range(0, W, 4):
                if gray.getpixel((x, y)) < content_threshold:
                    left = min(left, x)
                    right = max(right, x)
        if left >= right:
            left, right = 0, W
        clusters.append((left, top, right, bot))

    # Filter out noise: remove clusters smaller than 5% of page height
    min_cluster_h = H * 0.05
    clusters = [c for c in clusters if (c[3] - c[1]) >= min_cluster_h]

    if not clusters:
        return [(0, 0, W, H)]

    # Filter out footers: if last cluster is in bottom 15% of page AND either:
    # - much smaller than largest cluster (< 30% of largest height), OR
    # - absolutely small (< 15% of page height)
    if len(clusters) >= 2:
        largest_h = max(c[3] - c[1] for c in clusters)
        last = clusters[-1]
        last_h = last[3] - last[1]
        in_bottom = last[1] > H * 0.85
        is_small_relative = last_h < largest_h * 0.30
        is_small_absolute = last_h < H * 0.15
        if in_bottom and (is_small_relative or is_small_absolute):
            clusters = clusters[:-1]

    if not clusters:
        return [(0, 0, W, H)]

    return clusters


def get_page_text(page, dpi=200):
    """Get text from a page: try PyMuPDF text extraction first, fall back to OCR."""
    text = ""
    if hasattr(page, 'get_text'):
        text = page.get_text()
    if len(text.strip()) < 20:
        try:
            import pytesseract
            from PIL import Image as PILImage
            pix = page.get_pixmap(dpi=dpi)
            img = PILImage.frombytes('RGB', [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img, lang='tha+eng')
        except Exception:
            pass
    return text


def detect_doc_type(text):
    """Detect document type from page text.
    Returns 'id_card', 'house_reg', or 'corporate'."""
    if not text:
        return 'corporate'
    keywords_id = ['บัตรประจำตัวประชาชน', 'บัตรประจําตัวประชาชน', 'National ID Card',
                    'Thai National ID']
    keywords_house = ['ทะเบียนบ้าน', 'รายการบุคคล', 'กำหนดบ้านเลขที่', 'กําหนดบ้านเลขที่']
    for kw in keywords_id:
        if kw in text:
            return 'id_card'
    for kw in keywords_house:
        if kw in text:
            return 'house_reg'
    return 'corporate'


def detect_document_owner(text, cert_names, doc_type='id_card'):
    """Detect which cert_name is the owner of this document.
    For house_reg: looks only at รายการบุคคล section (ignores เจ้าบ้าน/ผู้ขอเลขบ้าน).
    Returns the matching name, or None if no match."""
    import re

    if not text or not cert_names:
        return None

    search_text = text

    # For house registration, only look at the person listing section
    if doc_type == 'house_reg':
        # Try to find รายการบุคคล section
        markers = ['รายการบุคคล', 'ลําดับ', 'ลำดับ']
        for marker in markers:
            idx = text.find(marker)
            if idx >= 0:
                search_text = text[idx:]
                break

    # Normalize for matching (remove prefix นาย/นาง/นางสาว, spaces)
    def normalize(name):
        name = re.sub(r'^(นาย|นาง|นางสาว)\s*', '', name.strip())
        return name.replace(' ', '')

    norm_names = {normalize(n): n for n in cert_names}
    text_norm = search_text.replace(' ', '')

    for norm, original in norm_names.items():
        if norm in text_norm:
            return original

    # Fuzzy: try matching first name or last name (>= 3 chars)
    for cert_name in cert_names:
        parts = cert_name.strip().split()
        for part in parts:
            if len(part) >= 3 and part in search_text:
                return cert_name

    # Extra fuzzy: try first 3 consonant chars of first name
    # (OCR often drops vowel marks like ั ิ ี etc.)
    import re
    def consonants_only(s):
        return re.sub(r'[ัิีึืุูเแโไใ็่้๊๋์ำ]', '', s)

    for cert_name in cert_names:
        first_name = cert_name.strip().split()[0]
        fn_cons = consonants_only(first_name)
        if len(fn_cons) >= 3:
            # Check if these consonants appear in sequence in the text
            search_cons = consonants_only(search_text)
            if fn_cons[:4] in search_cons:
                return cert_name

    return None


def find_header_bottom(img, cluster_box, content_threshold=230):
    """Within a content cluster, detect header area (logo/emblem + title at top).
    Returns the y-coordinate where body content starts (below header).
    If no header detected, returns cluster top."""
    cl, ct, cr, cb = cluster_box
    cluster_h = cb - ct
    W = img.size[0]
    gray = img.convert('L')

    # Only look for headers in the top 35% of the cluster
    scan_limit = ct + int(cluster_h * 0.35)

    # Scan rows within cluster top area for density
    row_data = []
    for y in range(ct, min(scan_limit, cb), 2):
        count = 0
        for x in range(cl, cr, 4):
            if gray.getpixel((x, y)) < content_threshold:
                count += 1
        total = max((cr - cl) // 4, 1)
        density = count / total
        row_data.append((y, density))

    if not row_data:
        return ct

    # Look for a gap (low density zone) that separates header from body
    # A gap is a consecutive run of rows with density < 0.02
    min_gap_rows = max(3, int(cluster_h * 0.015))  # at least 1.5% of cluster height
    gap_start = None
    gap_count = 0
    best_gap_end = None

    for y, d in row_data:
        if d < 0.02:
            if gap_start is None:
                gap_start = y
            gap_count += 1
        else:
            if gap_count >= min_gap_rows and gap_start is not None:
                # Found a gap — the content above is header
                best_gap_end = y
                break
            gap_start = None
            gap_count = 0

    if best_gap_end is not None:
        return best_gap_end

    return ct


def detect_card_rotation(img):
    """Detect rotation angle of card content using Hough line detection.
    Returns angle in degrees (positive = clockwise rotation of card).
    Uses 0.1° resolution Hough transform on near-horizontal edges."""
    import cv2, numpy as np
    img_cv = np.array(img)
    gray = cv2.cvtColor(img_cv, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 1800, 150)  # 0.1° resolution
    if lines is None:
        return 0.0
    import math
    h_angles = []
    for rho, theta in lines[:, 0]:
        angle = math.degrees(theta) - 90
        if abs(angle) < 10:
            h_angles.append(angle)
    if not h_angles:
        return 0.0
    return float(np.median(h_angles))


def detect_redact_positions(img, fields, dpi=200):
    """Detect positions of sensitive field VALUES on an image using OCR.
    Returns (rects, angle) where rects is list of [x1,y1,x2,y2] and angle is card rotation."""
    angle = detect_card_rotation(img)
    rects = redact_fields(img, fields, dpi=dpi, detect_only=True)
    return rects, angle


def redact_fields(img, fields, redact_color=(128, 128, 128), dpi=200, detect_only=False):
    """Redact sensitive field VALUES on an image using OCR.

    If detect_only=True, returns list of [x1,y1,x2,y2] rects without drawing.

    Strategy:
    1. Run Tesseract TSV to get all character/word boxes
    2. For each field label, find nearby OCR chars that spell it out (tight Y tolerance)
    3. If OCR text match fails (Thai OCR is unreliable), use positional fallback:
       - Find "Date of Birth" / "Birth" (English, reliable OCR)
       - Religion line is ~20-40px below Date of Birth on Thai ID cards
       - Cover the value portion of that line
    4. Draw gray bar over the value area

    Args:
        img: PIL Image
        fields: list of field label strings (e.g. ['ศาสนา', 'หมู่เลือด'])
        redact_color: RGB tuple for the redaction bar
        dpi: render DPI
    Returns:
        img with redaction bars drawn
    """
    import subprocess
    import tempfile
    import numpy as np

    # --- Crop to content area for better OCR accuracy ---
    # Use gap analysis to find the main content cluster (skip isolated noise rows)
    arr = np.array(img)
    gray = np.mean(arr, axis=2)
    W_img, H_img = img.size
    row_density = np.mean(gray < 200, axis=1)
    content_rows_mask = row_density > 0.03

    # Find contiguous content bands (skip gaps > 3% of page height)
    gap_threshold = int(H_img * 0.03)
    bands = []
    band_start = None
    gap_count = 0
    for y in range(H_img):
        if content_rows_mask[y]:
            if band_start is None:
                band_start = y
            gap_count = 0
        else:
            gap_count += 1
            if band_start is not None and gap_count > gap_threshold:
                bands.append((band_start, y - gap_count))
                band_start = None
    if band_start is not None:
        bands.append((band_start, H_img - 1))

    # Pick the largest band as the main content
    crop_x1 = crop_y1 = 0
    if bands:
        largest_band = max(bands, key=lambda b: b[1] - b[0])
        crop_y1 = max(0, largest_band[0] - 10)
        crop_y2 = min(H_img, largest_band[1] + 10)

        # Find x range within the band
        band_gray = gray[crop_y1:crop_y2, :]
        col_density = np.mean(band_gray < 200, axis=0)
        content_cols = np.where(col_density > 0.03)[0]
        if len(content_cols) > 10:
            crop_x1 = max(0, content_cols[0] - 10)
            crop_x2 = min(W_img, content_cols[-1] + 10)
        else:
            crop_x1 = 0
            crop_x2 = W_img
        cropped_img = img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    else:
        cropped_img = img

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        tmp_path = f.name
        cropped_img.save(tmp_path)

    try:
        result = subprocess.run(
            ['tesseract', tmp_path, 'stdout', '-l', 'tha+eng', '--psm', '6', 'tsv'],
            capture_output=True, text=True, timeout=60
        )
        tsv_lines = result.stdout.strip().split('\n')
        if len(tsv_lines) < 2:
            return img

        rows = []
        for line in tsv_lines[1:]:
            cols = line.split('\t')
            if len(cols) >= 12:
                try:
                    text = cols[11].strip()
                    if text:
                        rows.append({
                            'x': int(cols[6]) + crop_x1, 'y': int(cols[7]) + crop_y1,
                            'w': int(cols[8]), 'h': int(cols[9]),
                            'conf': float(cols[10]),
                            'text': text
                        })
                except (ValueError, IndexError):
                    pass

        if not rows:
            return img

        from PIL import ImageDraw
        if not detect_only:
            draw = ImageDraw.Draw(img)
        collected_rects = []
        W, H = img.size

        # --- Helper: find boxes on same line (tight Y tolerance: ±10px of y_center) ---
        def find_line_boxes(anchor_yc, y_tol=10):
            """Return all OCR boxes whose y_center is within y_tol of anchor_yc."""
            result = []
            for r in rows:
                rc = r['y'] + r['h'] // 2
                if abs(rc - anchor_yc) <= y_tol:
                    result.append(r)
            result.sort(key=lambda b: b['x'])
            return result

        # --- Helper: find label by scanning for starting chars ---
        def find_label_by_chars(label):
            """Find OCR boxes that spell out a Thai label (e.g. 'ศาสนา').
            Returns (label_boxes, value_boxes) or (None, None) if not found.
            Thai OCR splits words into chars, so look for the first char/bigram
            of the label, then verify subsequent chars exist nearby."""
            # Look for boxes containing the first 1-2 chars of the label
            first_chars = [label[:2], label[:1]]
            candidates = []
            for r in rows:
                for fc in first_chars:
                    if fc in r['text']:
                        candidates.append(r)
                        break

            for anchor in candidates:
                anchor_yc = anchor['y'] + anchor['h'] // 2
                line_boxes = find_line_boxes(anchor_yc, y_tol=8)
                if not line_boxes:
                    continue

                # Concatenate all text on this line, sorted by x
                line_text = ''.join(b['text'] for b in line_boxes)

                # Check if label appears in this line
                label_clean = label.replace(' ', '')
                line_clean = line_text.replace(' ', '')
                idx = line_clean.find(label_clean)
                if idx < 0:
                    # Try consonant-only match (strip vowels/tonemarks)
                    import unicodedata
                    def consonants_only(s):
                        return ''.join(c for c in s if '\u0e01' <= c <= '\u0e2e')
                    lc = consonants_only(label_clean)
                    tc = consonants_only(line_clean)
                    ci = tc.find(lc)
                    if ci < 0 or len(lc) < 2:
                        continue
                    # Matched by consonants — use this line
                    idx = 0  # approximate

                # Found the label on this line!
                # The label occupies roughly the first portion; value is what follows.
                # Find the x position where the label text ends.
                char_count = 0
                label_end_x = anchor['x']  # fallback
                for box in line_boxes:
                    box_text = box['text'].replace(' ', '')
                    char_count += len(box_text)
                    if char_count >= idx + len(label_clean):
                        label_end_x = box['x'] + box['w']
                        break

                # Value boxes = everything to the right of label on this line
                # Add small gap (8px) after label to avoid covering the label
                val_boxes = [b for b in line_boxes if b['x'] >= label_end_x + 8]
                lbl_boxes = [b for b in line_boxes if b['x'] < label_end_x]
                return lbl_boxes, val_boxes

            return None, None

        # --- Helper: positional fallback using "Date of Birth" / "Birth" ---
        def find_religion_by_position():
            """Find religion line by locating 'Birth' in English (reliable OCR)
            then looking ~20-40px below it. Returns value boxes or None."""
            birth_y = None
            birth_x_start = None
            for r in rows:
                if 'Birth' in r['text'] or 'birth' in r['text']:
                    birth_y = r['y'] + r['h'] // 2
                    birth_x_start = r['x']
                    break
            if birth_y is None:
                # Try "Date of"
                for r in rows:
                    if 'Date' in r['text']:
                        birth_y = r['y'] + r['h'] // 2
                        birth_x_start = r['x']
                        break
            if birth_y is None:
                return None

            # Religion line is ~20-40px below Birth line on Thai ID cards at 200dpi
            # Scan for content in that Y range
            religion_yc = birth_y + 30  # approximate center
            line_boxes = find_line_boxes(religion_yc, y_tol=15)
            if not line_boxes:
                # Try wider range
                for offset in [20, 25, 35, 40]:
                    line_boxes = find_line_boxes(birth_y + offset, y_tol=10)
                    if line_boxes:
                        break

            if not line_boxes:
                return None

            # Filter out margin artifacts (=, |, -, etc.) and keep only meaningful text
            # Also filter by x position (> 40% of image width) to skip card edge artifacts
            W_img = img.size[0]
            def is_meaningful_text(t):
                """Check if text contains at least one Thai char or Latin letter."""
                return any(('\u0e01' <= c <= '\u0e7f') or c.isalpha() for c in t)
            text_boxes = [b for b in line_boxes
                          if b['conf'] > 5 and b['x'] > W_img * 0.4
                          and is_meaningful_text(b['text'])]
            if not text_boxes:
                return None

            # The label "ศาสนา" is the first ~50px of text, value follows after
            leftmost_x = min(b['x'] for b in text_boxes)
            label_width = 55  # ~55px at 200dpi for "ศาสนา"
            val_boxes = [b for b in text_boxes if b['x'] > leftmost_x + label_width - 5]
            # Limit value width — religion value (พุทธ etc.) is short, ~80px max at 200dpi
            if val_boxes:
                val_left = min(b['x'] for b in val_boxes)
                val_boxes = [b for b in val_boxes if b['x'] < val_left + 100]
            return val_boxes

        # --- Main redaction logic ---
        # Known ID card fields and their positional fallbacks
        POSITIONAL_FIELDS = {'ศาสนา', 'หมู่เลือด'}

        for field_label in fields:
            redacted = False

            # --- Helper: normalize redact rectangle ---
            def draw_redact_rect(val_boxes):
                """Draw a redaction rectangle over value boxes with normalized size.
                - Height capped to ~25px (text line height at 200dpi), not OCR box height
                - Minimum width 80px so character count can't be guessed
                """
                if not val_boxes:
                    return
                vx1 = min(b['x'] for b in val_boxes)
                vx2 = max(b['x'] + b['w'] for b in val_boxes)
                # Use y_center of boxes, fixed height of 22px (reasonable for 200dpi text)
                y_centers = [b['y'] + b['h'] // 2 for b in val_boxes]
                avg_yc = sum(y_centers) // len(y_centers)
                rect_h = 22  # fixed height at 200dpi
                vy1 = avg_yc - rect_h // 2
                vy2 = avg_yc + rect_h // 2
                # Minimum width 80px — extend to the right only
                min_w = 80
                cur_w = vx2 - vx1
                if cur_w < min_w:
                    vx2 = vx1 + min_w
                pad = 5  # padding for visibility
                # Asymmetric padding: minimal left (to not cover label), more right
                rect = [vx1 - 2, vy1 - pad, vx2 + pad + 5, vy2 + pad]
                if detect_only:
                    collected_rects.append(rect)
                else:
                    draw.rectangle(rect, fill=redact_color)

            # Strategy 1: Direct OCR text match
            lbl_boxes, val_boxes = find_label_by_chars(field_label)
            if val_boxes:
                val_left = min(b['x'] for b in val_boxes)
                val_boxes = [b for b in val_boxes if b['x'] < val_left + 100]
                draw_redact_rect(val_boxes)
                redacted = True

            # Strategy 2: Positional fallback for known fields
            if not redacted and field_label in POSITIONAL_FIELDS:
                if field_label == 'ศาสนา':
                    val_boxes = find_religion_by_position()
                    if val_boxes:
                        draw_redact_rect(val_boxes)

    finally:
        os.unlink(tmp_path)

    if detect_only:
        return collected_rects
    return img


def main():
    parser = argparse.ArgumentParser(description="Add cross-out lines, rotated text, and certification to PDF")
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument("output", help="Output PDF path")
    parser.add_argument("--text", action="append", default=[], help="Rotated text line (repeatable, max 5)")
    parser.add_argument("--opacity", type=float, default=0.7)
    parser.add_argument("--line-width", type=int, default=2)
    parser.add_argument("--font-path", default=DEFAULT_FONT)
    parser.add_argument("--no-cert", action="store_true")
    parser.add_argument("--cert-position", default="auto", choices=["auto", "bottom-right", "bottom-left", "bottom-center"])
    parser.add_argument("--cert-name", action="append", default=[], help="Name under signature line (repeatable)")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--quality", type=int, default=90)
    parser.add_argument("--preserve-id", action="store_true", help="Preserve 13-digit national ID number (don't draw crossout over it)")
    parser.add_argument("--no-wrap", action="store_true", help="Don't wrap text - single line even if wider than cluster")
    parser.add_argument("--angle", type=int, default=45, help="Rotation angle in degrees (default: 45)")
    parser.add_argument("--cy-offset", type=float, default=0, help="Manual vertical center offset as fraction of cluster height (-0.3 = up 30%%, +0.3 = down 30%%)")
    parser.add_argument("--redact", action="append", default=[], metavar="FIELD",
                        help="Redact sensitive field values with gray bar (repeatable). "
                             "Built-in: 'ศาสนา', 'หมู่เลือด'. Custom: 'label=ศาสนา' to redact value after label.")
    parser.add_argument("--redact-color", default="180,180,180",
                        help="Redact bar RGB color (default: 180,180,180 light gray)")
    args = parser.parse_args()

    if len(args.text) > 5:
        print("Error: max 5 text lines", file=sys.stderr)
        sys.exit(1)

    try:
        import fitz  # PyMuPDF
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Error: install PyMuPDF and Pillow (pip install PyMuPDF Pillow)", file=sys.stderr)
        sys.exit(1)

    alpha = int(args.opacity * 255)
    color = (0, 0, 0, alpha)

    doc = fitz.open(args.input)

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=args.dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Detect redact positions on ORIGINAL image, draw BEFORE crossout
        # so crossout lines remain visible on top of the light gray bar
        redact_rects = []
        redact_angle = 0.0
        if args.redact:
            rc = tuple(int(c) for c in args.redact_color.split(','))
            redact_rects, redact_angle = detect_redact_positions(img, args.redact, dpi=args.dpi)
            # Draw redact bars now (before crossout)
            if redact_rects:
                if abs(redact_angle) < 0.05:
                    from PIL import ImageDraw as ID2
                    draw_r = ID2.Draw(img)
                    for rect in redact_rects:
                        draw_r.rectangle(rect, fill=rc)
                else:
                    import cv2
                    import numpy as np
                    img_cv = np.array(img)
                    rad = math.radians(redact_angle)
                    cos_a, sin_a = math.cos(rad), math.sin(rad)
                    for rect in redact_rects:
                        x1, y1, x2, y2 = rect
                        cx, cy = (x1+x2)/2, (y1+y2)/2
                        hw, hh = (x2-x1)/2, (y2-y1)/2
                        corners = [(-hw,-hh),(hw,-hh),(hw,hh),(-hw,hh)]
                        pts = [[int(round(cx+dx*cos_a-dy*sin_a)), int(round(cy+dx*sin_a+dy*cos_a))] for dx,dy in corners]
                        cv2.fillPoly(img_cv, [np.array(pts, dtype=np.int32)], color=(rc[2],rc[1],rc[0]), lineType=cv2.LINE_AA)
                    img = Image.fromarray(img_cv)

        draw = ImageDraw.Draw(img, 'RGBA')
        W, H = img.size

        # Detect content clusters
        clusters = detect_content_clusters(img)

        cross_text_bottom = 0  # track lowest point of crossout for cert placement

        # --preserve-id: adjust angle/position for ID cards

        # --preserve-id: for Thai ID cards, shift crossout band down + reduce angle
        # to avoid overlapping the 13-digit ID number at the top of the card
        _preserve_cy_offset = 0
        if args.preserve_id and clusters and args.text:
            page_text = get_page_text(page, args.dpi)
            doc_type_check = detect_doc_type(page_text)

            if doc_type_check == 'id_card':
                cl0, ct0, cr0, cb0 = clusters[0]
                ch0 = cb0 - ct0
                # Shift center down by 25% of cluster height + use 20° angle
                _preserve_cy_offset = int(ch0 * 0.25)
                args.angle = min(args.angle, 20)

        if args.text:
            for cl, ct, cr, cb in clusters:
                # Detect header and skip it (only for large clusters > 25% of page height)
                raw_ch = cb - ct
                if raw_ch > H * 0.25:
                    body_top = find_header_bottom(img, (cl, ct, cr, cb))
                else:
                    body_top = ct
                ct_eff = body_top  # effective top for crossout (below header)
                cw = cr - cl
                ch = cb - ct_eff
                if ch < 20:
                    continue  # skip if almost no body content
                cx = (cl + cr) // 2
                cy = (ct_eff + cb) // 2
                # Apply preserve-id offset
                if args.preserve_id:
                    cy += _preserve_cy_offset
                # Apply manual cy-offset
                if args.cy_offset:
                    cy += int(ch * args.cy_offset)

                # Scale font: text width ~30-40% of cluster width
                font_size = 28
                font_text = ImageFont.truetype(args.font_path, font_size)

                all_lines = list(args.text)
                max_text_w = int(cw * 1.5) if args.no_wrap else int(cw * 0.7)

                # Scale font so text is visible on this cluster
                max_line = max(all_lines, key=len)
                bbox = font_text.getbbox(max_line)
                tw = bbox[2] - bbox[0]
                min_width = cw * 0.3
                if tw > 0 and tw < min_width:
                    font_size = int(font_size * min_width / tw)
                    font_size = min(font_size, 100)
                    font_text = ImageFont.truetype(args.font_path, font_size)

                # Wrap long lines
                wrapped_lines = []
                for line in all_lines:
                    lb = font_text.getbbox(line)
                    lw = lb[2] - lb[0]
                    if lw <= max_text_w:
                        wrapped_lines.append(line)
                    else:
                        words = line.split(' ')
                        current = ""
                        for word in words:
                            test = (current + " " + word).strip()
                            tb = font_text.getbbox(test)
                            if (tb[2] - tb[0]) > max_text_w and current:
                                wrapped_lines.append(current)
                                current = word
                            else:
                                current = test
                        if current:
                            wrapped_lines.append(current)
                all_lines = wrapped_lines[:5]

                # Recalculate text dimensions
                max_line = max(all_lines, key=len)
                bbox = font_text.getbbox(max_line)
                tw = bbox[2] - bbox[0]
                ascent, descent = font_text.getmetrics()
                th_single = ascent + descent
                line_spacing = th_single + 4
                total_text_h = len(all_lines) * line_spacing

                # Create band image for rotated text
                # Use cluster diagonal, not full page diagonal, to avoid overflow
                diag_len = int(math.sqrt(cw ** 2 + ch ** 2))
                # For no-wrap, ensure diag_len fits the full text width
                if args.no_wrap:
                    max_line_now = max(all_lines, key=len)
                    tw_check = font_text.getbbox(max_line_now)[2] - font_text.getbbox(max_line_now)[0]
                    diag_len = max(diag_len, tw_check + 80)
                band_h = total_text_h + 100
                txt_img = Image.new('RGBA', (diag_len, band_h), (0, 0, 0, 0))
                txt_draw = ImageDraw.Draw(txt_img)

                bcx, bcy = diag_len // 2, band_h // 2
                gap_top = total_text_h // 2 + 12
                gap_bot = total_text_h // 2 + 12 - th_single // 4

                # Parallel lines
                line_half = tw // 2 + 20
                txt_draw.line([(bcx - line_half, bcy - gap_top), (bcx + line_half, bcy - gap_top)],
                              fill=color, width=args.line_width)
                txt_draw.line([(bcx - line_half, bcy + gap_bot), (bcx + line_half, bcy + gap_bot)],
                              fill=color, width=args.line_width)

                # Draw text lines centered
                for i, line in enumerate(all_lines):
                    lbbox = font_text.getbbox(line)
                    lw = lbbox[2] - lbbox[0]
                    x_off = lbbox[0]
                    y = bcy - total_text_h // 2 + i * line_spacing
                    txt_draw.text((bcx - lw // 2 - x_off, y), line, font=font_text, fill=color)

                # Rotate and paste centered on this cluster
                txt_img_rot = txt_img.rotate(args.angle, expand=True, resample=Image.BICUBIC)
                paste_x = cx - txt_img_rot.width // 2
                paste_y = cy - txt_img_rot.height // 2
                # Clamp to keep within page bounds
                paste_y = max(0, min(paste_y, H - txt_img_rot.height))
                paste_x = max(0, min(paste_x, W - txt_img_rot.width))
                img.paste(txt_img_rot, (paste_x, paste_y), txt_img_rot)

                # Track bottom of crossout
                rot_data = txt_img_rot.split()
                rot_alpha = rot_data[3] if len(rot_data) == 4 else None
                actual_bottom_in_rot = txt_img_rot.height
                if rot_alpha:
                    for ry in range(txt_img_rot.height - 1, -1, -1):
                        for rx in range(0, txt_img_rot.width, 8):
                            if rot_alpha.getpixel((rx, ry)) > 10:
                                actual_bottom_in_rot = ry + 1
                                break
                        else:
                            continue
                        break
                this_bottom = paste_y + actual_bottom_in_rot
                cross_text_bottom = max(cross_text_bottom, this_bottom)

            # Also track the bottom of the last content cluster
            last_content_bottom = max(cb for _, _, _, cb in clusters)
        else:
            cross_text_bottom = 0
            last_content_bottom = 0

        # Cert block
        if not args.no_cert:
            draw = ImageDraw.Draw(img, 'RGBA')
            font_cert = ImageFont.truetype(args.font_path, 22)
            font_date = ImageFont.truetype(args.font_path, 18)
            names = args.cert_name

            def draw_cert_block(draw, cx_i, cert_y, name=""):
                """Draw a single cert block at given position."""
                cert_text = "สำเนาถูกต้อง"
                ccb = font_cert.getbbox(cert_text)
                ccw = ccb[2] - ccb[0]
                draw.text((cx_i - ccw // 2, cert_y), cert_text, font=font_cert, fill=color)
                sig_y = cert_y + 120
                draw.line([(cx_i - 100, sig_y), (cx_i + 100, sig_y)], fill=color, width=1)
                cur_y = sig_y + 4
                if name:
                    name_text = f"({name})"
                    nb = font_cert.getbbox(name_text)
                    nw = nb[2] - nb[0]
                    nh = nb[3] - nb[1]
                    draw.text((cx_i - nw // 2, cur_y), name_text, font=font_cert, fill=color)
                    cur_y += nh + nh // 2
                else:
                    cur_y += 6
                date_text = "___/___/___"
                db = font_date.getbbox(date_text)
                dw = db[2] - db[0]
                draw.text((cx_i - dw // 2, cur_y), date_text, font=font_date, fill=color)

            # Calculate block height for positioning
            cert_text_h = font_cert.getbbox("สำเนาถูกต้อง")[3] - font_cert.getbbox("สำเนาถูกต้อง")[1]
            sig_gap = 120
            name_h = 0
            if names:
                nb = font_cert.getbbox(f"({names[0]})")
                name_h = (nb[3] - nb[1]) + (nb[3] - nb[1]) // 2
            else:
                name_h = 6
            date_h = font_date.getbbox("___/___/___")[3] - font_date.getbbox("___/___/___")[1]
            block_height = cert_text_h + sig_gap + 4 + name_h + date_h + 20

            pos = args.cert_position if args.cert_position != "auto" else "bottom-right"
            if pos == "bottom-right":
                default_cx = W - 250
            elif pos == "bottom-left":
                default_cx = 250
            else:
                default_cx = W // 2

            # Detect document type and owner
            page_text = get_page_text(page, args.dpi)
            doc_type = detect_doc_type(page_text)
            # --preserve-id implies ID card even if OCR can't detect keywords
            if args.preserve_id and doc_type == 'corporate':
                doc_type = 'id_card'
            is_personal = doc_type in ('id_card', 'house_reg')

            # Personal docs (ID card, house reg): single owner signs
            if is_personal:
                owner = detect_document_owner(page_text, names, doc_type)
                if not owner:
                    owner = names[0]  # fallback
                # Place cert block below the last cluster, centered on page
                last_cl, last_ct, last_cr, last_cb = clusters[-1]
                cert_y_mc = last_cb + 10
                cert_y_mc = min(cert_y_mc, H - block_height - 10)
                # Use cert-position setting
                cert_cx_mc = default_cx
                draw_cert_block(draw, cert_cx_mc, cert_y_mc, owner)
            else:
                # Single cluster: all signers together at the bottom
                margin_bottom = int(2.0 * args.dpi / 2.54)
                min_cert_y = cross_text_bottom + 10
                cert_y_candidate = last_content_bottom + 20 if last_content_bottom else cross_text_bottom + 10
                cert_y_candidate = max(cert_y_candidate, min_cert_y)
                cert_y_max = H - margin_bottom - block_height
                cert_y = min(cert_y_candidate, cert_y_max)

                # Scan for empty band
                content_threshold = 230
                if min_cert_y < cert_y_max:
                    scan_gray = img.convert('L')
                    best_gap_start = None
                    best_gap_len = 0
                    gap_start = None
                    gap_len = 0
                    for y_scan in range(max(0, int(min_cert_y)), min(H, int(cert_y_max + block_height)), 3):
                        dark = 0
                        for x_scan in range(0, W, 6):
                            if scan_gray.getpixel((x_scan, y_scan)) < content_threshold:
                                dark += 1
                        is_empty = dark < (W // 6) * 0.02
                        if is_empty:
                            if gap_start is None:
                                gap_start = y_scan
                            gap_len += 3
                        else:
                            if gap_start is not None and gap_len > best_gap_len:
                                best_gap_start = gap_start
                                best_gap_len = gap_len
                            gap_start = None
                            gap_len = 0
                    if gap_start is not None and gap_len > best_gap_len:
                        best_gap_start = gap_start
                        best_gap_len = gap_len
                    if best_gap_start is not None and best_gap_len >= block_height:
                        cert_y = best_gap_start + 10
                        cert_y = min(cert_y, cert_y_max)

                n_signers = max(len(names), 1)
                if n_signers == 1:
                    centers = [default_cx]
                else:
                    col_w = W // (n_signers + 1)
                    centers = [col_w * (i + 1) for i in range(n_signers)]

                for i in range(n_signers):
                    name = names[i] if i < len(names) else ""
                    draw_cert_block(draw, centers[i], cert_y, name)

        # Redact bars already drawn before crossout (above)

        # Convert to JPEG and replace page
        import io
        buf = io.BytesIO()
        img_rgb = img.convert("RGB")
        img_rgb.save(buf, format="JPEG", quality=args.quality, optimize=True)
        buf.seek(0)
        img_bytes = buf.read()

        new_page = doc.new_page(pno=page_idx, width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=img_bytes)
        doc.delete_page(page_idx + 1)

    doc.save(args.output, deflate=True, garbage=4)
    doc.close()
    print(f"Done: {args.output} ({len(fitz.open(args.output))} pages)")


if __name__ == "__main__":
    main()
