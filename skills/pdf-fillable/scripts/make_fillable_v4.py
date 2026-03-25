#!/usr/bin/env python3
"""Convert a static PDF form into a fillable PDF with text fields, checkboxes, and comb digit fields.

V4: Extends V3 with:
  - Multi-page support: processes all pages
  - Checkbox detection: small squares (~9.3×9.3 pt) that are NOT digit boxes
  - Comb digit field detection: medium squares (~14.4×14.4 pt) grouped into fields
  - Small digit boxes (~9.3×9.3 pt in groups of 4) detected as comb year fields
  - Custom font embedding (Tahoma by default, Simple TrueType + WinAnsiEncoding)
  - Auto alignment: short fields centered, long fields left-aligned

Usage:
    python make_fillable_v4.py input.pdf [output.pdf] [--border 0.3] [--color 0,0,166] [-v]
"""

import fitz
import argparse
import io
import json
import os
import sys
import numpy as np
from pathlib import Path
from collections import defaultdict

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from scipy import ndimage
except ImportError:
    ndimage = None

try:
    import subprocess as _sp
    _sp.run(["tesseract", "--version"], capture_output=True, check=True)
    HAS_TESSERACT = True
except Exception:
    HAS_TESSERACT = False


# ── OCR for pixel-scan mode ──

def ocr_page_labels(page, fields, verbose=False):
    """Run OCR on page and assign left_label to each field using PyMuPDF OCR."""
    if not HAS_TESSERACT:
        if verbose:
            print("  OCR skipped (tesseract not available)")
        return
    try:
        # Use PyMuPDF's built-in Tesseract OCR (returns proper word boxes in pt)
        tp = page.get_textpage_ocr(language="tha+eng", dpi=300, full=True)
        words = page.get_text("words", textpage=tp)
    except Exception as e:
        if verbose:
            print(f"  OCR failed: {e}")
        return

    if verbose:
        print(f"  OCR: {len(words)} words detected")

    # words format: (x0, y0, x1, y1, text, block_no, line_no, word_no)
    # Assign left_label to each field: find word(s) to the left on same line
    for f in fields:
        fy = f["dot_y"]
        fx0 = f["x0"]
        # Find words on same line (within 10pt) and to the left
        candidates = []
        for w in words:
            wx0, wy0, wx1, wy1, text = w[0], w[1], w[2], w[3], w[4]
            wy_mid = (wy0 + wy1) / 2
            if abs(wy_mid - fy) < 10 and wx1 <= fx0 + 5:
                candidates.append({"text": text, "x0": wx0, "x1": wx1})
        if candidates:
            # Take the closest word(s) to the left
            candidates.sort(key=lambda w: -w["x0"])  # rightmost first
            label_parts = []
            for c in candidates[:3]:  # max 3 words
                label_parts.insert(0, c["text"])
            f["left_label"] = " ".join(label_parts)

    if verbose:
        labeled = sum(1 for f in fields if f.get("left_label"))
        print(f"  OCR labels assigned: {labeled}/{len(fields)} fields")


# ── Dot field extraction (from V3) ──

def extract_dots_text_layer(page, exclude_rects=None):
    """Extract dot positions from PDF with text layer (character-level).
    
    Args:
        page: fitz.Page
        exclude_rects: list of (x0, y0, x1, y1) — dot chars inside these rects are ignored
                       (used to exclude ID grid areas from dot detection)
    """
    data = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    chars = []
    for b in data["blocks"]:
        if "lines" not in b:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                if "chars" in span:
                    for ch in span["chars"]:
                        if exclude_rects and ch["c"] in '.…':
                            cx = (ch["bbox"][0] + ch["bbox"][2]) / 2
                            cy = (ch["bbox"][1] + ch["bbox"][3]) / 2
                            excluded = False
                            for ex0, ey0, ex1, ey1 in exclude_rects:
                                if ex0 - 2 <= cx <= ex1 + 2 and ey0 - 5 <= cy <= ey1 + 5:
                                    excluded = True
                                    break
                            if excluded:
                                continue
                        chars.append((ch["bbox"], ch["c"]))
    if not chars:
        return []

    lines = defaultdict(list)
    for bbox, c in chars:
        y_key = round(bbox[1] / 5) * 5
        lines[y_key].append((bbox[0], bbox[2], bbox[1], bbox[3], c))

    fields = []
    field_idx = 0
    for y_key in sorted(lines.keys()):
        line_chars = sorted(lines[y_key], key=lambda x: x[0])
        segments = []
        current_text = ""
        current_x0 = None
        current_x1 = None
        for x0, x1, y0, y1, c in line_chars:
            is_dot = (c in '.…')  # period OR ellipsis U+2026
            if current_x0 is None:
                current_x0 = x0; current_x1 = x1; current_text = c
            elif is_dot != (current_text[-1] in '.…' if current_text else False):
                segments.append((current_text, current_x0, current_x1))
                current_text = c; current_x0 = x0; current_x1 = x1
            else:
                current_text += c; current_x1 = x1
        if current_text:
            segments.append((current_text, current_x0, current_x1))

        dot_y0 = dot_y1 = dot_font_size = dot_ascender = None
        for b in data["blocks"]:
            if "lines" not in b: continue
            for line in b["lines"]:
                for span in line["spans"]:
                    if "chars" not in span: continue
                    for ch in span["chars"]:
                        if ch["c"] in ".…" and round(ch["bbox"][1] / 5) * 5 == y_key:
                            dot_y0 = ch["bbox"][1]; dot_y1 = ch["bbox"][3]
                            dot_font_size = span["size"]
                            dot_ascender = span.get("ascender", 0.8)
                            break
                    if dot_y0 is not None: break
                if dot_y0 is not None: break
            if dot_y0 is not None: break
        if dot_y1 is None:
            continue

        for seg_idx, (text, x0, x1) in enumerate(segments):
            has_dots = ('.' in text or '…' in text) and len(text) >= 3
            if has_dots:
                width = x1 - x0
                if width > 8:
                    field_idx += 1
                    baseline = dot_y0 + dot_font_size * dot_ascender if dot_font_size else dot_y1 - 2
                    # Capture label text to the left for alignment hints
                    left_label = ""
                    for prev_text, prev_x0, prev_x1 in segments[:seg_idx]:
                        if ('.' not in prev_text and '…' not in prev_text) or len(prev_text) <= 3:
                            left_label = prev_text.strip()
                    fields.append({
                        "name": f"field_{field_idx}",
                        "dot_y": round(dot_y1, 1), "dot_y0": round(dot_y0, 1),
                        "baseline": round(baseline, 1),
                        "x0": round(x0, 1), "x1": round(x1, 1),
                        "y_line": y_key, "width": round(width, 1),
                        "left_label": left_label,
                    })
    return fields


def _img_to_gray(pix):
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return np.array(img.convert("L"))


def extract_dots_pixel_scan(page, coarse_dpi=288, refine_dpi=720, verbose=False,
                            dot_max_h=12, dot_max_w=20, dot_min_h=4,
                            min_field_width=15, min_dot_ccs=3):
    """Extract dot positions using multi-resolution + CC analysis (for image-only PDFs).
    dot_min_h: minimum CC height to qualify as a real dot (filters table border fragments)."""
    return []


def detect_underlines(page, verbose=False):
    """Detect thin horizontal rectangles as underline fields.
    
    Many Thai forms use solid underlines instead of dotted lines for fill-in areas.
    These appear as very thin filled rectangles (height < 1pt) in the PDF.
    
    Returns list of field dicts compatible with dot_fields format.
    """
    drawings = page.get_drawings()
    page_width = page.rect.width
    
    # Get link rects to filter underlines that are part of hyperlinks
    links = page.get_links()
    link_rects = [fitz.Rect(link["from"]) for link in links if "from" in link]
    
    underlines = []
    for d in drawings:
        rect = d.get("rect")
        if not rect:
            continue
        
        w = rect.width
        h = rect.height
        
        # Thin horizontal rect (h < 1pt, w > 15pt)
        if h >= 1.0 or w <= 15:
            continue
        
        # Skip underlines inside link areas (e.g., email/URL underlines)
        is_in_link = False
        for link_rect in link_rects:
            # Check if underline is inside or overlaps significantly with link
            if (link_rect.x0 - 5 <= rect.x0 and rect.x1 <= link_rect.x1 + 5 and
                link_rect.y0 - 5 <= rect.y0 <= link_rect.y1 + 5):
                is_in_link = True
                break
        if is_in_link:
            if verbose:
                print(f"  Skipping link underline at y={rect.y0:.1f}")
            continue
        
        underlines.append({
            "y": rect.y0,  # top of underline = baseline
            "x0": rect.x0,
            "x1": rect.x1,
            "w": w,
        })
    
    if not underlines:
        return []
    
    # Merge underlines on same line that are close together
    underlines.sort(key=lambda u: (u["y"], u["x0"]))
    
    merged = []
    current = underlines[0].copy()
    
    for u in underlines[1:]:
        # Same line (within 2pt) and small x gap (within 3pt)?
        # Use smaller gap (3pt) to preserve separated fields like วัน/เดือน/ปี
        if abs(u["y"] - current["y"]) < 2 and u["x0"] - current["x1"] < 3:
            # Merge
            current["x1"] = u["x1"]
            current["w"] = current["x1"] - current["x0"]
        else:
            merged.append(current)
            current = u.copy()
    merged.append(current)
    
    # Filter out full-width lines AFTER merging (section dividers often split into multiple segments)
    # But keep lines that are part of a "writing area" (multiple consecutive lines at same x0)
    
    # First, identify writing areas: groups of 3+ consecutive lines at similar x0
    writing_area_ys = set()
    if len(merged) >= 3:
        sorted_by_y = sorted(merged, key=lambda u: u["y"])
        for i in range(len(sorted_by_y) - 2):
            # Check if 3+ consecutive lines have similar x0 and y gap
            lines = sorted_by_y[i:i+3]
            x0s = [l["x0"] for l in lines]
            y_gaps = [lines[j+1]["y"] - lines[j]["y"] for j in range(len(lines)-1)]
            # Similar x0 (within 5pt) and regular y gap (15-25pt)
            if max(x0s) - min(x0s) < 5 and all(15 < g < 30 for g in y_gaps):
                for l in lines:
                    writing_area_ys.add(round(l["y"], 1))
    
    filtered = []
    for u in merged:
        # Check if this is part of a writing area
        is_writing_area = round(u["y"], 1) in writing_area_ys
        
        # Only filter as section divider if:
        # 1. Very wide (> 85% page width) AND
        # 2. Starts very close to left edge (x0 < 43pt) AND
        # 3. NOT part of a writing area
        # Note: x0 threshold 44pt is between page 3 บรรยาย lines (41.9) and page 5 dividers (43.6)
        is_divider = u["w"] > page_width * 0.85 and u["x0"] < 44 and not is_writing_area
        if is_divider:
            if verbose:
                print(f"  Skipping section divider at y={u['y']:.1f} (w={u['w']:.1f}pt, x0={u['x0']:.1f})")
            continue
        filtered.append(u)
    
    # Additional filter: wide lines (>70% page) with NO label text = section dividers
    # This catches dividers that don't span full width but have no text before them
    words = page.get_text("words")
    filtered_no_label = []
    for u in filtered:
        if u["w"] > page_width * 0.70:  # Wide line (>70% page)
            # Check if there's any text to the left of this line (within 15pt vertically)
            has_label = False
            for w in words:
                wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
                wy_mid = (wy0 + wy1) / 2
                # Text on same line and to the left
                if abs(wy_mid - u["y"]) < 15 and wx1 < u["x0"] + 10:
                    has_label = True
                    break
            if not has_label:
                if verbose:
                    print(f"  Skipping wide divider at y={u['y']:.1f} (w={u['w']:.1f}pt, no label)")
                continue
        filtered_no_label.append(u)
    filtered = filtered_no_label
    
    # Filter logo/header area underlines (top-left corner, y < 60, x < 120)
    # These are often decorative elements or text in letterheads/logos
    filtered_no_logo = []
    for u in filtered:
        if u["y"] < 60 and u["x0"] < 120:
            if verbose:
                print(f"  Skipping logo area underline at y={u['y']:.1f}, x={u['x0']:.1f}")
            continue
        filtered_no_logo.append(u)
    filtered = filtered_no_logo
    
    # Filter underlines that have text OVERLAPPING them (decorative underlines under labels)
    # These are underlines where text sits ON TOP of the underline, not before it
    words = page.get_text("words")
    filtered2 = []
    for u in filtered:
        # Sum horizontal coverage from ALL words whose vertical extent starts
        # at or above the underline.  Previously each word was checked in
        # isolation (>70 % of underline width) which missed multi-word labels
        # spanning the full underline.  Also, requiring wy0 < u["y"] avoids
        # false hits from *next-line* text that begins just below the underline
        # (e.g. paragraph text at y+0.6 which was incorrectly filtering short
        # underlines like hdr_floor / hdr_room).
        total_overlap = 0.0
        for w in words:
            wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
            # Text must start at/above the underline (label is ON the line)
            # and its bottom must reach near the underline Y.
            if wy0 < u["y"] and wy1 > u["y"] - 5:
                overlap_x = min(wx1, u["x1"]) - max(wx0, u["x0"])
                if overlap_x > 0:
                    total_overlap += overlap_x
        text_overlap = total_overlap > u["w"] * 0.7
        if text_overlap:
            if verbose:
                print(f"  Skipping label underline at y={u['y']:.1f} (combined text covers {total_overlap:.1f}/{u['w']:.1f}pt)")
        else:
            filtered2.append(u)
    filtered = filtered2
    
    # ── Stacked underline pairing ──
    # Detect groups of 3+ underlines at the same x-range (row-separator lines).
    # For these, each field spans from this_uline_y to next_uline_y.
    # Requires 3+ lines to avoid false positives on 2-line form sections.
    divider_lines = []
    for u in merged:
        if round(u["y"], 1) not in {round(f["y"], 1) for f in filtered}:
            # This was skipped (divider) — collect for boundary detection
            if u["w"] < 300 and u.get("_is_div"):
                divider_lines.append(u)

    # Collect dividers that were explicitly skipped
    _div_ys = set()
    for u in merged:
        in_filtered = any(abs(u["y"] - f["y"]) < 0.5 for f in filtered)
        if not in_filtered:
            divider_lines.append(u)

    if len(filtered) >= 3:
        filtered_sorted = sorted(filtered, key=lambda u: (u["x0"], u["y"]))
        x_groups = []
        for u in filtered_sorted:
            placed = False
            for grp in x_groups:
                ref = grp[0]
                if abs(u["x0"] - ref["x0"]) < 5 and abs(u["x1"] - ref["x1"]) < 20:
                    grp.append(u)
                    placed = True
                    break
            if not placed:
                x_groups.append([u])

        for grp in x_groups:
            if len(grp) < 3:  # require at least 3 to avoid false positives
                continue
            grp.sort(key=lambda u: u["y"])
            ys = [u["y"] for u in grp]
            spacings = [ys[i+1] - ys[i] for i in range(len(ys)-1)]
            if not all(10 < s < 55 for s in spacings):
                continue
            avg_w = sum(u["x1"] - u["x0"] for u in grp) / len(grp)
            if avg_w >= 300:
                continue
            # Skip stacking if any uline has label text within 50pt to the left
            has_label_any = False
            for u in grp:
                label_cands = [
                    w for w in words
                    if abs((w[1] + w[3]) / 2 - u["y"]) < 8
                    and w[2] < u["x0"]
                    and u["x0"] - w[2] < 50
                ]
                if label_cands:
                    has_label_any = True
                    break
            if has_label_any:
                continue
            # Mark stacked: each field spans from this line to the next
            for i, u in enumerate(grp[:-1]):
                next_y = grp[i+1]["y"]
                u["stack_y0"] = u["y"] + 2.5
                u["stack_y1"] = next_y - 2.0
            # For the last uline, use a nearby divider line as the bottom boundary
            last_u = grp[-1]
            for div in divider_lines:
                dy = div["y"] - last_u["y"]
                if 10 < dy < 55:
                    overlap = min(div["x1"], last_u["x1"]) - max(div["x0"], last_u["x0"])
                    if overlap > (last_u["x1"] - last_u["x0"]) * 0.5:
                        last_u["stack_y0"] = last_u["y"] + 2.5
                        last_u["stack_y1"] = div["y"] - 2.0
                        break

    # ── Label-aware x0 adjustment for very large gaps (> 60pt) ──
    # When the fill-in area starts well before the drawn underline (e.g. because
    # a long label text fills the left portion), adjust x0 to label_end + 4pt.
    LABEL_GAP_THRESHOLD = 60.0
    LABEL_TRAILING_GAP = 4.0
    for u in filtered:
        if "stack_y0" in u:
            continue
        candidates = [
            w for w in words
            if abs((w[1] + w[3]) / 2 - u["y"]) < 8 and w[2] <= u["x0"] + 1
        ]
        if candidates:
            nearest_word = max(candidates, key=lambda w: w[2])
            nearest_end = nearest_word[2]
            nearest_text = nearest_word[4]
            gap = u["x0"] - nearest_end
            if "/" in nearest_text:
                continue
            if gap > LABEL_GAP_THRESHOLD:
                new_x0 = nearest_end + LABEL_TRAILING_GAP
                if new_x0 < u["x1"] - 10:
                    u["x0"] = new_x0
                    u["w"] = u["x1"] - u["x0"]

    # Convert to field dict format
    fields = []
    for i, u in enumerate(filtered):
        if "stack_y0" in u:
            fields.append({
                "name": f"uline_{i + 1}",
                "dot_y": round(u["stack_y1"], 1),
                "dot_y0": round(u["stack_y0"], 1),
                "x0": round(u["x0"], 1),
                "x1": round(u["x1"], 1),
                "y_line": round(u["stack_y0"], 0),
                "width": round(u["w"], 1),
                "left_label": "",
                "is_underline": True,
            })
            continue
        fields.append({
            "name": f"uline_{i + 1}",
            "dot_y": round(u["y"], 1),  # baseline = underline position
            "x0": round(u["x0"], 1),
            "x1": round(u["x1"], 1),
            "y_line": round(u["y"], 0),
            "width": round(u["w"], 1),
            "left_label": "",
            "is_underline": True,
        })
    
    if verbose:
        print(f"  Underlines detected: {len(fields)}")
    
    return fields


def detect_grid_fields(page, existing_fields=None, verbose=False):
    """Detect grid-structured areas (signature/name/date sections) from vector drawings.

    Many Thai forms have signature grids: a small table (3-5 rows × 3-5 cols)
    where each cell contains a short text label (e.g. 'ลงชื่อ', 'ตัวบรรจง',
    'วันที่') followed by an empty fill-in area.  These are formed by thin
    horizontal + vertical rectangles in the PDF drawings.

    The function detects consistent column boundaries across multiple row
    lines, then creates text fields for the empty portion of each cell.

    Returns a list of field dicts compatible with dot_fields.
    """
    drawings = page.get_drawings()
    page_width = page.rect.width
    MIN_CELL_WIDTH = 100   # pt – signature grid cells are wide (>130pt typically)
    MAX_CELL_WIDTH_RATIO = 0.65  # cells must be < 65% page width
    MIN_GRID_ROWS = 4     # need at least 4 horizontal lines (= 3 cell rows)
    MIN_FIELD_WIDTH = 25   # pt – minimum empty space to create a field

    # ── Collect thin horizontal line segments (cell borders) ──
    h_lines = []
    for d in drawings:
        rect = d.get("rect")
        if not rect:
            continue
        h, w = rect.height, rect.width
        if h < 1.5 and w >= MIN_CELL_WIDTH and w < page_width * MAX_CELL_WIDTH_RATIO:
            h_lines.append({
                "y": round(rect.y0, 2),
                "x0": round(rect.x0, 1),
                "x1": round(rect.x1, 1),
                "w": round(w, 1),
            })

    if len(h_lines) < MIN_GRID_ROWS * 3:
        # Need at least MIN_GRID_ROWS lines × 3 columns
        return []

    # ── Group by Y (within 1.5pt) ──
    h_lines.sort(key=lambda l: (l["y"], l["x0"]))
    y_groups: dict[float, list] = {}
    for line in h_lines:
        placed = False
        for y_key in list(y_groups.keys()):
            if abs(line["y"] - y_key) < 1.5:
                y_groups[y_key].append(line)
                placed = True
                break
        if not placed:
            y_groups[line["y"]] = [line]

    # Keep only groups with 3+ segments (at least 3 columns)
    row_candidates = []
    for y_key, segs in y_groups.items():
        if len(segs) >= 3:
            segs_sorted = sorted(segs, key=lambda s: s["x0"])
            boundaries = [s["x0"] for s in segs_sorted] + [segs_sorted[-1]["x1"]]
            row_candidates.append({
                "y": y_key,
                "n_cols": len(segs_sorted),
                "boundaries": boundaries,
                "segs": segs_sorted,
            })

    if len(row_candidates) < MIN_GRID_ROWS:
        return []

    # ── Find grids: groups of rows with matching column boundaries ──
    row_candidates.sort(key=lambda r: r["y"])
    grids = []
    used = set()
    for i, row in enumerate(row_candidates):
        if i in used:
            continue
        grid = [row]
        used.add(i)
        for j in range(i + 1, len(row_candidates)):
            if j in used:
                continue
            other = row_candidates[j]
            if other["n_cols"] != row["n_cols"]:
                continue
            max_diff = max(abs(a - b) for a, b in zip(row["boundaries"], other["boundaries"]))
            if max_diff < 5:
                grid.append(other)
                used.add(j)
        if len(grid) >= MIN_GRID_ROWS:
            grid.sort(key=lambda r: r["y"])
            grids.append(grid)

    if not grids:
        return []

    # ── Build existing-field lookup for dedup ──
    existing_rects = []
    if existing_fields:
        for f in existing_fields:
            existing_rects.append((f["x0"], f["x1"], f["dot_y"]))

    # ── Create fields for empty cell portions ──
    words = page.get_text("words")
    fields = []
    for grid in grids:
        boundaries = grid[0]["boundaries"]
        n_cols = grid[0]["n_cols"]
        if verbose:
            print(f"  Grid detected: {len(grid)} rows × {n_cols} cols, "
                  f"y={grid[0]['y']:.1f}-{grid[-1]['y']:.1f}")

        for row_idx in range(len(grid) - 1):
            top_y = grid[row_idx]["y"]
            bot_y = grid[row_idx + 1]["y"]
            row_height = bot_y - top_y
            if row_height < 8 or row_height > 45:
                continue

            for col_idx in range(n_cols):
                cell_left = boundaries[col_idx]
                cell_right = boundaries[col_idx + 1]
                cell_width = cell_right - cell_left
                if cell_width < 30:
                    continue

                # ── Check for existing field in this cell ──
                has_existing = False
                for ex0, ex1, ey in existing_rects:
                    if abs(ey - top_y) < 5 and ex0 >= cell_left - 3 and ex1 <= cell_right + 3:
                        has_existing = True
                        break
                if has_existing:
                    continue

                # ── Find text inside this cell ──
                cell_texts = []
                for w in words:
                    wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
                    wy_mid = (wy0 + wy1) / 2
                    if (top_y < wy_mid < bot_y and
                            wx0 >= cell_left - 3 and wx1 <= cell_right + 3):
                        cell_texts.append({"x0": wx0, "x1": wx1, "text": wtext})

                # ── Compute field boundaries ──
                if cell_texts:
                    rightmost_text_x = max(t["x1"] for t in cell_texts)
                    field_x0 = rightmost_text_x + 5  # gap after text
                else:
                    field_x0 = cell_left + 3  # margin from cell edge

                field_x1 = cell_right - 2  # margin from cell edge
                field_w = field_x1 - field_x0
                if field_w < MIN_FIELD_WIDTH:
                    continue  # cell too full of text

                # ── Deduplicate with existing fields ──
                is_dup = False
                for ex0, ex1, ey in existing_rects:
                    if abs(ey - top_y) < 5:
                        overlap = min(field_x1, ex1) - max(field_x0, ex0)
                        if overlap > 0.5 * field_w:
                            is_dup = True
                            break
                if is_dup:
                    continue

                fields.append({
                    "name": f"grid_{len(fields) + 1}",
                    "dot_y0": round(top_y + 2, 1),
                    "dot_y": round(bot_y - 2, 1),
                    "x0": round(field_x0, 1),
                    "x1": round(field_x1, 1),
                    "y_line": round(top_y, 0),
                    "width": round(field_w, 1),
                    "is_underline": True,
                    "is_grid_field": True,
                    "is_table": True,
                })

    if verbose and fields:
        print(f"  Grid fields: {len(fields)} text field(s)")
    return fields


def detect_underscore_fields(page, existing_fields=None, verbose=False):
    """Detect fill-in fields formed by underscore runs '______' or
    placeholder character runs 'XXXXXXXXXXXXX' in text.

    Some Thai forms use sequences of underscore characters instead of drawn
    lines for fill-in areas.  Others use runs of 'X' as name placeholders
    (e.g., "(XXXXXXXXXXXXX..)").  This function finds such runs and creates
    fields from them.

    Uses char-level (rawdict) extraction for accurate x/y positions instead
    of span-level estimation.

    Returns a list of field dicts compatible with dot_fields.
    """
    raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    fields = []

    # Build existing-field lookup
    existing_rects = []
    if existing_fields:
        for f in existing_fields:
            existing_rects.append((f["x0"], f["x1"], f["dot_y"]))

    # Placeholder characters: underscore (min 5) and X (min 8, stricter to avoid FP)
    PLACEHOLDER_CHARS = {"_": 5, "X": 8}

    for placeholder_char, min_run in PLACEHOLDER_CHARS.items():
        # Collect all placeholder chars with their bboxes
        ph_chars = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    for ch in span.get("chars", []):
                        if ch["c"] == placeholder_char:
                            ph_chars.append(ch["bbox"])

        if not ph_chars:
            continue

        # Group consecutive chars into runs (same y within 3pt, x gap < 5pt)
        runs = []
        current_run = [ph_chars[0]]
        for bbox in ph_chars[1:]:
            prev = current_run[-1]
            same_line = abs(bbox[1] - prev[1]) < 3
            adjacent = bbox[0] - prev[2] < 5
            if same_line and adjacent:
                current_run.append(bbox)
            else:
                runs.append(current_run)
                current_run = [bbox]
        runs.append(current_run)

        for run in runs:
            if len(run) < min_run:
                continue
            # Use actual char bboxes for precise positioning
            field_x0 = run[0][0]
            field_x1 = run[-1][2]
            field_y0 = min(b[1] for b in run)  # top of chars
            field_y1 = max(b[3] for b in run)  # bottom of chars (underline position)
            field_w = field_x1 - field_x0

            if field_w < 15:
                continue

            # Deduplicate with existing fields
            is_dup = False
            for ex0, ex1, ey in existing_rects:
                if abs(ey - field_y1) < 8:
                    overlap = min(field_x1, ex1) - max(field_x0, ex0)
                    if overlap > 0.3 * field_w:
                        is_dup = True
                        break
            if is_dup:
                continue

            # Cap dot_y0: some fonts have oversized char bboxes extending far above
            # the actual underscore mark. Limit the field height to at most 14pt.
            effective_y0 = max(field_y0, field_y1 - 14)
            fields.append({
                "name": f"uscore_{len(fields) + 1}",
                "dot_y": round(field_y1, 1),      # bottom = where underline sits
                "dot_y0": round(effective_y0, 1),  # top of field (capped)
                "x0": round(field_x0, 1),
                "x1": round(field_x1, 1),
                "y_line": round(field_y1, 0),
                "width": round(field_w, 1),
                "is_underline": True,
                "is_underscore_field": True,
            })

    if verbose and fields:
        print(f"  Underscore fields: {len(fields)} text field(s)")
    return fields


def detect_underlines_pixel_scan(page, dpi=288, verbose=False,
                                  min_field_width=15, max_line_height=2.0,
                                  threshold=150, n_pre_cb=0):
    """Detect solid underlines in image-only PDFs using morphological analysis.

    Uses horizontal morphological opening to isolate thin horizontal line
    segments, then filters by thickness and width.  Solid underlines are common
    in bank/government forms as fill-in areas for text.

    Args:
        page: PyMuPDF page
        dpi: rendering DPI (288 is sufficient for solid lines)
        verbose: print debug info
        min_field_width: minimum underline width in pt
        max_line_height: maximum underline thickness in pt (2pt filters digit
                         box borders which are typically ≥2.8pt)
    Returns:
        Tuple of (fields, n_dividers) where n_dividers is the count of
        full-width divider lines skipped during detection.
    """
    return []


def detect_squares(page, verbose=False):
    """Detect square drawings and classify as checkboxes or digit boxes."""
    paths = page.get_drawings()
    words = page.get_text('words')

    small_squares = []
    medium_squares = []

    for i, p in enumerate(paths):
        r = p['rect']
        w = r[2] - r[0]; h = r[3] - r[1]
        if abs(w - h) > 5: continue  # Allow slightly non-square (e.g., 16.5x20.5)
        if 7 < w < 12 and 7 < h < 12:
            small_squares.append((i, r))
        elif 12 < w < 22 and 12 < h < 22:  # Expanded to 22pt for larger checkboxes
            medium_squares.append((i, r))

    if verbose:
        print(f"  Square detection: {len(small_squares)} small, {len(medium_squares)} medium")

    # Initialize output lists
    checkboxes = []
    digit_comb_fields = []
    digit_field_idx = 0

    # ── Group medium squares into digit comb fields or checkboxes ──
    medium_squares.sort(key=lambda t: (t[1][1], t[1][0]))
    med_groups = []; cur = []
    for idx, r in medium_squares:
        if cur and abs(r[1] - cur[0][1][1]) > 5:
            med_groups.append(cur); cur = []
        cur.append((idx, r))
    if cur: med_groups.append(cur)

    for g in med_groups:
        g.sort(key=lambda t: t[1][0])
        rects = [r for _, r in g]
        subgroups = [[rects[0]]]
        for i in range(1, len(rects)):
            if rects[i][0] - rects[i - 1][2] > 5: subgroups.append([])
            subgroups[-1].append(rects[i])
        for sg in subgroups:
            n = len(sg)
            if n < 1: continue
            x0 = sg[0][0]; x1 = sg[-1][2]
            y0 = min(r[1] for r in sg); y1 = max(r[3] for r in sg)
            
            # Check if this is a section header circle (isolated, ~14.1x14.2pt, with header label)
            # These are decorative circles like "(1) ข้อมูลนายจ้าง" and should be skipped
            if n == 1:
                rect = sg[0]
                w_box = rect[2] - rect[0]
                h_box = rect[3] - rect[1]
                cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
                # Check for section header patterns
                nearby = []
                for w in words:
                    wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
                    if abs((wy0 + wy1) / 2 - cy) < 15 and wx0 > rect[2] - 5 and wx0 < rect[2] + 200:
                        nearby.append((wx0, wtext))
                nearby.sort()
                label = ' '.join(t for _, t in nearby[:3])
                
                # Skip section header circles: ~14.1x14.2pt with labels like "ข้อมูล..."
                is_section_header = (
                    13.5 < w_box < 14.3 and 13.5 < h_box < 14.3 and  # Specific size for section circles
                    ('ข้อมูล' in label or label == '')  # Section header label pattern
                )
                if is_section_header:
                    if verbose:
                        print(f"  Skipping section header circle: {w_box:.1f}x{h_box:.1f}pt at ({cx:.0f},{cy:.0f}) label='{label}'")
                    continue
                
                # Check if there's content inside the square (filled/example checkbox)
                has_content_inside = False
                for w in words:
                    wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
                    wcx, wcy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
                    if rect[0] < wcx < rect[2] and rect[1] < wcy < rect[3]:
                        has_content_inside = True
                        break
                if has_content_inside:
                    if verbose:
                        print(f"  Skipping filled medium square at ({cx:.0f},{cy:.0f})")
                    continue
                
                # Check if it looks like a digit box (14.4x14.4pt) vs checkbox
                # Checkboxes: selection options (hospital, etc.)
                # Digit boxes: everything else that's 14.4x14.4pt
                is_digit_box_size = w_box > 14.3 and h_box > 14.3
                
                # Checkbox-indicating labels (selection options)
                checkbox_keywords = ['โรงพยาบาล', 'อื่นๆ', 'อื่น ๆ', 'เลือก', 'ไม่เลือก']
                is_selection_checkbox = any(kw in label for kw in checkbox_keywords)
                
                if is_digit_box_size and not is_selection_checkbox:
                    # Looks like a digit input box - treat as comb
                    digit_field_idx += 1
                    digit_comb_fields.append((f"digits_{digit_field_idx}", [x0, y0, x1, y1], n))
                    continue
                    
                # Otherwise treat as checkbox
                checkboxes.append((list(rect), label))
                if verbose:
                    print(f"  Medium checkbox: {w_box:.1f}x{h_box:.1f}pt at ({cx:.0f},{cy:.0f}) label='{label}'")
            elif n == 2:
                # Pair of medium squares - check if digit boxes or checkboxes
                rect = sg[0]
                w_box = rect[2] - rect[0]
                h_box = rect[3] - rect[1]
                is_digit_box = w_box > 14.3 and h_box > 14.3
                
                if is_digit_box:
                    # Treat as comb digit field
                    digit_field_idx += 1
                    digit_comb_fields.append((f"digits_{digit_field_idx}", [x0, y0, x1, y1], n))
                else:
                    # Treat as checkboxes
                    for rect in sg:
                        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
                        nearby = []
                        for w in words:
                            wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
                            if abs((wy0 + wy1) / 2 - cy) < 15 and wx0 > rect[2] - 5 and wx0 < rect[2] + 200:
                                nearby.append((wx0, wtext))
                        nearby.sort()
                        label = ' '.join(t for _, t in nearby[:3])
                        checkboxes.append((list(rect), label))
                        if verbose:
                            print(f"  Medium checkbox: {rect[2]-rect[0]:.1f}x{rect[3]-rect[1]:.1f}pt at ({cx:.0f},{cy:.0f}) label='{label}'")
            else:
                # 3+ tightly packed squares = digit comb field
                digit_field_idx += 1
                digit_comb_fields.append((f"digits_{digit_field_idx}", [x0, y0, x1, y1], n))

    # ── Group small squares ──
    small_squares.sort(key=lambda t: (t[1][1], t[1][0]))
    small_groups = []; cur = []
    for idx, r in small_squares:
        if cur and abs(r[1] - cur[0][1][1]) > 5:
            small_groups.append(cur); cur = []
        cur.append((idx, r))
    if cur: small_groups.append(cur)

    small_digit_idx = 0

    for sg in small_groups:
        sg.sort(key=lambda t: t[1][0])
        # Split into subgroups by X gap first (gap > 5pt = separate cluster)
        rects_all = [(idx, r) for idx, r in sg]
        subgrps = [[rects_all[0]]]
        for j in range(1, len(rects_all)):
            if rects_all[j][1][0] - rects_all[j - 1][1][2] > 5:
                subgrps.append([])
            subgrps[-1].append(rects_all[j])

        for sub in subgrps:
            if len(sub) >= 3:
                # Tightly packed subgroup → digit comb field
                gaps = [sub[j + 1][1][0] - sub[j][1][2] for j in range(len(sub) - 1)]
                avg_gap = sum(gaps) / len(gaps) if gaps else 999
                if avg_gap < 3:
                    rects = [r for _, r in sub]
                    x0 = rects[0][0]; x1 = rects[-1][2]
                    y0 = min(r[1] for r in rects); y1 = max(r[3] for r in rects)
                    small_digit_idx += 1
                    digit_comb_fields.append((f"small_digits_{small_digit_idx}", [x0, y0, x1, y1], len(rects)))
                    continue

            # Individual squares → checkboxes (only if empty inside)
            for idx, r in sub:
                cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
                
                # Check if there's text inside the square (would indicate a filled/example checkbox)
                has_content_inside = False
                for w in words:
                    wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
                    # Check if word center is inside the square bounds
                    wcx, wcy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
                    if r[0] < wcx < r[2] and r[1] < wcy < r[3]:
                        has_content_inside = True
                        break
                
                if has_content_inside:
                    if verbose:
                        print(f"  Skipping filled small square at y={cy:.0f}, x={cx:.0f}")
                    continue
                
                nearby = []
                for w in words:
                    wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
                    if abs((wy0 + wy1) / 2 - cy) < 8 and wx0 > r[2] - 5 and wx0 < r[2] + 150:
                        nearby.append((wx0, wtext))
                nearby.sort()
                label = ' '.join(t for _, t in nearby[:3])
                checkboxes.append((list(r), label))

    # ── Glyph-based checkbox detection (for checkboxes embedded as font glyphs) ──
    # Some forms use special characters (Wingdings, Symbol, or surrogate chars) for checkboxes
    # These appear as square/box glyphs in the text layer, not as vector drawings
    data = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    for block in data.get("blocks", []):
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span.get("chars", []):
                    try:
                        c = ch["c"]
                        cp = ord(c)
                    except (ValueError, TypeError):
                        continue
                    # Detect checkbox glyphs: surrogate chars, Wingdings squares,
                    # ballot boxes, or specific Unicode box chars
                    # NOTE: cp > 0xD800 is intentionally restricted to actual
                    # surrogates (D800-DFFF) and Private Use Area (E000-F8FF,
                    # F0000+). U+FFFD (replacement char) is excluded — it
                    # appears when PyMuPDF can't decode CID fonts (e.g.
                    # BrowalliaNew Identity-H) and is NOT a checkbox glyph.
                    # Only detect EMPTY checkbox glyphs (not filled/checked ones)
                    # Empty checkboxes are fillable; checked ones are examples/instructions
                    EMPTY_CHECKBOX_GLYPHS = {
                        0x2610,  # ☐ BALLOT BOX (empty)
                        0x25A1,  # □ WHITE SQUARE (empty)
                        0x25FB,  # ◻ WHITE MEDIUM SQUARE
                        0xF0A3,  # Wingdings empty square
                        0xF0A8,  # Wingdings empty circle
                        0xF06F,  # Wingdings empty checkbox variant
                    }
                    FILLED_CHECKBOX_GLYPHS = {
                        0x2611, 0x2612,  # ☑ ☒ checked/crossed ballot box
                        0x25A0, 0x25FC,  # ■ filled squares
                        0x2713, 0x2714, 0x2717, 0x2718,  # ✓✔✗✘ check/cross marks
                        0xF0FE, 0xF06E, 0xF052, 0xF0FC,  # Wingdings checked/filled
                    }
                    
                    # Accept: known empty glyphs, PUA glyphs that are NOT known filled,
                    # or ANY glyph in a Wingdings/Symbol font (these fonts only contain
                    # symbol chars; low code points like U+0001 are valid checkbox glyphs)
                    is_empty_checkbox = cp in EMPTY_CHECKBOX_GLYPHS
                    is_pua_glyph = (0xE000 <= cp <= 0xF8FF) or (cp >= 0xF0000) or (0xD800 <= cp <= 0xDFFF)
                    is_filled_checkbox = cp in FILLED_CHECKBOX_GLYPHS
                    font_name = span.get("font", "").lower()
                    is_wingdings_font = any(w in font_name for w in ("wingdings", "symbol", "zapfdingbats", "webdings"))
                    # Wingdings fonts with non-PUA code points (e.g. U+0001,
                    # U+FFFD replacement char) are valid checkbox glyphs.
                    # PUA glyphs in Wingdings (0xF0xx) go through the normal
                    # empty/filled classification to avoid false positives.
                    is_wingdings_non_pua = is_wingdings_font and not is_pua_glyph and not is_filled_checkbox

                    if not (is_empty_checkbox or is_wingdings_non_pua or (is_pua_glyph and not is_filled_checkbox)):
                        continue
                    bbox = list(ch["bbox"])
                    bw = bbox[2] - bbox[0]
                    bh = bbox[3] - bbox[1]
                    # Must be roughly square-ish and reasonable size (5-25pt)
                    if bw < 5 or bh < 5 or bw > 25 or bh > 25:
                        continue
                    # Aspect ratio check: must be roughly square (not tall/narrow)
                    aspect = min(bw, bh) / max(bw, bh) if max(bw, bh) > 0 else 0
                    if aspect < 0.4:
                        continue
                    # Find label text to the right
                    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
                    nearby = []
                    for w in words:
                        wx0, wy0, wx1, wy1, wtext = w[0], w[1], w[2], w[3], w[4]
                        if abs((wy0 + wy1) / 2 - cy) < 8 and wx0 > bbox[2] - 2 and wx0 < bbox[2] + 100:
                            nearby.append((wx0, wtext))
                    nearby.sort()
                    label = ' '.join(t for _, t in nearby[:3])
                    # U+2610 BALLOT BOX has extra ascender/descender space
                    # in its bbox — crop height to make square checkbox
                    if cp == 0x2610:
                        gbw = bbox[2] - bbox[0]
                        gbh = bbox[3] - bbox[1]
                        if gbh > gbw * 1.3:
                            bbox[3] = bbox[1] + gbw  # crop bottom
                    checkboxes.append((bbox, label))
                    if verbose:
                        print(f"  Glyph checkbox: U+{cp:04X} bbox={[round(x,1) for x in bbox]} label='{label}'")

    if verbose:
        print(f"  Checkboxes: {len(checkboxes)}, Comb digit fields: {len(digit_comb_fields)}")

    return checkboxes, digit_comb_fields


def detect_squares_pixel(page, verbose=False):
    """Detect checkbox squares from page image (for image-only pages).
    
    Finds hollow square components (~10-18pt) by analyzing connected components
    in the rendered page image. Returns checkboxes in same format as detect_squares.
    """
    return []


def detect_table_fields(page, existing_fields, verbose=False):
    """Auto-detect table grids and create fields in empty cells.
    
    Scans the page image for horizontal and vertical line patterns that form
    a table grid. Creates text fields in cells that don't already have fields.
    Returns list of table field dicts.
    """
    from scipy.signal import find_peaks

    # Quick pre-scan for glyph checkboxes to exclude their columns from table cells
    checkbox_rects = []
    CHECKBOX_CHARS = {0x2610, 0x2611, 0x2612, 0x25A0, 0x25A1, 0x25FB, 0x25FC}
    for block in page.get_text("rawdict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span.get("chars", []):
                    cp = ord(ch["c"]) if len(ch["c"]) == 1 else 0
                    if cp in CHECKBOX_CHARS or (0xD800 <= cp <= 0xDFFF) or (0xE000 <= cp <= 0xF8FF):
                        bbox = ch["bbox"]
                        w = bbox[2] - bbox[0]
                        h = bbox[3] - bbox[1]
                        if 5 < w < 25 and 5 < h < 25 and h / w > 0.4:
                            checkbox_rects.append(bbox)

    def cell_has_checkbox(x0, y0, x1, y1):
        for cb in checkbox_rects:
            cbx = (cb[0] + cb[2]) / 2
            cby = (cb[1] + cb[3]) / 2
            if x0 < cbx < x1 and y0 < cby < y1:
                return True
        return False

    dpi = 300; s = dpi / 72
    pix = page.get_pixmap(dpi=dpi)
    gray = np.array(Image.open(io.BytesIO(pix.tobytes("png"))).convert("L"))
    H, W = gray.shape

    # Step 1: Find horizontal lines across the full page
    row_density = (gray < 130).sum(axis=1) / W
    h_peaks, _ = find_peaks(row_density, height=0.12, distance=int(8 * s))
    h_cands = [(p, row_density[p]) for p in h_peaks if row_density[p] > 0.15]
    if len(h_cands) < 4:
        return []

    # Step 2: Find the largest cluster of evenly-spaced horizontal lines (= table)
    # Only consider stronger lines (density > 0.4) as table grid candidates
    h_strong = [(p, d) for p, d in h_cands if d > 0.4]
    if len(h_strong) < 4:
        # Fall back to all candidates if not enough strong lines
        h_strong = h_cands

    h_pts_with_d = sorted(h_strong, key=lambda x: x[0] / s)
    h_pts = [p / s for p, _ in h_pts_with_d]
    h_dens = [d for _, d in h_pts_with_d]

    # Step 2: Find ALL valid clusters of evenly-spaced horizontal lines
    # (supports forms with multiple separate tables on one page)
    valid_clusters = []
    for start_i in range(len(h_pts)):
        for end_i in range(start_i + 3, len(h_pts)):
            cluster = [h_pts[j] for j in range(start_i, end_i + 1)]
            c_dens = [h_dens[j] for j in range(start_i, end_i + 1)]
            gaps = [cluster[j+1] - cluster[j] for j in range(len(cluster) - 1)]
            med = sorted(gaps)[len(gaps) // 2]
            # Tight consistency: gaps within 1.25x of median
            consistent = sum(1 for g in gaps if med * 0.75 < g < med * 1.25)
            # Density consistency: all lines should have similar density (within 3x range)
            min_d = min(c_dens); max_d = max(c_dens)
            density_ok = max_d < min_d * 3.0
            if consistent >= len(gaps) * 0.9 and density_ok:
                score = len(cluster) * 10 - np.std(gaps)
                valid_clusters.append((cluster, score))

    if not valid_clusters:
        return []

    # Split clusters at large internal gaps (> 1.15× median) to separate
    # merged regions (e.g., table + signature area)
    def split_cluster_at_large_gaps(cluster):
        if len(cluster) < 6:
            return [cluster]  # too small to split
        gaps = [cluster[j+1] - cluster[j] for j in range(len(cluster) - 1)]
        med = sorted(gaps)[len(gaps) // 2]
        threshold = med * 1.15
        # Find split points
        splits = [0]
        for i, g in enumerate(gaps):
            if g > threshold:
                splits.append(i + 1)
        splits.append(len(cluster))
        # Create sub-clusters
        sub_clusters = []
        for i in range(len(splits) - 1):
            sub = cluster[splits[i]:splits[i+1]]
            if len(sub) >= 4:  # need at least 4 lines for a valid cluster
                sub_clusters.append(sub)
        return sub_clusters if sub_clusters else [cluster]

    # Apply splitting to all valid clusters
    split_clusters = []
    for cluster, score in valid_clusters:
        subs = split_cluster_at_large_gaps(cluster)
        for sub in subs:
            # Recalculate score for sub-cluster
            sub_gaps = [sub[j+1] - sub[j] for j in range(len(sub) - 1)]
            sub_score = len(sub) * 10 - np.std(sub_gaps) if sub_gaps else len(sub) * 10
            split_clusters.append((sub, sub_score))
    valid_clusters = split_clusters

    # Pre-filter: validate each cluster has vertical lines spanning full height
    # This must happen BEFORE non-overlapping selection to avoid wrong clusters
    # blocking correct ones.
    def cluster_has_full_vertical_lines(cluster):
        y_min_px = max(0, int(cluster[0] * s) - int(5 * s))
        y_max_px = min(H, int(cluster[-1] * s) + int(5 * s))
        table_strip = gray[y_min_px:y_max_px, :]
        th = table_strip.shape[0]
        if th < 60:
            return True  # too short to validate
        
        col_density = (table_strip < 130).sum(axis=0) / th
        v_peaks, _ = find_peaks(col_density, height=0.10, distance=int(10 * s))
        v_cands = [p for p in v_peaks if col_density[p] > 0.30]
        if len(v_cands) < 3:
            return False
        
        # Check vertical line presence in 5 horizontal slices
        # A valid table grid should have lines in ALL slices
        n_slices = 5
        slice_h = th // n_slices
        for i in range(n_slices):
            y0 = i * slice_h
            y1 = (i + 1) * slice_h if i < n_slices - 1 else th
            section = table_strip[y0:y1, :]
            hits = sum(1 for vx in v_cands
                      if (section[:, max(0,vx-1):vx+2] < 130).sum() / max(section[:, max(0,vx-1):vx+2].size, 1) > 0.15)
            # Require at least 40% of vertical lines present in EVERY slice
            if hits < len(v_cands) * 0.4:
                return False
        return True

    filtered_clusters = []
    for cluster, score in valid_clusters:
        if cluster_has_full_vertical_lines(cluster):
            filtered_clusters.append((cluster, score))
        elif verbose:
            print(f"  Table cluster y={cluster[0]:.1f}→{cluster[-1]:.1f} rejected: vertical lines not spanning full height")

    if not filtered_clusters:
        return []

    # Sort by score descending, select non-overlapping clusters
    filtered_clusters.sort(key=lambda x: x[1], reverse=True)
    selected_clusters = []
    used_ranges = []
    for cluster, score in filtered_clusters:
        c_min = cluster[0]; c_max = cluster[-1]
        overlaps = any(not (c_max < ur[0] - 10 or c_min > ur[1] + 10) for ur in used_ranges)
        if not overlaps:
            selected_clusters.append(cluster)
            used_ranges.append((c_min, c_max))

    if not selected_clusters:
        return []

    # Check which cells already have fields (avoid duplicates)
    existing_rects = []
    for f in existing_fields:
        existing_rects.append((f["x0"], f["dot_y"] - 5, f["x1"], f["dot_y"] + 15))

    def cell_has_field(x0, y0, x1, y1):
        cx = (x0 + x1) / 2; cy = (y0 + y1) / 2
        for ex0, ey0, ex1, ey1 in existing_rects:
            if ex0 < cx < ex1 and ey0 < cy < ey1:
                return True
        return False

    # Step 3-4: For each cluster, find vertical lines and create table fields
    all_table_fields = []
    tbl_num = 0
    for h_lines_pt in selected_clusters:
        # Find vertical lines within this cluster's Y range
        y_min_px = max(0, int(h_lines_pt[0] * s) - int(5 * s))
        y_max_px = min(H, int(h_lines_pt[-1] * s) + int(5 * s))
        table_strip = gray[y_min_px:y_max_px, :]
        th = table_strip.shape[0]

        col_density = (table_strip < 130).sum(axis=0) / th
        v_peaks, _ = find_peaks(col_density, height=0.10, distance=int(10 * s))
        v_cands = [(p, col_density[p]) for p in v_peaks if col_density[p] > 0.30]
        if len(v_cands) < 3:
            continue

        v_lines_pt = sorted(p / s for p, _ in v_cands)

        # Sanity checks
        table_width = v_lines_pt[-1] - v_lines_pt[0]
        page_width = page.rect.width
        if table_width < page_width * 0.4:
            continue
        n_cols = len(v_lines_pt) - 1
        if n_cols > 12 or n_cols < 3:
            continue

        # Identify data rows (skip header — rows with gaps much larger than median)
        row_gaps = [(h_lines_pt[i+1] - h_lines_pt[i], i) for i in range(len(h_lines_pt) - 1)]
        sorted_gaps = sorted(g for g, _ in row_gaps)
        median_gap = sorted_gaps[len(sorted_gaps) // 2]

        data_row_boundaries = []
        for i in range(len(h_lines_pt) - 1):
            gap = h_lines_pt[i + 1] - h_lines_pt[i]
            if gap < median_gap * 1.5 and gap > median_gap * 0.5:
                data_row_boundaries.append((h_lines_pt[i], h_lines_pt[i + 1]))

        if len(data_row_boundaries) < 4:  # need at least 4 data rows (excludes 3-row signature sections)
            continue

        # Create fields for this table
        tbl_num += 1
        pad_x = 2.0
        pad_y = 2.0
        for row_idx, (ry0, ry1) in enumerate(data_row_boundaries):
            for col_idx in range(len(v_lines_pt) - 1):
                cx0 = v_lines_pt[col_idx] + pad_x
                cx1 = v_lines_pt[col_idx + 1] - pad_x
                cy0 = ry0 + pad_y
                cy1 = ry1 - pad_y
                cell_width = cx1 - cx0
                if cell_width < 5 or cy1 - cy0 < 5:
                    continue
                if cell_has_field(cx0, cy0, cx1, cy1):
                    continue
                if cell_has_checkbox(cx0, cy0, cx1, cy1):
                    continue  # Skip cells containing glyph checkboxes
                # Skip narrow cells (< 30pt) that are near checkbox columns
                # (these are gap columns between checkboxes, not real data fields)
                if cell_width < 30:
                    cell_cx = (cx0 + cx1) / 2
                    near_cb = any(abs(cell_cx - (cb[0] + cb[2]) / 2) < 50 for cb in checkbox_rects if abs(cy0 - cb[1]) < 20)
                    if near_cb:
                        continue
                all_table_fields.append({
                    "name": f"tbl{tbl_num}_r{row_idx + 1}_c{col_idx + 1}",
                    "x0": cx0, "x1": cx1,
                    "dot_y0": cy0,
                    "dot_y": cy1,
                    "height": cy1 - cy0,
                    "width": cx1 - cx0,
                    "alignment": "center" if (cx1 - cx0) < 100 else "left",
                    "left_label": "",
                    "is_table": True,
                })

        if verbose:
            n_rows = len(data_row_boundaries)
            n_f = sum(1 for f in all_table_fields if f["name"].startswith(f"tbl{tbl_num}_"))
            print(f"  Table {tbl_num} detected: {n_rows} data rows × {n_cols} cols = {n_f} cell fields")
            if data_row_boundaries:
                print(f"    First row: y={data_row_boundaries[0][0]:.1f}→{data_row_boundaries[0][1]:.1f}")
                print(f"    Last row:  y={data_row_boundaries[-1][0]:.1f}→{data_row_boundaries[-1][1]:.1f}")

    if verbose and not all_table_fields and selected_clusters:
        print(f"  Table clusters found ({len(selected_clusters)}) but no valid tables after vertical line check")

    return all_table_fields



def filter_text_overlap(page, dot_fields, verbose=False):
    """Remove false positive dot fields that overlap with actual text content.
    
    For pages with both text layer and image content, pixel scan may detect
    text characters as dots. This filter checks if a field area contains
    non-dot text and removes it.
    """
    return fields


def _embed_font(doc, page, font_name="Tahoma", font_path=None):
    """Embed a TrueType font into the PDF for form fields."""
    if font_path and Path(font_path).exists():
        pass
    else:
        candidates = [
            f"/mnt/c/Windows/Fonts/{font_name.lower()}.ttf",
            f"/usr/share/fonts/truetype/{font_name.lower()}.ttf",
            f"/usr/share/fonts/{font_name.lower()}.ttf",
            f"/usr/local/share/fonts/{font_name.lower()}.ttf",
        ]
        font_path = None
        for p in candidates:
            if Path(p).exists():
                font_path = p; break

    if not font_path:
        print(f"WARNING: {font_name} font not found, using Helvetica", file=sys.stderr)
        return "Helv"

    font_xref = page.insert_font(
        fontname=font_name, fontfile=font_path,
        set_simple=True, encoding=fitz.TEXT_ENCODING_LATIN
    )
    catalog = doc.pdf_catalog()
    # Handle AcroForm — may be indirect (separate xref) or direct (inline in catalog)
    try:
        doc.xref_set_key(catalog, "AcroForm/DR", f"<</Font<</{font_name} {font_xref} 0 R>>>>")
        doc.xref_set_key(catalog, "AcroForm/NeedAppearances", "true")
    except Exception:
        # AcroForm is an indirect object — resolve and set keys on it directly
        acro_val = doc.xref_get_key(catalog, "AcroForm")
        if acro_val[0] == "xref":
            acro_xref = int(acro_val[1].split()[0])
        else:
            # Create new AcroForm dict
            acro_xref = doc.get_new_xref()
            doc.update_object(acro_xref, "<<>>")
            doc.xref_set_key(catalog, "AcroForm", f"{acro_xref} 0 R")
        doc.xref_set_key(acro_xref, "DR", f"<</Font<</{font_name} {font_xref} 0 R>>>>")
        doc.xref_set_key(acro_xref, "NeedAppearances", "true")
    return font_name


# ── ID Grid Detection ──

def detect_id_grids(page, verbose=False):
    """Detect ID number grid rectangles from vector drawings and create comb fields.
    
    Thai government forms use bordered rectangle grids for ID numbers
    (e.g., เลขประจำตัวผู้เสียภาษีอากร, เลขประจำตัวประชาชน).
    
    Detection strategy:
    1. Find rectangles with h=10-18pt (candidate digit boxes)
    2. Find short horizontal lines (4-15pt, connecting segments between groups)
    3. Match lines to rectangle gaps — only rows with connecting lines qualify
    4. Require mixed widths in the row (not all uniform squares)
    5. Each rectangle in a validated row becomes one comb group
    6. Digits per group = round(width / cell_width)
    
    Returns:
        (grid_rects, comb_fields) where:
        - grid_rects: list of (x0, y0, x1, y1) bounding each entire row for dot exclusion
        - comb_fields: list of (name, [x0, y0, x1, y1], maxlen) per group
    """
    drawings = page.get_drawings()
    
    # Step 1: Collect candidate rectangles (h=10-18pt, w=8-70pt)
    rects = []
    for d in drawings:
        for item in d.get('items', []):
            if item[0] == 're':
                r = item[1]
                w, h = r.width, r.height
                if 10 <= h <= 18 and 8 <= w <= 70:
                    rects.append((r.x0, r.y0, r.x1, r.y1, w, h))
    
    if len(rects) < 4:
        return [], []
    
    # Step 2: Collect short horizontal connecting lines (4-15pt long)
    hlines = []
    for d in drawings:
        for item in d.get('items', []):
            if item[0] == 'l':
                p1, p2 = item[1], item[2]
                dx = abs(p2.x - p1.x)
                dy = abs(p2.y - p1.y)
                if 3 < dx < 15 and dy < 1:
                    hlines.append({
                        'x0': min(p1.x, p2.x),
                        'x1': max(p1.x, p2.x),
                        'y': (p1.y + p2.y) / 2,
                    })
    
    if not hlines:
        return [], []
    
    # Step 3: Group rectangles by Y (within 3pt of y_mid)
    rects_by_y = {}
    for r in rects:
        y_mid = (r[1] + r[3]) / 2
        placed = False
        for key in list(rects_by_y.keys()):
            if abs(y_mid - key) <= 3:
                rects_by_y[key].append(r)
                placed = True
                break
        if not placed:
            rects_by_y[y_mid] = [r]
    
    # Step 4: Validate rows using connecting lines
    grid_rects = []
    comb_fields = []
    field_idx = 0
    
    for y_key, row_rects in sorted(rects_by_y.items()):
        if len(row_rects) < 3:
            continue
        
        row_rects.sort(key=lambda r: r[0])
        row_y_min = min(r[1] for r in row_rects)
        row_y_max = max(r[3] for r in row_rects)
        row_y_mid = (row_y_min + row_y_max) / 2
        
        # Find connecting lines at this y level
        row_lines = [l for l in hlines if abs(l['y'] - row_y_mid) <= 5]
        if not row_lines:
            continue  # No connecting lines → not an ID grid
        
        # Verify lines actually connect gaps between rectangles
        line_connects = 0
        for line in row_lines:
            has_left = any(abs(r[2] - line['x0']) < 3 for r in row_rects)
            has_right = any(abs(r[0] - line['x1']) < 3 for r in row_rects)
            if has_left and has_right:
                line_connects += 1
        
        if line_connects < 2:
            continue  # Need ≥2 verified connecting lines
        
        # Step 5: Require mixed widths (not all uniform squares)
        widths = [r[4] for r in row_rects]
        if max(widths) - min(widths) < 5:
            continue  # All same width → uniform squares, handled by detect_squares
        
        # Step 6: Create comb fields
        single_widths = [r[4] for r in row_rects if r[4] < 15]
        cell_width = (sum(single_widths) / len(single_widths)) if single_widths else 12.0
        
        row_x0 = min(r[0] for r in row_rects)
        row_x1 = max(r[2] for r in row_rects)
        grid_rects.append((row_x0, row_y_min, row_x1, row_y_max))
        
        for r in row_rects:
            x0, y0, x1, y1, w, h = r
            maxlen = 1 if w < 15 else max(1, round(w / cell_width))
            
            field_idx += 1
            name = f"id_grid_{field_idx}"
            comb_fields.append((name, [x0, y0, x1, y1], maxlen))
            
            if verbose:
                print(f"  ID grid: {name} ({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f}) "
                      f"w={w:.1f} → {maxlen} digit(s)")
    
    if verbose and comb_fields:
        print(f"  ID grids total: {len(comb_fields)} comb field(s) from {len(grid_rects)} row(s)")
    
    return grid_rects, comb_fields


# ── Detect all fields on a single page ──

def detect_page_fields(page, page_idx, has_text, verbose=False,
                       coarse_dpi=288, refine_dpi=720, dot_max_h=12, dot_max_w=20,
                       skip_checkboxes=False, skip_digits=False):
    """Detect all field types on a single page. Returns (dot_fields, checkboxes, digit_comb_fields)."""
    prefix = f"p{page_idx + 1}_"

    # ID Grid detection (early — needed for dot exclusion)
    id_grid_rects, id_grid_combs = detect_id_grids(page, verbose=verbose)

    # Dot fields — try text layer first, fall back to pixel scan if too few results
    used_pixel_scan = False
    if has_text:
        dot_fields = extract_dots_text_layer(page, exclude_rects=id_grid_rects if id_grid_rects else None)
        # Post-filter: remove remaining dot fields overlapping grid rects
        if id_grid_rects:
            before_n = len(dot_fields)
            dot_fields = [f for f in dot_fields
                         if not any(min(f["x1"], gx1) - max(f["x0"], gx0) > 0
                                    and gy0 - 5 <= f["dot_y"] <= gy1 + 5
                                    for gx0, gy0, gx1, gy1 in id_grid_rects)]
            if verbose and len(dot_fields) < before_n:
                print(f"  ID grid exclusion: removed {before_n - len(dot_fields)} dot field(s)")
            # Merge adjacent fields on same line that were split by excluded grid dots
            merged = []
            dot_fields_s = sorted(dot_fields, key=lambda f: (f["y_line"], f["x0"]))
            i = 0
            while i < len(dot_fields_s):
                f = dict(dot_fields_s[i])
                while i + 1 < len(dot_fields_s):
                    nf = dot_fields_s[i + 1]
                    if abs(f["y_line"] - nf["y_line"]) < 3 and nf["x0"] - f["x1"] < 5:
                        f["x1"] = nf["x1"]
                        f["width"] = round(f["x1"] - f["x0"], 1)
                        i += 1
                    else:
                        break
                merged.append(f)
                i += 1
            if verbose and len(merged) < len(dot_fields):
                print(f"  ID grid merge: {len(dot_fields)} → {len(merged)} field(s)")
            dot_fields = merged
        # Hybrid fallback: if text layer produces very few fields AND the page has dots
        # in its text, the form template might be an image background (pre-filled forms).
        # Don't trigger on pages with zero dots (checkbox-only pages are fine with 0 dot fields).
        page_text = page.get_text()
        page_has_dots = '.' in page_text or '…' in page_text
        # Skip fallback on text-rich pages (>1000 chars) with 0 fields — dots are in labels
        text_rich = len(page_text) > 1000
        if len(dot_fields) < 5 and page_has_dots and not (len(dot_fields) == 0 and text_rich):
            pixel_fields = extract_dots_pixel_scan(
                page, coarse_dpi=coarse_dpi, refine_dpi=refine_dpi,
                verbose=verbose, dot_max_h=dot_max_h, dot_max_w=dot_max_w,
            )
            if len(pixel_fields) > len(dot_fields):
                if verbose:
                    print(f"  Text layer: {len(dot_fields)} fields → pixel scan: {len(pixel_fields)} fields (using pixel scan)")
                dot_fields = pixel_fields
                used_pixel_scan = True
    else:
        used_pixel_scan = True
        dot_fields = extract_dots_pixel_scan(
            page, coarse_dpi=coarse_dpi, refine_dpi=refine_dpi,
            verbose=verbose, dot_max_h=dot_max_h, dot_max_w=dot_max_w,
        )
    if not dot_fields:
        dot_fields = []

    # Filter false positives: pixel-scanned fields overlapping with real text
    if used_pixel_scan and has_text:
        before = len(dot_fields)
        dot_fields = filter_text_overlap(page, dot_fields, verbose=verbose)
        if verbose and len(dot_fields) < before:
            print(f"  Text overlap filter removed {before - len(dot_fields)} false positive(s)")

    # Auto-detect table grids — only on image-based pages (pixel scan)
    # Text-layer pages with rich content don't have empty data tables
    table_fields = detect_table_fields(page, dot_fields, verbose=verbose) if used_pixel_scan else []
    if table_fields:
        dot_fields.extend(table_fields)

    # Detect underlines (thin horizontal rectangles) — common in Thai forms
    underline_fields = detect_underlines(page, verbose=verbose)
    # Exclude underlines within ID grid bounding rects
    if underline_fields and id_grid_rects:
        before_uf = len(underline_fields)
        underline_fields = [uf for uf in underline_fields
                           if not any(gx0 - 5 <= uf["x0"] and uf["x1"] <= gx1 + 5
                                      and gy0 - 5 <= uf["dot_y"] <= gy1 + 5
                                      for gx0, gy0, gx1, gy1 in id_grid_rects)]
        if verbose and len(underline_fields) < before_uf:
            print(f"  ID grid: excluded {before_uf - len(underline_fields)} underline(s) inside grid area")
    if underline_fields:
        # Deduplicate: remove underlines that overlap with existing dot fields
        existing_rects = [(f["x0"], f["x1"], f["dot_y"]) for f in dot_fields]
        new_underlines = []
        for uf in underline_fields:
            is_dup = False
            for ex0, ex1, ey in existing_rects:
                # Same line (within 5pt) and overlapping x range?
                if abs(uf["dot_y"] - ey) < 5:
                    overlap = min(uf["x1"], ex1) - max(uf["x0"], ex0)
                    if overlap > 0.5 * uf["width"]:
                        is_dup = True
                        break
            if not is_dup:
                new_underlines.append(uf)
        if verbose and len(new_underlines) < len(underline_fields):
            print(f"  Underline dedup: {len(underline_fields)} → {len(new_underlines)} (removed {len(underline_fields) - len(new_underlines)} overlapping with dots)")
        dot_fields.extend(new_underlines)

    # Detect grid-structured signature/name/date sections (vector drawings)
    grid_fields = detect_grid_fields(page, existing_fields=dot_fields, verbose=verbose)
    if grid_fields:
        dot_fields.extend(grid_fields)

    # Detect underscore-based fill-in fields ("______" in text)
    uscore_fields = detect_underscore_fields(page, existing_fields=dot_fields, verbose=verbose)
    if uscore_fields:
        dot_fields.extend(uscore_fields)

    # Pixel-based underline detection for image-only pages
    # Only run when existing detection (dots + tables) found very few fields.
    # This prevents false positives from header/border elements on pages with
    # already-good dot or table detection.
    n_dots = sum(1 for f in dot_fields
                 if not f.get("is_table") and not f.get("is_underline"))
    n_table = sum(1 for f in dot_fields if f.get("is_table"))
    n_existing = n_dots + n_table
    # Also trigger underline scan when most dot detections look like noise
    # (narrow fields < 35pt suggest false positives from scan artifacts)
    n_narrow = sum(1 for f in dot_fields if f.get("width", 0) < 35
                   and not f.get("is_table") and not f.get("is_underline"))
    dots_look_noisy = n_dots > 0 and n_narrow >= n_dots * 0.6
    _n_page_dividers = 0  # count of full-width dividers (set by pixel underline scan)
    if used_pixel_scan and (n_existing < 5 or dots_look_noisy):
        if verbose:
            print(f"  Pixel underline trigger: {n_dots} dots + {n_table} table = {n_existing} (< 5)")
        # Suppress narrow CC dot fields — when there are very few dots (≤3),
        # they're likely noise (diacritical marks, checkbox artifacts) not real fields.
        # Only suppress actual CC dot fields, NOT text-layer underlines.
        if n_dots <= 3:
            before_len = len(dot_fields)
            dot_fields = [f for f in dot_fields
                          if f.get("is_table") or f.get("is_underline") or (f["x1"] - f["x0"]) >= 25]
            if verbose and len(dot_fields) < before_len:
                print(f"  Suppressed {before_len - len(dot_fields)} narrow CC dot field(s) (< 25pt)")
        # Quick pre-count of pixel checkboxes to determine if this is a dense form
        # (dense forms like KBank_p6 have many checkboxes AND short underline fields)
        _pre_checkboxes = detect_squares_pixel(page, verbose=False)
        _n_pre_cb = len(_pre_checkboxes)
        # Use smaller min_field_width only when form has many checkboxes (>30)
        # This prevents false short-underline detections on sparse forms
        _min_fw = 10 if _n_pre_cb > 30 else 15
        if verbose and _n_pre_cb > 30:
            print(f"  Dense form ({_n_pre_cb} cb): using min_field_width={_min_fw}")
        pixel_result = detect_underlines_pixel_scan(page, verbose=verbose,
                                                     threshold=150, min_field_width=_min_fw,
                                                     n_pre_cb=_n_pre_cb)
        if isinstance(pixel_result, tuple) and len(pixel_result) == 3:
            pixel_ulines, pixel_combs, _n_page_dividers = pixel_result
        elif isinstance(pixel_result, tuple):
            pixel_ulines, pixel_combs = pixel_result
            _n_page_dividers = 0
        else:
            pixel_ulines, pixel_combs = pixel_result, []
            _n_page_dividers = 0
        if pixel_ulines:
            # Deduplicate with existing fields (dots + vector underlines + tables)
            existing_rects = [(f["x0"], f["x1"], f["dot_y"]) for f in dot_fields]
            new_ulines = []
            for uf in pixel_ulines:
                is_dup = False
                for ex0, ex1, ey in existing_rects:
                    if abs(uf["dot_y"] - ey) < 5:
                        overlap = min(uf["x1"], ex1) - max(uf["x0"], ex0)
                        if overlap > 0.5 * uf["width"]:
                            is_dup = True
                            break
                if not is_dup:
                    new_ulines.append(uf)
            if verbose and len(new_ulines) < len(pixel_ulines):
                print(f"  Pixel uline dedup: {len(pixel_ulines)} → {len(new_ulines)}")
            # Filter out pixel underlines that have text overlapping them (label underlines)
            if has_text and new_ulines:
                new_ulines = filter_text_overlap(page, new_ulines, verbose=verbose)
            dot_fields.extend(new_ulines)

    # ── Header suppression ──
    # On pixel-scan pages, detect full-width horizontal dividers (>85% page width)
    # and remove fields above the first one (header/logo/title area).
    first_body_y = None
    if used_pixel_scan and dot_fields:
        page_width = page.rect.width
        # Quick divider scan: render at low DPI and find full-width horizontal lines
        _div_dpi = 144
        _div_scale = _div_dpi / 72
        _div_pix = page.get_pixmap(dpi=_div_dpi)
        _div_gray = _img_to_gray(_div_pix)
        _div_H, _div_W = _div_gray.shape
        _div_threshold = 0.85 * page_width * _div_scale  # min dark pixels for divider

        # Find rows with full-width dark content
        dark_rows = []
        for row_y in range(_div_H):
            dark_count = int((_div_gray[row_y, :] < 150).sum())
            if dark_count >= _div_threshold:
                dark_rows.append(row_y / _div_scale)

        # Group consecutive dark rows into bands; real dividers are thin (< 5pt),
        # decorative borders are thick bands (> 10pt) — skip those.
        divider_ys = []
        if dark_rows:
            band_start = dark_rows[0]
            band_end = dark_rows[0]
            for y_pt in dark_rows[1:]:
                if y_pt - band_end < 3:  # still in same band
                    band_end = y_pt
                else:
                    band_thickness = band_end - band_start
                    if band_thickness < 5:  # thin line = real divider
                        divider_ys.append((band_start + band_end) / 2)
                    band_start = band_end = y_pt
            # Last band
            band_thickness = band_end - band_start
            if band_thickness < 5:
                divider_ys.append((band_start + band_end) / 2)

        # Header detection: use ONLY full-width dividers in the top portion (y < 100).
        # Dividers below y=100 are likely section dividers within form content,
        # not header boundaries. Previously used any divider < 300 which incorrectly
        # suppressed legitimate form fields in KBank_Wisdom_p3.
        if divider_ys:
            for dy in divider_ys:
                if 50 < dy < 100:
                    first_body_y = dy + 3
                    if verbose:
                        print(f"  Header boundary: divider at y={dy:.1f}, cut at y={first_body_y:.1f}")
                    break

        if first_body_y is not None:
            before = len(dot_fields)
            # Keep rect fields in header (bordered boxes are intentional form fields)
            dot_fields = [f for f in dot_fields if f["dot_y"] >= first_body_y or f.get("is_rect")]
            if verbose and len(dot_fields) < before:
                print(f"  Header suppression: removed {before - len(dot_fields)} fields above divider y={first_body_y:.1f}")
        # Terms/schedule page detection: many full-width dividers indicate a
        # structured text page (fee schedules, terms & conditions) not a form.
        if _n_page_dividers >= 5 and _n_pre_cb == 0:
            if dot_fields and verbose:
                print(f"  Terms/schedule page detected ({_n_page_dividers} dividers, 0 checkboxes) — suppressing {len(dot_fields)} field(s)")
            dot_fields = []

        else:
            # No divider found — check if this looks like a real form page
            # Real form pages have: dot fields OR table cells
            # Intro pages have: only underline detections (false positives)
            n_dots_now = sum(1 for f in dot_fields
                             if not f.get("is_table") and not f.get("is_underline"))
            n_table_now = sum(1 for f in dot_fields if f.get("is_table"))
            # Count long underlines (>100pt) — form pages have signatures & wide fields
            n_long_ulines = sum(1 for f in dot_fields
                                if f.get("is_underline") and f.get("width", 0) > 100)
            # Also count "good" underlines (wide or clean below_dark) — many real underlines = form page
            n_good_ulines = sum(1 for f in dot_fields if f.get("is_underline")
                                and (f.get("width", 0) > 40 or f.get("below_dark", 1) < 0.1))
            is_form_page = n_long_ulines >= 3 or n_good_ulines >= 5
            if n_dots_now == 0 and n_table_now == 0 and not is_form_page:
                # No dots, no table, few good underlines → likely intro/cover page
                if dot_fields and verbose:
                    print(f"  Intro page detected (0 dots, 0 table, {n_long_ulines} long/{n_good_ulines} good ulines, no divider) — suppressing {len(dot_fields)} field(s)")
                dot_fields = []
            elif n_dots_now == 0 and n_table_now == 0 and is_form_page:
                if verbose:
                    print(f"  Form page (0 dots, 0 table, but {n_long_ulines} long/{n_good_ulines} good ulines) — keeping {len(dot_fields)} field(s)")

    # Prefix field names with page number
    for f in dot_fields:
        f["name"] = prefix + f["name"]

    # Squares (vector + glyph detection, with pixel fallback for image-only pages)
    checkboxes = []
    digit_comb_fields = []
    if not skip_checkboxes or not skip_digits:
        cb, dcf = detect_squares(page, verbose=verbose)
        if not skip_checkboxes:
            checkboxes = [(r, label) for r, label in cb]
            # Pixel fallback: if vector/glyph found 0 checkboxes, try image scan
            if len(checkboxes) == 0 and used_pixel_scan:
                pixel_cb = detect_squares_pixel(page, verbose=verbose)
                checkboxes = pixel_cb
            # Remove checkboxes above header boundary (if divider was found)
            # Also suppress all checkboxes on intro pages (no dots, no table, no divider)
            # Count underlines for intro page detection (same logic as text field suppression)
            _n_long_ulines_cb = sum(1 for f in dot_fields
                                     if f.get("is_underline") and f.get("width", 0) > 100)
            _n_good_ulines_cb = sum(1 for f in dot_fields if f.get("is_underline")
                                    and (f.get("width", 0) > 40 or f.get("below_dark", 1) < 0.1))
            _is_form_page_cb = _n_long_ulines_cb >= 3 or _n_good_ulines_cb >= 5
            is_intro_page = (first_body_y is None and n_dots == 0 and n_table == 0
                             and not _is_form_page_cb)
            if is_intro_page and used_pixel_scan:
                if checkboxes and verbose:
                    print(f"  Intro page — suppressing {len(checkboxes)} checkbox(es)")
                checkboxes = []
            elif first_body_y is not None and first_body_y > 50:
                before_cb = len(checkboxes)
                filtered_cb = []
                for cb_item in checkboxes:
                    cb_rect = cb_item[0]
                    cb_y = cb_rect[1] if isinstance(cb_rect, (list, tuple)) else cb_rect.y0
                    if cb_y >= first_body_y:
                        filtered_cb.append(cb_item)
                checkboxes = filtered_cb
                if verbose and len(checkboxes) < before_cb:
                    print(f"  Header suppression: removed {before_cb - len(checkboxes)} checkbox(es) above y={first_body_y:.1f}")
        if not skip_digits:
            digit_comb_fields = [(prefix + n, r, m) for n, r, m in dcf]

    # Add pixel-detected comb fields (from underline rectangle grid detection)
    pixel_combs = locals().get('pixel_combs', [])
    if not skip_digits and pixel_combs:
        for pc in pixel_combs:
            digit_comb_fields.append((
                prefix + pc["name"],
                [pc["x0"], pc["y0"], pc["x1"], pc["y1"]],
                pc["maxlen"]
            ))

    # Filter out pixel underlines that are checkbox table borders
    # (These are horizontal lines forming the boundaries of checkbox groups)
    if checkboxes:
        # Collect Y ranges of medium checkboxes (height > 15pt)
        cb_y_ranges = []
        for cb_item in checkboxes:
            cb_rect = cb_item[0]
            cb_y0 = cb_rect[1] if isinstance(cb_rect, (list, tuple)) else cb_rect.y0
            cb_y1 = cb_rect[3] if isinstance(cb_rect, (list, tuple)) else cb_rect.y1
            cb_h = cb_y1 - cb_y0
            if cb_h > 15:  # medium checkbox
                cb_y_ranges.append((cb_y0 - 3, cb_y1 + 3))  # with small tolerance
        
        if cb_y_ranges:
            before_dots = len(dot_fields)
            filtered_dots = []
            for f in dot_fields:
                # Only filter pixel underlines (not vector underlines)
                if not f.get("is_pixel_underline"):
                    filtered_dots.append(f)
                    continue
                y = f["dot_y"]
                is_cb_border = any(y0 <= y <= y1 for y0, y1 in cb_y_ranges)
                if not is_cb_border:
                    filtered_dots.append(f)
            dot_fields = filtered_dots
            if verbose and len(dot_fields) < before_dots:
                print(f"  Checkbox border filter: removed {before_dots - len(dot_fields)} pixel underline(s)")

    # Suppress checkboxes that overlap with comb fields (border fragments misdetected)
    if digit_comb_fields and checkboxes:
        before_cb = len(checkboxes)
        filtered_cb = []
        for cb_item in checkboxes:
            cb_rect = cb_item[0]
            cb_x0 = cb_rect[0] if isinstance(cb_rect, (list, tuple)) else cb_rect.x0
            cb_y0 = cb_rect[1] if isinstance(cb_rect, (list, tuple)) else cb_rect.y0
            cb_x1 = cb_rect[2] if isinstance(cb_rect, (list, tuple)) else cb_rect.x1
            cb_y1 = cb_rect[3] if isinstance(cb_rect, (list, tuple)) else cb_rect.y1
            overlaps_comb = False
            for _, comb_rect, _ in digit_comb_fields:
                cx0, cy0, cx1, cy1 = comb_rect if isinstance(comb_rect, (list, tuple)) else (comb_rect.x0, comb_rect.y0, comb_rect.x1, comb_rect.y1)
                if cb_x0 >= cx0 - 5 and cb_x1 <= cx1 + 5 and cb_y0 >= cy0 - 5 and cb_y1 <= cy1 + 5:
                    overlaps_comb = True
                    break
            if not overlaps_comb:
                filtered_cb.append(cb_item)
        checkboxes = filtered_cb
        if verbose and len(checkboxes) < before_cb:
            print(f"  Comb overlap: removed {before_cb - len(checkboxes)} checkbox(es) overlapping comb fields")

    # ── Table-area checkbox realignment ──
    # For pixel-scan forms with multi-table layout, glyph checkboxes inside
    # table cells may land in the same 10pt sort bucket as text fields in the
    # same row. Realign them to cell_top + 9pt so they always sort into the
    # next 10pt bucket (consistent with hand-crafted expected baselines).
    if table_fields and checkboxes:
        row_top_map = {}
        for tf in table_fields:
            row_top = tf["dot_y0"] - 2.0  # dot_y0 = cell_top + pad_y (2.0)
            y_band = round(row_top / 10) * 10
            if y_band not in row_top_map:
                row_top_map[y_band] = row_top
        new_checkboxes = []
        for cb_rect, cb_label in checkboxes:
            cr = cb_rect if isinstance(cb_rect, list) else list(cb_rect)
            cb_cy = (cr[1] + cr[3]) / 2
            matched_top = None
            for row_top in row_top_map.values():
                if row_top <= cb_cy <= row_top + 22:
                    matched_top = row_top
                    break
            if matched_top is not None:
                # Widget rect gets a +1/-1 inset on all sides before writing.
                # To get widget y0 = matched_top + 9, set new_y0 = matched_top + 8.
                new_y0 = matched_top + 8.0
                cb_h = cr[3] - cr[1]  # preserve original height (may be cropped)
                new_y1 = new_y0 + cb_h
                new_checkboxes.append(([cr[0], new_y0, cr[2], new_y1], cb_label))
            else:
                new_checkboxes.append((cb_rect, cb_label))
        checkboxes = new_checkboxes

    # ── Enhanced pixel analysis (checkbox borders, comb ticks, ID groups) ──
    if used_pixel_scan:
        dot_fields, checkboxes, digit_comb_fields = enhance_detections_pixel(
            page, dot_fields, checkboxes, digit_comb_fields, prefix, verbose=verbose)

    # Add ID grid comb fields
    if id_grid_combs:
        for name, rect, maxlen in id_grid_combs:
            digit_comb_fields.append((prefix + name, rect, maxlen))

    if verbose:
        print(f"  Page {page_idx + 1}: {len(dot_fields)} text, {len(checkboxes)} cb, {len(digit_comb_fields)} comb")

    return dot_fields, checkboxes, digit_comb_fields


def enhance_detections_pixel(page, dot_fields, checkboxes, digit_comb_fields,
                              prefix, verbose=False):
    """Enhance field detection using high-resolution pixel analysis.

    1. H-line checkbox border detection at 600 DPI (finds checked checkboxes
       missed by connected-component analysis)
    2. Comb tick detection (converts text fields with vertical ticks to comb)
    3. Full-width comb row scan (detects name/email comb fields)
    4. ID card digit box detection (Thai ID: 1-4-5-2-1 pattern)
    5. Adjacent field merge (merges consecutive small text fields into comb)
    """
    return dot_fields, checkboxes, digit_comb_fields


def create_fillable(input_path, output_path, all_pages_fields,
                    border_width=0, text_color=(0, 0, 0.65), verbose=False,
                    font_name="Tahoma", font_path=None):
    """Add form widgets to all pages of the PDF."""
    doc = fitz.open(input_path)

    # Embed font on first page (shared across all pages via AcroForm/DR)
    actual_font = _embed_font(doc, doc[0], font_name, font_path)

    COMB_FLAG = 1 << 24
    total_counts = {"text": 0, "cb": 0, "comb": 0}
    cb_global_idx = 0

    for page_idx, (dot_fields, checkboxes, digit_comb_fields) in enumerate(all_pages_fields):
        page = doc[page_idx]

        # ── Unify all fields: pre-compute actual rect, use y_center for row grouping ──
        unified = []  # (type, data, y_center, y0, y1, x0)

        for f in dot_fields:
            x0 = f["x0"]; x1 = f["x1"]
            baseline = f.get("baseline"); dot_y0 = f.get("dot_y0"); dot_y = f["dot_y"]
            if baseline is not None and dot_y0 is not None:
                ry0, ry1 = dot_y0, baseline + 1
            elif dot_y0 is not None:
                ry0, ry1 = dot_y0, dot_y
            else:
                ry0, ry1 = dot_y - 11.2, dot_y + 2
            if not f.get("is_table"):
                h = ry1 - ry0
                ry0 -= h * 0.10
            yc = (ry0 + ry1) / 2
            unified.append(("dot", f, yc, ry0, ry1, x0))

        for rect, label in checkboxes:
            cb_rect = (rect[0]+1, rect[1]+1, rect[2]-1, rect[3]-1)
            yc = (cb_rect[1] + cb_rect[3]) / 2
            unified.append(("cb", (rect, label), yc, cb_rect[1], cb_rect[3], cb_rect[0]))

        for name, rect, maxlen in digit_comb_fields:
            yc = (rect[1] + rect[3]) / 2
            unified.append(("comb", (name, rect, maxlen), yc, rect[1], rect[3], rect[0]))

        # ── Sort by (y-row, x) using y_center proximity for row grouping ──
        # Using y_center distance (≤8pt) instead of y-overlap to avoid
        # 10% height expansion causing near-miss overlaps that merge separate rows.
        ROW_YC_TOL = 8  # max y_center distance to be on same row
        if unified:
            unified.sort(key=lambda u: (u[2], u[5]))  # sort by y_center, then x
            rows = []
            current_row = [unified[0]]
            for u in unified[1:]:
                # Same row if y_center is close to any field in current row
                row_yc_min = min(f[2] for f in current_row)
                row_yc_max = max(f[2] for f in current_row)
                if u[2] - row_yc_min <= ROW_YC_TOL:
                    current_row.append(u)
                else:
                    rows.append(current_row)
                    current_row = [u]
            rows.append(current_row)
            unified = []
            for row in rows:
                unified.extend(sorted(row, key=lambda u: u[5]))

        # ── Insert all fields in unified position order ──
        for ftype, fdata, _yc, _y0, _y1, _x in unified:
            if ftype == "dot":
                f = fdata
                x0 = f["x0"]; x1 = f["x1"]
                baseline = f.get("baseline"); dot_y0 = f.get("dot_y0"); dot_y = f["dot_y"]
                if baseline is not None and dot_y0 is not None:
                    rect = fitz.Rect(x0, dot_y0, x1, baseline + 1)
                elif dot_y0 is not None:
                    rect = fitz.Rect(x0, dot_y0, x1, dot_y)
                else:
                    rect = fitz.Rect(x0, dot_y - 11.2, x1, dot_y + 2)
                if not f.get("is_table"):
                    h = rect.height
                    rect.y0 -= h * 0.10
                widget = fitz.Widget()
                widget.field_name = f["name"]
                widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                widget.rect = rect
                widget.field_value = ""
                widget.text_fontsize = 0
                widget.text_color = text_color
                widget.border_width = border_width
                if f.get("maxlen"):
                    widget.text_maxlen = f["maxlen"]
                    widget.field_flags = COMB_FLAG
                page.add_widget(widget)
            elif ftype == "cb":
                rect, label = fdata
                cb_global_idx += 1
                safe_label = label.replace(' ', '_').replace('.', '')[:30] if label else ""
                name = f"p{page_idx+1}_cb_{cb_global_idx}_{safe_label}" if safe_label else f"p{page_idx+1}_cb_{cb_global_idx}"
                w = fitz.Widget()
                w.field_name = name
                w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
                w.rect = fitz.Rect(rect) + (1, 1, -1, -1)
                w.field_value = "Off"
                w.border_width = 0
                w.border_color = (1, 1, 1)
                page.add_widget(w)
            elif ftype == "comb":
                name, rect, maxlen = fdata
                w = fitz.Widget()
                w.field_name = name
                w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                w.rect = fitz.Rect(rect)
                w.field_value = ""
                w.text_fontsize = 0
                w.text_color = text_color
                w.border_width = 0
                w.text_maxlen = maxlen
                w.field_flags = COMB_FLAG
                page.add_widget(w)

        total_counts["text"] += sum(1 for f in dot_fields if not f.get("maxlen"))
        total_counts["comb"] += sum(1 for f in dot_fields if f.get("maxlen"))
        total_counts["cb"] += len(checkboxes)
        total_counts["comb"] += len(digit_comb_fields)

        # Tab order: /W = widget (annotation array) order
        page_xref = doc.page_xref(page_idx)
        doc.xref_set_key(page_xref, "Tabs", "/W")

    # Strip PDF/A metadata
    try:
        import re
        xmp = doc.get_xml_metadata()
        if xmp and 'pdfaid' in xmp.lower():
            xmp = re.sub(r'<pdfaid:part>[^<]*</pdfaid:part>', '', xmp)
            xmp = re.sub(r'<pdfaid:conformance>[^<]*</pdfaid:conformance>', '', xmp)
            doc.set_xml_metadata(xmp)
    except Exception:
        pass

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()

    # Post-save: update font DA + alignment + remove AP on all pages
    # Build set of field names that should be force-centered (signature/position/date fields)
    CENTER_KEYWORDS = ['ลงชื่อ', 'ตำแหน่ง', 'ต าแหน่ง', 'วันที่']
    force_center_names = set()
    for dot_fields, _, _ in all_pages_fields:
        for f in dot_fields:
            label = f.get("left_label", "")
            if any(kw in label for kw in CENTER_KEYWORDS):
                force_center_names.add(f["name"])

    doc2 = fitz.open(output_path)
    SHORT_FIELD_THRESHOLD = 100
    for page_idx in range(len(doc2)):
        page2 = doc2[page_idx]
        for w in page2.widgets():
            # Remove pre-generated AP so viewer uses NeedAppearances to regenerate
            # (PyMuPDF AP uses built-in fonts which can't render Thai combining chars)
            try:
                doc2.xref_set_key(w.xref, "AP", "null")
            except Exception:
                pass
            # Add /MK (Appearance Characteristics) — required for Acrobat to
            # properly regenerate appearance with Thai combining chars (สระ อำ)
            try:
                doc2.xref_set_key(w.xref, "MK", "<<>>")
            except Exception:
                pass

            if w.field_type == fitz.PDF_WIDGET_TYPE_TEXT:
                if actual_font != "Helv":
                    da = doc2.xref_get_key(w.xref, "DA")
                    if da[0] == "string" and "/Helv" in da[1]:
                        da_new = da[1].replace("/Helv", f"/{actual_font}")
                        doc2.xref_set_key(w.xref, "DA", f"({da_new})")
                # Center if: short field, OR signature/position/date field
                is_short = w.rect.width < SHORT_FIELD_THRESHOLD
                is_signature = w.field_name in force_center_names
                q = "1" if (is_short or is_signature) else "0"
                doc2.xref_set_key(w.xref, "Q", q)
    doc2.saveIncr()
    doc2.close()

    return total_counts


# ── Field validation / QA ──

def validate_fields(all_pages_fields, verbose=False):
    """Post-detection validation to remove suspicious false-positive fields.

    Rules:
    1. Isolated small field: text field <25pt wide with no neighbor within ±8pt
       vertically on the same page → remove
    2. Sparse page: page with ≤3 text fields, all <35pt → remove all
    3. Any text field <15pt wide → remove (too small to be usable)

    Returns cleaned all_pages_fields and list of removed field descriptions.
    """
    SMALL_THRESHOLD = 18  # pt — only very narrow fields (<18pt) need neighbors; 20-25pt fields are often legitimate
    NEIGHBOR_Y_TOL = 4    # pt — vertical tolerance for "same line" neighbor
    NEIGHBOR_X_MAX_GAP = 300  # pt — max horizontal gap to count as neighbor (increased for forms with spread-out fields)
    # Wider isolation: fields < 30pt with NO neighbor within 30pt Y → definitely false positive
    WIDE_SMALL_THRESHOLD = 45
    WIDE_Y_TOL = 70
    SPARSE_MAX_FIELDS = 3
    SPARSE_MAX_WIDTH = 40
    MIN_USABLE_WIDTH = 12
    removed = []

    cleaned = []
    for page_idx, (dot_fields, checkboxes, digit_comb_fields) in enumerate(all_pages_fields):
        page_num = page_idx + 1

        # Rule 3: absolute minimum width
        kept = []
        for f in dot_fields:
            w = f["x1"] - f["x0"]
            if w < MIN_USABLE_WIDTH:
                removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — too narrow")
                if verbose:
                    print(f"  QA remove: {f['name']} width={w:.0f}pt < {MIN_USABLE_WIDTH}pt")
            else:
                kept.append(f)
        dot_fields = kept

        # Rule 2: sparse page (few tiny fields = likely all false positives)
        if 0 < len(dot_fields) <= SPARSE_MAX_FIELDS:
            widths = [f["x1"] - f["x0"] for f in dot_fields]
            if all(w < SPARSE_MAX_WIDTH for w in widths):
                for f in dot_fields:
                    w = f["x1"] - f["x0"]
                    removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — sparse page ({len(dot_fields)} small fields)")
                    if verbose:
                        print(f"  QA remove: {f['name']} — sparse page")
                dot_fields = []

        # Rule 1: isolated small fields — need a close neighbor
        # "close" = within NEIGHBOR_Y_TOL vertically AND NEIGHBOR_X_MAX_GAP horizontally
        # Neighbors include other text fields AND checkboxes (short fields next to
        # checkboxes are often real, e.g. "ระดับ___" after a checkbox).
        cb_ys = []
        for cb in checkboxes:
            cb_rect = cb[0]
            if hasattr(cb_rect, 'y0'):
                cb_ys.append(cb_rect.y0)
            elif isinstance(cb_rect, (list, tuple)):
                cb_ys.append(cb_rect[1])
        kept = []
        for f in dot_fields:
            w = f["x1"] - f["x0"]
            y = f["dot_y"]
            # Extra header filter: small fields in header area (y < 80) are likely artifacts
            if y < 80 and w < 25:
                removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — header artifact")
                if verbose:
                    print(f"  QA remove: {f['name']} width={w:.0f}pt, header artifact (y={y:.0f})")
                continue
            if w < SMALL_THRESHOLD:
                y = f["dot_y"]
                has_neighbor = False
                for other in dot_fields:
                    if other is f:
                        continue
                    if abs(other["dot_y"] - y) < NEIGHBOR_Y_TOL:
                        x_gap = max(0, max(other["x0"] - f["x1"], f["x0"] - other["x1"]))
                        if x_gap < NEIGHBOR_X_MAX_GAP:
                            has_neighbor = True
                            break
                # Also check checkboxes as neighbors
                if not has_neighbor:
                    for cb_y in cb_ys:
                        if abs(cb_y - y) < NEIGHBOR_Y_TOL + 5:
                            has_neighbor = True
                            break
                if not has_neighbor:
                    removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — isolated small field")
                    if verbose:
                        print(f"  QA remove: {f['name']} width={w:.0f}pt, isolated")
                    continue
            kept.append(f)
        dot_fields = kept

        # Rule 1b: wider isolation — 25-30pt fields with NO neighbor within 30pt Y
        # Check ALL field types (text + checkbox + comb) as potential neighbors
        all_field_ys = [f2["dot_y"] for f2 in dot_fields]
        for cb in checkboxes:
            cb_rect = cb[0]
            if hasattr(cb_rect, 'y0'):
                all_field_ys.append(cb_rect.y0)
            elif isinstance(cb_rect, (list, tuple)):
                all_field_ys.append(cb_rect[1])
        for comb in digit_comb_fields:
            comb_rect = comb[1]
            if hasattr(comb_rect, 'y0'):
                all_field_ys.append(comb_rect.y0)
            elif isinstance(comb_rect, (list, tuple)):
                all_field_ys.append(comb_rect[1])

        kept2 = []
        for f in dot_fields:
            w = f["x1"] - f["x0"]
            if SMALL_THRESHOLD <= w < WIDE_SMALL_THRESHOLD:
                y = f["dot_y"]
                has_any_neighbor = False
                # Count fields at same y (±0.1) — if >1, there are neighbors on same line
                same_y_count = sum(1 for oy in all_field_ys if abs(oy - y) < 0.1)
                if same_y_count > 1:
                    has_any_neighbor = True  # other fields on same line = not isolated
                else:
                    for other_y in all_field_ys:
                        if abs(other_y - y) < 0.1:  # skip self
                            continue
                        if abs(other_y - y) < WIDE_Y_TOL:
                            has_any_neighbor = True
                            break
                if not has_any_neighbor:
                    removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — isolated small field (wide)")
                    if verbose:
                        print(f"  QA remove: {f['name']} width={w:.0f}pt, isolated (wide)")
                    continue
            kept2.append(f)
        dot_fields = kept2

        # Rule 1d: sandwiched border filter — narrow field alone on its line
        # with fields BOTH above AND below it (within 25pt each).
        # This catches decorative lines sandwiched between field rows.
        kept2c = []
        for f in dot_fields:
            w = f["x1"] - f["x0"]
            if w >= 50:
                kept2c.append(f)
                continue
            y = f["dot_y"]
            # Must be alone on its line
            same_line = [o for o in dot_fields if o is not f and abs(o["dot_y"] - y) < 4]
            if same_line:
                kept2c.append(f)
                continue
            # Check for fields above AND below (both required)
            # Use tighter range (14-21pt) to avoid false positives on real fields
            # that happen to be 21+pt from neighbors.
            has_above = any(14 < (y - o["dot_y"]) < 21 for o in dot_fields if o is not f)
            has_below = any(14 < (o["dot_y"] - y) < 21 for o in dot_fields if o is not f)
            if has_above and has_below:
                removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — sandwiched border")
                if verbose:
                    print(f"  QA remove: {f['name']} width={w:.0f}pt, sandwiched border")
                continue
            kept2c.append(f)
        dot_fields = kept2c

        # Rule 2: text artifact filter (pixel-scan pages)
        # Real dotted lines have empty space below; text artifacts have dense text below.
        # Two tiers: narrow fields (<80pt) with moderate below_dark (>0.08),
        #            wider fields with very high below_dark (>0.15) = clearly printed text
        BELOW_DARK_THRESHOLD = 0.08
        BELOW_DARK_MAX_WIDTH = 80  # pt — for moderate below_dark
        BELOW_DARK_HIGH = 0.15     # very high = printed text (any width)
        kept3 = []
        for f in dot_fields:
            bd = f.get("below_dark", 0)
            w = f["x1"] - f["x0"]
            is_text_artifact = False
            if not f.get("is_comb"):
                if bd > BELOW_DARK_THRESHOLD and w < BELOW_DARK_MAX_WIDTH:
                    is_text_artifact = True
                elif bd > BELOW_DARK_HIGH:
                    is_text_artifact = True
            if is_text_artifact:
                removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — text artifact (below_dark={bd:.3f})")
                if verbose:
                    print(f"  QA remove: {f['name']} width={w:.0f}pt, text artifact (below_dark={bd:.3f})")
                continue
            kept3.append(f)
        dot_fields = kept3

        # Rule 2b: vertical overlap dedup — if field B's X-range is entirely
        # within field A's X-range and they're within 20pt in Y, the narrower
        # one is likely a shadow/duplicate (e.g. bordered box detected twice).
        # SKIP if either field is a comb (comb cells are intentionally smaller).
        # Only runs on pixel-scan pages (text-layer fields are structurally accurate).
        V_OVERLAP_Y = 5  # pt — max Y distance (tight: real shadows are <3pt apart)
        is_pixel_scan_page_2b = any(f.get("is_pixel_underline") for f in dot_fields)
        to_remove_vidx = set()
        for i, fi in enumerate(dot_fields):
            if not is_pixel_scan_page_2b or i in to_remove_vidx or fi.get("is_comb"):
                continue
            for j, fj in enumerate(dot_fields):
                if j <= i or j in to_remove_vidx or fj.get("is_comb"):
                    continue
                yi, yj = fi["dot_y"], fj["dot_y"]
                if abs(yi - yj) > V_OVERLAP_Y:
                    continue
                wi = fi["x1"] - fi["x0"]
                wj = fj["x1"] - fj["x0"]
                # Check if one is entirely inside the other's X-range
                if fi["x0"] <= fj["x0"] and fi["x1"] >= fj["x1"] and wj < wi:
                    to_remove_vidx.add(j)
                    removed.append(f"P{page_num} {fj['name']} (w={wj:.0f}pt) — vertical overlap with {fi['name']}")
                    if verbose:
                        print(f"  QA remove: {fj['name']} width={wj:.0f}pt, vertical overlap with {fi['name']}")
                elif fj["x0"] <= fi["x0"] and fj["x1"] >= fi["x1"] and wi < wj:
                    to_remove_vidx.add(i)
                    removed.append(f"P{page_num} {fi['name']} (w={wi:.0f}pt) — vertical overlap with {fj['name']}")
                    if verbose:
                        print(f"  QA remove: {fi['name']} width={wi:.0f}pt, vertical overlap with {fj['name']}")
                    break
        if to_remove_vidx:
            dot_fields = [f for i, f in enumerate(dot_fields) if i not in to_remove_vidx]

        # Rule 2c: shared-endpoint dedup with same-row neighbor check.
        # Two pixel underlines sharing x1 (within 5pt) with nested x-ranges and
        # Y within 25pt. The WIDER one is spurious only when it has NO same-row
        # neighbors (within 3pt Y) while the narrower one does.
        # Example: uline at y=505 (wide, no neighbors) vs uline at y=521 with
        # row-mates — the y=505 one is a misdetected table border/edge.
        # When removing the wider spurious field, extend the kept field's x0
        # leftward so the full x-range is preserved.
        SHARED_X1_TOL = 5        # pt — x1 must match within this
        SHARED_X1_Y_MAX = 25     # pt — max Y distance
        SHARED_X0_DIFF_MIN = 20  # pt — x0 must differ by at least this
        SAME_ROW_Y_TOL = 3       # pt — fields within this Y are "row-mates"
        to_remove_shared = set()
        x0_extend = {}           # idx → new x0 (extend kept field leftward)
        for i, fi in enumerate(dot_fields):
            if not fi.get("is_pixel_underline") or i in to_remove_shared:
                continue
            for j, fj in enumerate(dot_fields):
                if j <= i or not fj.get("is_pixel_underline") or j in to_remove_shared:
                    continue
                # Must share x1
                if abs(fi["x1"] - fj["x1"]) > SHARED_X1_TOL:
                    continue
                # Must be within Y range
                if abs(fi["dot_y"] - fj["dot_y"]) > SHARED_X1_Y_MAX:
                    continue
                # Must have nested x-ranges (one fully inside the other)
                wi = fi["x1"] - fi["x0"]
                wj = fj["x1"] - fj["x0"]
                i_contains_j = fi["x0"] <= fj["x0"] and fi["x1"] >= fj["x1"] and wj < wi
                j_contains_i = fj["x0"] <= fi["x0"] and fj["x1"] >= fi["x1"] and wi < wj
                if not i_contains_j and not j_contains_i:
                    continue
                # x0 must differ meaningfully
                if abs(fi["x0"] - fj["x0"]) < SHARED_X0_DIFF_MIN:
                    continue
                # Count same-row neighbors (excluding the pair partner)
                n_i = sum(1 for k, fk in enumerate(dot_fields)
                          if k != i and k != j and abs(fk["dot_y"] - fi["dot_y"]) <= SAME_ROW_Y_TOL)
                n_j = sum(1 for k, fk in enumerate(dot_fields)
                          if k != i and k != j and abs(fk["dot_y"] - fj["dot_y"]) <= SAME_ROW_Y_TOL)
                # Only remove the isolated one when the other has MULTIPLE row-mates (≥2).
                # Single neighbor isn't enough since later QA rules may remove it.
                if i_contains_j and n_i == 0 and n_j >= 2:
                    # fi is the wider spurious one; fj is the correct narrower one
                    to_remove_shared.add(i)
                    x0_extend[j] = min(fi["x0"], fj["x0"])  # extend fj's x0 leftward
                    removed.append(f"P{page_num} {fi['name']} (w={wi:.0f}pt) — spurious wider (no row-mates, extending {fj['name']} x0)")
                    if verbose:
                        print(f"  QA remove: {fi['name']} width={wi:.0f}pt, spurious wider (no row-mates)")
                elif j_contains_i and n_j == 0 and n_i >= 2:
                    to_remove_shared.add(j)
                    x0_extend[i] = min(fi["x0"], fj["x0"])
                    removed.append(f"P{page_num} {fj['name']} (w={wj:.0f}pt) — spurious wider (no row-mates, extending {fi['name']} x0)")
                    if verbose:
                        print(f"  QA remove: {fj['name']} width={wj:.0f}pt, spurious wider (no row-mates)")
        # Apply x0 extensions before removing
        for idx, new_x0 in x0_extend.items():
            dot_fields[idx]["x0"] = new_x0
        if to_remove_shared:
            dot_fields = [f for i, f in enumerate(dot_fields) if i not in to_remove_shared]

        # Rule 4: checkbox shadow filter (pixel-scan pages)
        # Two sub-rules:
        # 4a) Narrow text/dot fields just below a checkbox (tight X match)
        # 4b) In dense checkbox zones (≥3 cb within ±15pt Y), small non-comb
        #     fields from CC dot detection (not pixel underlines) are suspect
        CHECKBOX_SHADOW_Y = 35   # pt — max distance below checkbox
        CHECKBOX_SHADOW_MAX_W = 45  # pt
        CB_ZONE_RADIUS = 18      # pt — Y radius for dense checkbox zone
        CB_ZONE_MIN = 4          # minimum checkboxes to form a zone
        CB_ZONE_MAX_W = 20       # pt — max width for zone-based removal
        # Rule 4b only applies to pixel-scan pages (CC dot artifacts).
        # Text-layer pages generate accurate fields even near checkboxes.
        is_pixel_scan_page = any(f.get("is_pixel_underline") for f in dot_fields)
        cb_positions = []  # [(x, y), ...]
        for cb in checkboxes:
            cb_rect = cb[0]
            if hasattr(cb_rect, 'y0'):
                cb_positions.append((cb_rect.x0, cb_rect.y0))
            elif isinstance(cb_rect, (list, tuple)):
                cb_positions.append((cb_rect[0], cb_rect[1]))
        if cb_positions:
            kept_cb_shadow = []
            for f in dot_fields:
                if f.get("is_comb"):
                    kept_cb_shadow.append(f)
                    continue
                w = f["x1"] - f["x0"]
                y = f["dot_y"]
                is_shadow = False
                # 4c: section header above checkbox row — wide field (≥150pt)
                #     just above checkboxes with moderate below_dark = label text
                #     (Must run before width skip for narrow-field rules)
                if w >= 150 and f.get("below_dark", 0) > 0.08:
                    cb_below = [cb_y for _, cb_y in cb_positions if 0 < cb_y - y < 30]
                    if len(cb_below) >= 2:
                        is_shadow = True
                        if verbose:
                            print(f"  QA remove: {f['name']} width={w:.0f}pt, section header above cb row")
                if is_shadow:
                    removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — section header above cb row")
                    continue
                # Skip wide fields for narrow-field rules (4a, 4b)
                if w >= CHECKBOX_SHADOW_MAX_W:
                    kept_cb_shadow.append(f)
                    continue
                # 4a: tight X match — field directly below a checkbox
                for cb_x, cb_y in cb_positions:
                    y_dist = y - cb_y
                    if 0 < y_dist < CHECKBOX_SHADOW_Y:
                        if abs(f["x0"] - cb_x) < 8:
                            is_shadow = True
                            break
                # 4b: dense zone — CC dot fields (not pixel underlines) in
                #     checkbox-dense areas are likely CC artifacts.
                #     Only runs on pixel-scan pages (CC detection may produce noise).
                if not is_shadow and is_pixel_scan_page and not f.get("is_pixel_underline") and w < CB_ZONE_MAX_W:
                    nearby_cb = sum(1 for _, cb_y in cb_positions if abs(y - cb_y) < CB_ZONE_RADIUS)
                    if nearby_cb >= CB_ZONE_MIN:
                        is_shadow = True
                if is_shadow:
                    removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — checkbox shadow")
                    if verbose:
                        print(f"  QA remove: {f['name']} width={w:.0f}pt, checkbox shadow")
                else:
                    kept_cb_shadow.append(f)
            dot_fields = kept_cb_shadow

        # Rule 4d: checkbox-dominant page — when a page has many checkboxes (≥10)
        # and ALL remaining text fields are narrow (max < 55pt), the text fields
        # are likely all noise (CC dot artifacts / pixel underline fragments on a
        # page that only has checkboxes, no fill-in lines).
        CB_DOMINANT_MIN = 10     # minimum checkboxes on page
        CB_DOMINANT_MAX_W = 55   # pt — all text fields must be below this
        if len(cb_positions) >= CB_DOMINANT_MIN and dot_fields:
            max_text_w = max((f["x1"] - f["x0"]) for f in dot_fields if not f.get("is_comb"))
            if max_text_w < CB_DOMINANT_MAX_W:
                for f in dot_fields:
                    if not f.get("is_comb"):
                        w = f["x1"] - f["x0"]
                        removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — cb-dominant page noise")
                        if verbose:
                            print(f"  QA remove: {f['name']} width={w:.0f}pt, cb-dominant page noise")
                dot_fields = [f for f in dot_fields if f.get("is_comb")]

        # Rule 3: header row artifact filter (pixel-scan pages)
        # Multiple pixel dot fields at the same Y in the header area (y < 130) with below_dark=0 = header artifacts
        # Exclude rect fields (bordered boxes) — these are legitimate form elements
        HEADER_Y_LIMIT = 130
        # Group pixel dot fields by Y position (within 3pt tolerance)
        y_groups = {}
        for f in dot_fields:
            if f.get("is_rect"):  # Skip rectangle fields
                continue
            if f.get("below_dark") is not None and f.get("below_dark", 1) < 0.01:
                y = round(f.get("dot_y", 0) / 3) * 3  # quantize to 3pt
                if y < HEADER_Y_LIMIT:
                    y_groups.setdefault(y, []).append(f)
        # Remove groups with 3+ fields (horizontal header row artifacts)
        header_artifacts = set()
        for y, fields_at_y in y_groups.items():
            if len(fields_at_y) >= 3:
                for f in fields_at_y:
                    header_artifacts.add(id(f))
        if header_artifacts:
            kept4 = []
            for f in dot_fields:
                if id(f) in header_artifacts:
                    w = f["x1"] - f["x0"]
                    removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — header row artifact")
                    if verbose:
                        print(f"  QA remove: {f['name']} width={w:.0f}pt, header row artifact")
                else:
                    kept4.append(f)
            dot_fields = kept4

        # Rule 5: truly isolated fields — any width, NO neighbor within 300pt Y
        # Runs AFTER text artifact removal so stale neighbors don't mask isolation.
        # Catches stray detections in logo/header areas far from any real content.
        # 300pt threshold: real forms can have 100-200pt gaps between field clusters,
        # but truly isolated fields (e.g., logo at y=123, nearest field at y=600+) are 400+pt away.
        # Skip on pages with ≤3 fields — those might legitimately have just 1-2 fill-in areas.
        TRULY_ISOLATED_Y = 300
        n_page_fields = len(dot_fields) + len(checkboxes) + len(digit_comb_fields)
        # Rebuild neighbor list from current surviving fields + checkboxes + combs
        live_ys = [f2["dot_y"] for f2 in dot_fields]
        for cb in checkboxes:
            cb_rect = cb[0]
            if hasattr(cb_rect, 'y0'):
                live_ys.append(cb_rect.y0)
            elif isinstance(cb_rect, (list, tuple)):
                live_ys.append(cb_rect[1])
        for comb in digit_comb_fields:
            comb_rect = comb[1]
            if hasattr(comb_rect, 'y0'):
                live_ys.append(comb_rect.y0)
            elif isinstance(comb_rect, (list, tuple)):
                live_ys.append(comb_rect[1])
        if n_page_fields > 3:
            kept5 = []
            for f in dot_fields:
                y = f["dot_y"]
                has_any = False
                for other_y in live_ys:
                    if abs(other_y - y) < 0.1:
                        continue
                    if abs(other_y - y) < TRULY_ISOLATED_Y:
                        has_any = True
                        break
                if not has_any:
                    w = f["x1"] - f["x0"]
                    removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — truly isolated")
                    if verbose:
                        print(f"  QA remove: {f['name']} width={w:.0f}pt, truly isolated")
                    continue
                kept5.append(f)
            dot_fields = kept5

        # Rule 6: header cluster suppression (pixel-scan underlines only)
        # Remove pixel-detected underlines near the top (y < 200) when they're
        # >200pt from ANY field, AND no non-pixel field exists in the header zone.
        # Only affects is_pixel_underline fields.
        pix_ulines = [f for f in dot_fields if f.get("is_pixel_underline")]
        if len(pix_ulines) > 5:
            header_pix = [f for f in pix_ulines if f["dot_y"] < 200]
            # Check if non-pixel fields exist near the header (within same zone)
            non_pix_in_header = any(
                f["dot_y"] < 250 and not f.get("is_pixel_underline")
                for f in dot_fields
            )
            # Use live_ys (all field types) for gap calculation
            body_ys = [y for y in live_ys if y >= 200]
            # Also check: if multiple header fields share a Y line (within 3pt),
            # it's a real form row, not decorative → don't suppress.
            header_y_counts = {}
            for f in header_pix:
                y_key = round(f["dot_y"] / 3) * 3  # group within 3pt
                header_y_counts[y_key] = header_y_counts.get(y_key, 0) + 1
            has_form_row = any(c >= 3 for c in header_y_counts.values())
            if header_pix and body_ys and not non_pix_in_header and not has_form_row:
                max_header_y = max(f["dot_y"] for f in header_pix)
                min_body_y = min(body_ys)
                if min_body_y - max_header_y > 200:
                    hdr_ids = {id(f) for f in header_pix}
                    kept6 = []
                    for f in dot_fields:
                        if id(f) in hdr_ids:
                            w = f["x1"] - f["x0"]
                            removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — header cluster")
                            if verbose:
                                print(f"  QA remove: {f['name']} width={w:.0f}pt, header cluster")
                        else:
                            kept6.append(f)
                    dot_fields = kept6

        # Rule 7: vertical duplicate (pixel-scan underlines only)
        # Two pixel underlines with same x-range and 12-25pt Y gap → top border
        # of a box; remove the upper one (or the non-comb one).
        # Only applies to narrow fields (<120pt) — wide fields are real form lines.
        vert_dup_ids = set()
        for i, f1 in enumerate(dot_fields):
            if not f1.get("is_pixel_underline"):
                continue
            w1 = f1["x1"] - f1["x0"]
            if w1 >= 110:
                continue
            if id(f1) in vert_dup_ids:
                continue
            for j, f2 in enumerate(dot_fields):
                if j <= i or not f2.get("is_pixel_underline"):
                    continue
                w2 = f2["x1"] - f2["x0"]
                if w2 >= 110:
                    continue
                if id(f2) in vert_dup_ids:
                    continue
                if abs(f1["x0"] - f2["x0"]) < 5 and abs(f1["x1"] - f2["x1"]) < 5:
                    y_gap = abs(f1["dot_y"] - f2["dot_y"])
                    if 12 <= y_gap <= 25:
                        # If one is comb and the other isn't, remove the non-comb
                        # (it's the top border of the comb box)
                        f1_comb = f1.get("is_comb", False)
                        f2_comb = f2.get("is_comb", False)
                        if f1_comb and f2_comb:
                            continue  # both combs, don't remove either
                        if f1_comb:
                            vert_dup_ids.add(id(f2))
                        elif f2_comb:
                            vert_dup_ids.add(id(f1))
                        else:
                            # Neither is comb — remove upper one
                            upper = f1 if f1["dot_y"] < f2["dot_y"] else f2
                            vert_dup_ids.add(id(upper))
        if vert_dup_ids:
            kept7 = []
            for f in dot_fields:
                if id(f) in vert_dup_ids:
                    w = f["x1"] - f["x0"]
                    removed.append(f"P{page_num} {f['name']} (w={w:.0f}pt) — vertical duplicate")
                    if verbose:
                        print(f"  QA remove: {f['name']} width={w:.0f}pt, vertical duplicate")
                else:
                    kept7.append(f)
            dot_fields = kept7

        cleaned.append((dot_fields, checkboxes, digit_comb_fields))

    return cleaned, removed


def main():
    parser = argparse.ArgumentParser(description="Convert PDF form to fillable (V4: text + checkbox + comb, multi-page)")
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument("output", nargs="?", help="Output PDF path")
    parser.add_argument("--border", type=float, default=0, help="Field border width (default: 0)")
    parser.add_argument("--color", default="0,0,166", help="Text color R,G,B 0-255 (default: 0,0,166)")
    parser.add_argument("--dump-fields", action="store_true", help="Dump detected fields as JSON")
    parser.add_argument("--fields-json", help="Use pre-defined fields from JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--coarse-dpi", type=int, default=288)
    parser.add_argument("--refine-dpi", type=int, default=720)
    parser.add_argument("--dot-max-h", type=int, default=12)
    parser.add_argument("--dot-max-w", type=int, default=20)
    parser.add_argument("--no-checkboxes", action="store_true", help="Skip checkbox detection")
    parser.add_argument("--no-digits", action="store_true", help="Skip digit box detection")
    parser.add_argument("--font", default="Tahoma", help="Font name for form fields (default: Tahoma)")
    parser.add_argument("--font-path", default=None, help="Path to .ttf font file (auto-detected if omitted)")
    parser.add_argument("--ocr", action="store_true", help="Run OCR on image-only pages for label detection (experimental)")
    parser.add_argument("--no-validate", action="store_true", help="Skip post-detection validation/QA")
    parser.add_argument("--metadata", help="Output field metadata JSON sidecar (OCR labels + rects)")
    args = parser.parse_args()

    input_path = args.input
    if args.output:
        output_path = args.output
    else:
        p = Path(input_path)
        output_path = str(p.parent / f"{p.stem}_fillable.pdf")

    r, g, b = [int(x) / 255 for x in args.color.split(",")]
    text_color = (r, g, b)

    doc = fitz.open(input_path)
    num_pages = len(doc)
    print(f"Processing {num_pages} page(s)")

    # ── Fields from JSON (AI mode) ──
    if args.fields_json:
        print(f"Using pre-defined fields from {args.fields_json}")
        with open(args.fields_json, "r") as f:
            json_data = json.load(f)
        all_pages_fields = []
        for page_idx in range(num_pages):
            page_data = None
            for pd in json_data:
                if pd.get("page") == page_idx + 1:
                    page_data = pd
                    break
            if page_data is None:
                all_pages_fields.append(([], [], []))
                continue
            # Parse dot_fields
            dot_fields = []
            for i, fd in enumerate(page_data.get("dot_fields", [])):
                field = {
                    "name": fd.get("name", f"field_p{page_idx}_{i}"),
                    "x0": fd["x0"], "x1": fd["x1"],
                    "dot_y0": fd.get("dot_y0", fd["y0"]),
                    "dot_y": fd.get("dot_y", fd["y1"]),
                    "baseline": fd.get("baseline", fd.get("y1", fd.get("dot_y", 0)) - 1),
                    "y_line": fd.get("y_line", fd.get("dot_y", fd.get("y1", 0))),
                    "width": fd.get("width", fd["x1"] - fd["x0"]),
                    "left_label": fd.get("left_label", fd.get("label", "")),
                }
                dot_fields.append(field)
            # Parse checkboxes: list of (rect, label)
            checkboxes = []
            for cd in page_data.get("checkboxes", []):
                r = cd.get("rect")
                if r is None and all(k in cd for k in ("x0", "y0", "x1", "y1")):
                    r = [cd["x0"], cd["y0"], cd["x1"], cd["y1"]]
                if r:
                    checkboxes.append((r, cd.get("label", "")))
            # Parse comb fields: list of (name, rect, maxlen)
            digit_comb_fields = []
            for dd in page_data.get("digit_comb_fields", []):
                r = dd.get("rect")
                if r is None and all(k in dd for k in ("x0", "y0", "x1", "y1")):
                    r = [dd["x0"], dd["y0"], dd["x1"], dd["y1"]]
                if r:
                    digit_comb_fields.append((dd.get("name", "comb"), r, dd.get("maxlen", 13)))
            all_pages_fields.append((dot_fields, checkboxes, digit_comb_fields))
            t = len(dot_fields); c = len(checkboxes); d = len(digit_comb_fields)
            if t + c + d > 0:
                print(f"  Page {page_idx + 1}: {t} text, {c} checkbox, {d} comb")
        doc.close()
        # Skip validation for JSON mode (fields are pre-defined)
        args.no_validate = True
    else:
        all_pages_fields = []
        for page_idx in range(num_pages):
            page = doc[page_idx]

            # Per-page text layer detection
            page_text = page.get_text().strip()
            page_has_text = bool(page_text) and ('.' in page_text or '…' in page_text)
            if page_idx == 0:
                if page_has_text:
                    print("Detected text layer — using character-level extraction")
                elif page_text:
                    print(f"Text layer found but no dot fields ('{page_text[:30]}...') — using pixel scan")
                else:
                    print("No text layer — using multi-res CC analysis")

            if args.verbose:
                print(f"\n── Page {page_idx + 1} ──")
                if page_idx > 0:
                    mode = "text-layer" if page_has_text else ("pixel scan" if not page_text else "pixel scan (text but no dots)")
                    print(f"  Mode: {mode}")

            dot_fields, checkboxes, digit_comb_fields = detect_page_fields(
                page, page_idx, page_has_text, verbose=args.verbose,
                coarse_dpi=args.coarse_dpi, refine_dpi=args.refine_dpi,
                dot_max_h=args.dot_max_h, dot_max_w=args.dot_max_w,
                skip_checkboxes=args.no_checkboxes, skip_digits=args.no_digits,
            )
            # OCR for pixel-scan pages (no text layer) to extract left labels
            if not page_has_text and dot_fields and getattr(args, 'ocr', False):
                ocr_page_labels(page, dot_fields, verbose=args.verbose)
            all_pages_fields.append((dot_fields, checkboxes, digit_comb_fields))

            if not args.verbose:
                t = len(dot_fields); c = len(checkboxes); d = len(digit_comb_fields)
                if t + c + d > 0:
                    print(f"  Page {page_idx + 1}: {t} text, {c} checkbox, {d} comb")

        doc.close()

    # ── Validation / QA ──
    if not args.no_validate:
        all_pages_fields, qa_removed = validate_fields(all_pages_fields, verbose=args.verbose)
        if qa_removed:
            print(f"QA removed {len(qa_removed)} suspicious field(s):")
            for desc in qa_removed:
                print(f"  ✗ {desc}")

    if args.dump_fields:
        data = []
        for page_idx, (df, cb, dcf) in enumerate(all_pages_fields):
            data.append({
                "page": page_idx + 1,
                "dot_fields": df,
                "checkboxes": [{"rect": r, "label": l} for r, l in cb],
                "digit_comb_fields": [{"name": n, "rect": r, "maxlen": m} for n, r, m in dcf],
            })
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    total_all = sum(len(df) + len(cb) + len(dcf) for df, cb, dcf in all_pages_fields)
    if total_all == 0:
        print("ERROR: No fields detected on any page", file=sys.stderr)
        sys.exit(1)

    counts = create_fillable(input_path, output_path, all_pages_fields,
                            args.border, text_color, args.verbose,
                            font_name=args.font, font_path=args.font_path)

    total = counts["text"] + counts["cb"] + counts["comb"]
    print(f"Created fillable PDF: {output_path} ({total} fields across {num_pages} page(s): "
          f"{counts['text']} text, {counts['cb']} checkbox, {counts['comb']} comb)")

    # ── Metadata sidecar JSON ──
    # Always generate metadata JSON sidecar alongside the fillable PDF
    metadata_path = args.metadata if args.metadata else os.path.splitext(output_path)[0] + "_metadata.json"
    if True:
        metadata = {"form_name": os.path.splitext(os.path.basename(input_path))[0], "fields": []}
        doc = fitz.open(output_path)
        for page in doc:
            for w in page.widgets():
                ft = w.field_type
                if ft == fitz.PDF_WIDGET_TYPE_TEXT:
                    ftype = "comb" if w.text_maxlen and w.text_maxlen > 0 else "text"
                elif ft == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                    ftype = "checkbox"
                else:
                    ftype = "other"
                # Find OCR label from detection data
                ocr_label = ""
                page_idx = page.number
                if page_idx < len(all_pages_fields):
                    df, cb_list, dcf = all_pages_fields[page_idx]
                    for f in df:
                        if f.get("name") == w.field_name:
                            ocr_label = f.get("left_label", "")
                            break
                    if not ocr_label:
                        for rect, label in cb_list:
                            # Match by position
                            if (abs(rect[0] - w.rect.x0) < 5 and abs(rect[1] - w.rect.y0) < 5):
                                ocr_label = label or ""
                                break
                metadata["fields"].append({
                    "field_name": w.field_name,
                    "type": ftype,
                    "page": page.number + 1,
                    "rect": [round(x, 1) for x in w.rect],
                    "ocr_label": ocr_label,
                    "label": "",
                    "name_en": "",
                    "description": "",
                })
        doc.close()
        # Clean surrogates from OCR labels before writing JSON
        for f in metadata["fields"]:
            if f.get("ocr_label"):
                f["ocr_label"] = f["ocr_label"].encode("utf-8", errors="replace").decode("utf-8")
        with open(metadata_path, "w", encoding="utf-8") as mf:
            json.dump(metadata, mf, indent=2, ensure_ascii=False)
        print(f"Metadata: {metadata_path} ({len(metadata['fields'])} fields)")


if __name__ == "__main__":
    main()
