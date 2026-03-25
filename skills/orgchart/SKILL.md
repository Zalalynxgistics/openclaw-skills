---
name: orgchart
description: Create and maintain LYNX organization chart as HTML/PNG. Use when user asks to update org chart, add/remove people, change department structure, add photos, or re-render the chart. Handles photo cropping, HTML generation with proper connector lines, and Chrome headless rendering.
---

# Org Chart Skill

## Files

- **Working HTML files** — in workspace root:
  - `orgchart_with_lex.html` — version with LEX department (orange styling)
  - `orgchart_no_lex.html` — version without LEX
- **Photos** — `orgchart_photos/` (300x300 JPEG headshots)
- **Rendered output** — `orgchart_with_lex.png`, `orgchart_no_lex.png`
- **Reference data** — `references/structure.md` for current org structure
- **HTML template** — `assets/template.html` for CSS classes and patterns

## Workflow

1. Read `references/structure.md` for current org structure
2. Edit the HTML file(s) — apply changes
3. Render with Chrome headless: `google-chrome --headless --no-sandbox --disable-gpu --window-size=2400,1400 --screenshot=<output>.png "file://$(pwd)/<file>.html"`
4. Verify with vision — check for excess lines, alignment, photo visibility
5. Send both versions if both exist

## Connector Line System (CRITICAL)

Never use fixed-width `<div class="hl">` for horizontal lines. Use the position-based system:

### CSS Classes

```css
.cl         — absolute positioned horizontal line (2px, blue)
.cl.first   — left:50%; right:-1px  (first item: center → right edge)
.cl.mid     — left:-1px; right:-1px (middle item: full width)
.cl.last    — left:-1px; right:50%  (last item: left edge → center)
.sp         — flex:1 spacer with border-top (bridges gaps between items)
```

### Pattern

```html
<div style="display:flex;align-items:flex-start;">
  <div class="col" style="position:relative;">
    <div class="cl first"></div>         <!-- line from center to right -->
    <div class="vl" style="height:10px;"></div>
    <!-- content -->
  </div>
  <div class="sp"></div>                 <!-- bridges gap between items -->
  <div class="col" style="position:relative;">
    <div class="cl mid"></div>           <!-- line across full width -->
    <div class="vl" style="height:10px;"></div>
    <!-- content -->
  </div>
  <div class="sp"></div>
  <div class="col" style="position:relative;">
    <div class="cl last"></div>          <!-- line from left to center -->
    <div class="vl" style="height:10px;"></div>
    <!-- content -->
  </div>
</div>
```

This ensures horizontal lines span ONLY between item centers — no excess.

### LEX Styling

LEX uses orange color scheme: `.cl.lex-c` (orange lines), `.sp.lex-s` (orange spacers), `.bx.dp.lex` (orange department box), `.vl.lex` (orange vertical lines).

## Photo Processing

Crop incoming photos to 300x300 square JPEG headshots:

```python
from PIL import Image
img = Image.open(input_path)
w, h = img.size
crop_size = min(w, h) * 0.65
cx, cy = w/2, h * 0.32  # face in upper portion
# crop, square, resize to 300x300, save as JPEG quality=90
```

Save to `orgchart_photos/<Name>.jpg`.

## Box Hierarchy

| Class | Level | Style |
|-------|-------|-------|
| `.bx.gm` | GM | Dark blue gradient, white text, 50px photo |
| `.bx.vp` | VP (AGM/DGM) | Blue gradient, white text, 44px photo |
| `.bx.dp` | Department | Light blue bg, blue border |
| `.bx.sc` | Section/Sub-dept | White bg, light blue border |
| `.bx.pr` | Person card | White bg, blue border, 40px photo |

## Rules

- Always maintain BOTH versions (with_lex / no_lex) when both exist
- Back Office reports directly to GM (not to DGM)
- LEX is a separate branch from GM (not under any VP)
- After changes, always render and send preview for review
- Verify with vision before sending — check for excess lines
- `&` in HTML must be `&amp;` (e.g., "HR &amp; Admin")
