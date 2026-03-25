---
name: pdf-fillable
description: Convert scanned or text-layer PDF forms into fillable PDF forms with interactive text fields placed on dotted lines (จุดไข่ปลา), checkboxes on square boxes, and comb digit fields on digit boxes. Use when user wants to make a PDF form fillable, add form fields to PDF, create interactive PDF forms, or convert static PDF forms to editable ones.
---

# PDF Fillable Form Creator

Convert static PDF forms into fillable PDFs by detecting dotted-line field positions, checkbox squares, and digit box groups — adding interactive text widgets, checkbox widgets, and comb digit fields.

## Golden Files Are Sacred

**Never replace or overwrite golden (expected) test files.** Golden files in `tests/expected/` are human-verified baselines. If the script output doesn't match a golden file, the script is wrong — not the golden. Only the user can provide a new golden file. When adding new test cases, generate output and send it to the user for manual verification before adding it as a golden baseline.

## Principle: Always Automate

**Whenever manual post-processing is needed for a form, automate it into the script.** Never leave a step that requires human intervention if it can be coded. Every manual fix should become an auto feature in `make_fillable_v4.py`. This keeps the workflow as: **one command in → fillable PDF out**.

## Workflow — Self-Check Before Sending

**Always follow this process when converting a PDF form:**

1. **Run** `make_fillable_v4.py` with `-v` (verbose)
2. **Check QA output** — script auto-validates and removes suspicious fields
3. **Render** the output pages to images (PyMuPDF `get_pixmap`)
4. **Visual scan** — for each page, verify:
   - No fields overlap printed labels/text
   - No tiny orphan fields in blank areas
   - All visible dotted lines have corresponding fields
   - Checkboxes are only on actual checkbox squares
5. **Fix** any remaining issues — **then automate the fix into the script**
6. **Send** only when satisfied all fields are correct

The script's built-in QA catches most false positives automatically (see Field Validation below). Only send the file after confirming the QA log and visual check pass.

## Quick Start

```bash
# Basic usage (auto-detect + auto-validate)
.venv/bin/python3 skills/pdf-fillable/scripts/make_fillable_v4.py input.pdf output.pdf -v

# Custom font (TH Sarabun New)
.venv/bin/python3 skills/pdf-fillable/scripts/make_fillable_v4.py input.pdf output.pdf --font THSarabunNew --font-path /tmp/THSarabunNew.ttf -v

# Skip checkbox/digit detection
.venv/bin/python3 skills/pdf-fillable/scripts/make_fillable_v4.py input.pdf output.pdf --no-checkboxes --no-digits -v

# Disable auto-validation (if QA removes fields you want to keep)
.venv/bin/python3 skills/pdf-fillable/scripts/make_fillable_v4.py input.pdf output.pdf --no-validate -v

# Dump detected fields as JSON (for debugging)
.venv/bin/python3 skills/pdf-fillable/scripts/make_fillable_v4.py input.pdf /dev/null --dump-fields

# With OCR label detection (experimental, requires Tesseract + Thai)
.venv/bin/python3 skills/pdf-fillable/scripts/make_fillable_v4.py input.pdf output.pdf --ocr -v
```

## Workflow

1. **Detect form type**: Check if PDF has meaningful text layer (must contain `"."` for dots)
2. **Smart fallback**: Text layer without dots (e.g., junk text "ทำ") → automatic pixel scan
3. **Process all pages**: Loop through every page detecting fields
4. **Find dot positions**: Text-layer → character extraction; Image-only → CC analysis
5. **Detect squares**: Classify as checkboxes or digit boxes from vector drawings
6. **Deduplicate**: Remove near-duplicate rows (within 4pt y) from pixel scan
7. **OCR labels** (optional): Run Tesseract on image-only pages for left_label extraction
8. **Create form fields**: Add text widgets, checkbox widgets, and comb digit fields
9. **Embed font**: Tahoma by default (Simple TrueType + WinAnsiEncoding)
10. **Post-process**: Remove /AP, add /MK <<>>, set alignment, set NeedAppearances
11. **Verify**: Open in PDF viewer, check fields align

## Dot Detection

### Text-layer PDFs — Character-level extraction

Extract char-level data with `page.get_text("rawdict")`, group by Y (5pt tolerance), find consecutive dot runs as dot fields. Supports both `"."` (period U+002E) and `"…"` (ellipsis U+2026) — Thai government forms often use both as dotted-line fill areas. Exact and reliable.

### Image-only PDFs — Multi-resolution CC analysis

Two-pass approach:

1. **Pass 1 (coarse, 288dpi)**: Scan row density to find text line Y bands
2. **Pass 2 (refine, 720dpi)**: For each line band, run connected-component analysis:
   - CCs with **4≤h≤12px and w≤20px** → dot candidates (`dot_min_h=4` filters table border fragments which are h=2-3px)
   - Larger CCs → text
   - **Adjacency filter**: Small CCs within 0.5pt X AND 2pt Y of a text CC are excluded (Thai diacritical marks). Y-check prevents cross-line filtering in tall bands (e.g., 43pt band covering header + dotted lines)
   - **Sub-line clustering**: Dot CCs within a band are clustered by Y position (5pt gap threshold). Each sub-line is processed independently with its own segments and y_line. This handles wide bands that contain multiple text lines (e.g., สำหรับเจ้าหน้าที่ box with เลขรับที่ + วันที่ on separate lines within one coarse band)
   - **Minimum dot count**: ≥3 dot CCs per segment
   - **Minimum field width**: 15pt
   - **Merge gap**: 6pt — dot segments within 6pt are merged into one field
3. **Deduplication**: Rows with y_line within 4pt are deduplicated (prevents double-detection)

### Table grid detection (auto)

Forms with empty bordered tables (no dotted lines inside cells) are auto-detected on pixel-scan pages:
1. **Horizontal line clustering**: Find peaks in row density (>0.15), prefer strong lines (density >0.4) but fallback to all candidates. Select largest cluster of evenly-spaced lines (90% gap consistency within 1.25× median, density range <3×, scored by count − std)
2. **Vertical lines**: Scan within table Y range, require density >0.30 (continuous lines, not dots)
3. **Validation**: 3-12 columns, ≥3 data rows, table spans >40% page width
4. **Data rows**: Filter to rows with consistent gap (0.5-1.5× median), skip header rows (larger gaps)
5. **Cell fields**: Create text fields using cell boundaries directly (`dot_y0`=top, `dot_y`=bottom), with padding (x: 2pt, y: 3pt). No 10% height expansion for table cells (`is_table=True` flag)
6. Only runs on **pixel-scan pages** — text-layer pages skip table detection (their structured content causes false positives)

### Text overlap filter (auto)

Removes false positives from pixel scan where detected "dot" fields actually overlap printed text:
1. For each pixel-scan field, check text-layer words that intersect the field rect (`y-12` to `y+2` — matching actual widget dimensions)
2. Calculate coverage: width of pure non-dot text (no `.` or `…`) overlapping the field / field width
3. If coverage > 60%, the field is over printed text → remove as false positive
4. Short labels next to dotted lines (coverage < 60%) are preserved — these are normal form labels
5. **Critical**: overlap rect must match widget rect — using wider rect (e.g., y+15) catches unrelated text below the field and removes legitimate fields

### Smart text-layer detection

A text layer is only used for character-level extraction if it contains `"."` or `"…"` characters. PDFs with minimal junk text (e.g., stray "ทำ" from poor OCR) automatically fall back to pixel scan.

## Field Positioning & Height

- **Text-layer PDFs**: `rect = [x0, dot_y0, x1, baseline + 1]` using font metrics
- **Image-only PDFs**: `rect = [x0, dot_y - 11.2, x1, dot_y + 2]`
- **Table cells**: `rect = [x0, cy0+3, x1, cy1-3]` using grid boundaries directly (pad_x=2pt, pad_y=3pt)
- **Height expansion**: All fields expanded 10% upward — **except table cells** (`is_table=True` skips expansion to stay within grid lines)

## Checkbox Detection

### Vector-based (get_drawings)
- **Small squares (~7-12 pt)**: Groups of ≥3 tightly packed (gap < 3pt) → digit boxes; otherwise → checkboxes
- **Medium squares (~12-17 pt)**: Always digit boxes (e.g., เลขบัตรประชาชน)
- Checkboxes: `border_width=0`, `border_color=(1,1,1)` — uses existing drawn border
- Comb digits: grouped into subgroups by gap >5pt, each subgroup = one comb field with `text_maxlen`

### Glyph-based (text layer)
Some forms embed checkboxes as font glyphs (e.g., Wingdings, Symbol) instead of vector drawings. These appear as special characters in the text layer. Detected characters:
- **Surrogate chars** (U+D800–U+DFFF) — actual surrogates from font-specific glyphs (e.g., สัญญาซื้อขายรถยนต์ uses U+DBC0 in Times New Roman for □)
- **Private Use Area** (U+E000–U+F8FF, U+F0000+) — custom font glyphs
- **Unicode ballot boxes**: ☐ U+2610, ☑ U+2611, ☒ U+2612
- **Unicode squares**: ■ U+25A0, □ U+25A1, ◻ U+25FB, ◼ U+25FC
- **Check/cross marks**: ✓ U+2713, ✔ U+2714, ✗ U+2717, ✘ U+2718
- **Wingdings**: U+F06F, U+F06E, U+F0FE

Glyph must be 5-25pt wide/tall and **roughly square** (aspect ratio ≥ 0.4). Label extracted from text to the right of the glyph.

**Important exclusions:**
- **U+FFFD** (replacement character) is NOT a checkbox — appears when PyMuPDF can't decode CID fonts (e.g., BrowalliaNew Identity-H encoding maps Thai digits to U+FFFD)
- **Aspect ratio filter**: Glyphs that are tall/narrow (e.g., 5.8×20pt, ratio 0.29) are rejected — real checkboxes are roughly square
- Bug found on DLT คำขอโอนรับโอน (Illustrator-generated): BrowalliaNew Identity-H digits (section numbers + fee amounts) decoded as U+FFFD, old `cp > 0xD800` condition caught 12 false positives

## Field Validation (Auto-QA)

The script runs automatic post-detection validation (disable with `--no-validate`). Three rules:

| Rule | Condition | Action |
|------|-----------|--------|
| **Too narrow** | Field width < 15pt | Remove — too small to be usable |
| **Sparse page** | Page has ≤3 fields, all < 35pt | Remove all — likely all false positives (e.g., page with only warnings/instructions) |
| **Isolated small** | Field < 25pt wide, no neighbor within 4pt vertically AND 80pt horizontally | Remove — artifact or stray dots, not a real field |
| **Wide isolation** | Field 25-30pt wide, NO neighbor within 100pt vertically (checks all field types: text + checkbox + comb) | Remove — truly alone on the page section |
| **Text artifact** | Pixel-scan field with `below_dark > 0.08` AND width < 80pt | Remove — real dotted lines have empty space below; text artifacts have dense text |

"Neighbor" = another text field on roughly the same line (±4pt y, ±80pt x gap). Real small fields (like date segments วัน/เดือน/ปี) always cluster with other fields on the same line.

### Text artifact detection (below_dark metric)

For pixel-scan pages, the script measures dark pixel density in an 11pt strip **below** each field (y+2 to y+13 at 720dpi). Real dotted-line fields have empty white space below (between text lines), while false positives caused by Thai diacritical marks sit within continuous text paragraphs with more text directly below. Threshold 0.08 provides a safe margin (real fields max ~0.07, FP fields min ~0.09).

**Tested on:**
- หนังสือมอบอำนาจ (image-only): removed 4 false positives (20pt, 18pt artifacts + 2 sparse page 2 fields), kept all 48 real fields ✅
- DLT คำขอโอนรับโอน (text-layer): 0 removed, all 84 correct ✅
- สัญญาซื้อขายรถยนต์ (text-layer): 0 removed, all 47 correct ✅
- สปส.1-03 (text-layer): removed 2 tiny 9pt fragments, kept all 119 real fields ✅
- บต.44 WP.44 (text-layer, mixed `.`+`…`): 0 removed, all 91 fields correct (81 text + 10 checkbox) ✅
- บต.52 (image-only, auto table): 0 removed, 39 dot + 96 auto table + 2 pixel cb = 137 ✅
- บต.53 (image-only, auto table+filter): 2 text overlaps auto-removed, 27 dot + 28 auto table + 12 p2 + 2 pixel cb = 69 ✅

## Field Alignment

- **Short fields** (<100pt): **Centered** automatically
- **Keyword fields**: Centered if left label contains ลงชื่อ / ตำแหน่ง / วันที่ (text-layer mode)
- **Long fields** (≥100pt): **Left-aligned**

## Font Embedding — Critical Details

### Encoding
- **Must use**: Simple TrueType + WinAnsiEncoding (`set_simple=True, encoding=fitz.TEXT_ENCODING_LATIN`)
- **Never use**: CIDFont/Identity-H — breaks number/English input in Acrobat

### Thai สระ อำ Display — Three Required Settings

All three are mandatory for Thai combining characters to display on screen:

1. **NeedAppearances=true** in AcroForm — tells viewer to regenerate appearance streams
2. **Remove /AP** from all widgets — PyMuPDF's pre-generated AP uses built-in font that can't render Thai
3. **Add /MK <<>>** to all widgets — empty Appearance Characteristics dict triggers Acrobat to regenerate properly. **Without /MK, สระ อำ won't display even with NeedAppearances=true.**

### Font search order
`/mnt/c/Windows/Fonts/` → `/usr/share/fonts/truetype/` → `/usr/share/fonts/` → `/usr/local/share/fonts/`

### Available fonts
- **Tahoma** (default): `/mnt/c/Windows/Fonts/tahoma.ttf`
- **TH Sarabun New**: Download from `Phonbopit/sarabun-webfont` on GitHub

## Filling Form Values (Preserve Font)

**Problem**: `w.update()` resets font to Helvetica.

**Solution**: Set values via `xref_set_key` + `NeedAppearances=true`:

```python
doc.xref_set_key(w.xref, "V", fitz.get_pdf_str(value))
doc.xref_set_key(w.xref, "AP", "null")  # Remove old appearance
doc.xref_set_key(cat, "AcroForm/NeedAppearances", "true")
```

**Never call `w.update()` after setting values** — it destroys the font.

## Printing Filled Forms — Flatten with htmlbox

**Problem**: Filled forms using `NeedAppearances=true` print as `???????` via CUPS/IPP (ghostscript can't generate appearance streams). Also, `insert_textbox` and `TextWriter` cause สระจม (Thai vowel marks sink into consonants when printed).

**Solution**: Use `insert_htmlbox` (HarfBuzz shaping) + **Tahoma** font to write text directly on the page, then delete all widgets (flatten).

```python
import fitz

TAHOMA = "/mnt/c/Windows/Fonts/tahoma.ttf"

def fill_and_flatten(pdf, out, data, center_fields=None):
    """Fill form and flatten to static text for reliable printing."""
    doc = fitz.open(pdf)
    css = f"""@font-face {{font-family: Tahoma; src: url({TAHOMA});}}
    * {{font-family: Tahoma; font-size: 11px; margin: 0; padding: 0;}}
    .center {{text-align: center;}}"""
    
    for pi in range(doc.page_count):
        page = doc[pi]
        widgets = list(page.widgets())
        for w in widgets:
            val = data.get(w.field_name, "")
            if not val:
                continue
            r = w.rect
            is_centered = center_fields and w.field_name in center_fields
            # Auto-shrink font if text wider than field
            font = fitz.Font(fontfile=TAHOMA)
            fontsize = 11
            text_width = font.text_length(val, fontsize=fontsize)
            while text_width > r.width - 2 and fontsize > 6:
                fontsize -= 0.5
                text_width = font.text_length(val, fontsize=fontsize)
            cls = ' class="center"' if is_centered else ''
            local_css = css.replace("font-size: 11px", f"font-size: {fontsize}px")
            page.insert_htmlbox(r, f'<p{cls}>{val}</p>', css=local_css)
        # Remove all widgets (flatten)
        for w in list(page.widgets()):
            page.delete_widget(w)
    doc.save(out, garbage=4, deflate=True)
    doc.close()
```

### Why htmlbox?

| Method | Thai shaping | Print quality | Notes |
|--------|-------------|---------------|-------|
| `xref_set_key` + `NeedAppearances` | ✅ viewer | ❌ CUPS prints ??????? | Fillable but unprintable via CUPS |
| `insert_textbox` | ❌ สระจม | ⚠️ vowels sink | No HarfBuzz shaping |
| `TextWriter` | ❌ สระซ้อน | ⚠️ vowels overlap | No HarfBuzz shaping |
| **`insert_htmlbox`** | ✅ HarfBuzz | ✅ perfect | **Recommended for print** |

### When to use which

- **Fillable form for screen/Adobe** → `xref_set_key` + `NeedAppearances` (original method)
- **Print-ready PDF via CUPS/IPP** → `fill_and_flatten` with `insert_htmlbox` (flatten method)

## PDF/A Handling

Government PDFs (e.g., dlt.go.th) are often PDF/A-1a → opens read-only. Script strips `pdfaid:part` and `pdfaid:conformance` from XMP metadata.

## OCR Label Detection (Experimental)

- Enabled with `--ocr` flag
- Uses PyMuPDF's `page.get_textpage_ocr()` with Tesseract (tha+eng, 300dpi)
- Assigns left_label to fields based on OCR word positions
- Quality varies — Tesseract struggles with Thai government form scans
- Useful for some forms, unreliable for others

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--font` | Tahoma | Font name for form fields |
| `--font-path` | auto | Path to .ttf file |
| `--border` | 0 | Border width (pt) |
| `--color` | 0,0,166 | Text color (R,G,B 0-255) |
| `--coarse-dpi` | 288 | Pass 1 DPI for pixel scan |
| `--refine-dpi` | 720 | Pass 2 DPI for pixel scan |
| `--dot-max-h` | 12 | Max dot CC height (pixels) |
| `--dot-max-w` | 20 | Max dot CC width (pixels) |
| `--no-checkboxes` | off | Skip checkbox detection |
| `--no-digits` | off | Skip digit box detection |
| `--ocr` | off | Run OCR for label detection |
| `--dump-fields` | off | Output detected fields as JSON |
| `--fields-json` | - | Use pre-defined fields from JSON |
| `-v` | off | Verbose output |

## Dependencies

- **PyMuPDF** (`fitz`): PDF manipulation and form fields
- **Pillow** (`PIL`): Image processing
- **scipy** (`ndimage`): Connected-component labeling
- **Tesseract** (optional): OCR for label detection (`tesseract-ocr-tha`)
- All in workspace `.venv`

## Regression Tests

Run from workspace root:
```bash
.venv/bin/python3 skills/pdf-fillable/tests/run_tests.py
```

Test structure:
- `tests/inputs/` — blank source PDFs (widgets stripped)
- `tests/expected/` — baseline output PDFs with correct field counts/positions
- `tests/run_tests.py` — compares field counts + positions (2pt tolerance)

**Test forms (9):**
| Form | Type | Expected |
|------|------|----------|
| DLT_คำขอโอนรับโอน | text+glyph | 84 (84t) |
| บต44 | text+ellipsis | 91 (81t+10cb) |
| บต52 | pixel scan+table | 137 (135t+2cb) — 96 auto table fields |
| บต53 | pixel scan+table+filter | 69 (67t+2cb) — 28 auto table + 2 auto-filtered FP |
| บต54 | pixel scan+checkbox | 21 (17t+4cb) — 4 auto-filtered FP (text artifacts) |
| บต55 | pixel scan | 56 (54t+2cb) — wide isolation QA |
| สปส1-03 | text-layer | 113 (35t+57cb+21comb) |
| สัญญาซื้อขายรถยนต์ | text+glyph | 47 (45t+2cb) |
| หนังสือมอบอำนาจ | image-only | 48 (48t) |
| RG013_โอนบัญชีธนาคาร | text+wingdings | 19 (8t+11cb) — Wingdings2 glyph checkboxes + underscore fields |

**Important:** Test inputs must be widget-free blank forms. If copying from inbound media, strip existing widgets first.

## Scripts

- **`scripts/make_fillable_v4.py`** — Recommended. Full-featured auto-detection.
- **`scripts/make_fillable_v3.py`** — Text fields only (no checkboxes/digits).
- **`scripts/make_fillable.py`** — V1 legacy, superseded.
