#!/usr/bin/env python3
"""AI-powered field labeling for fillable PDFs.

Takes a fillable PDF + its OCR metadata JSON, renders annotated page images
with numbered field markers, sends to an AI vision model for semantic labeling.
Outputs a golden metadata JSON with label, name_en, and description for each field.

Usage:
    python3 label_fields.py input.pdf metadata.json output.json [--model MODEL] [--render-dir DIR]

Requires: PyMuPDF, openai (or anthropic) SDK
"""
import argparse
import json
import os
import sys
import fitz


def render_annotated_pages(pdf_path, metadata, render_dir, dpi=150):
    """Render each page with numbered field markers overlaid."""
    os.makedirs(render_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    page_images = []

    # Group fields by page
    fields_by_page = {}
    for i, f in enumerate(metadata["fields"]):
        pg = f["page"]
        fields_by_page.setdefault(pg, []).append((i, f))

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        pg_num = page_idx + 1

        # Render base page
        pix = page.get_pixmap(dpi=dpi)

        # Draw field markers
        fields = fields_by_page.get(pg_num, [])
        for field_idx, f in fields:
            rect = fitz.Rect(f["rect"])
            # Scale rect to pixel coordinates
            scale = dpi / 72
            r = fitz.Rect(
                rect.x0 * scale, rect.y0 * scale,
                rect.x1 * scale, rect.y1 * scale
            )
            # Draw red rectangle outline
            ir = fitz.IRect(r)
            for x in range(ir.x0, min(ir.x1, pix.width)):
                for thickness in range(2):
                    if 0 <= ir.y0 + thickness < pix.height:
                        pix.set_pixel(x, ir.y0 + thickness, (255, 0, 0))
                    if 0 <= ir.y1 - thickness - 1 < pix.height:
                        pix.set_pixel(x, ir.y1 - thickness - 1, (255, 0, 0))
            for y in range(ir.y0, min(ir.y1, pix.height)):
                for thickness in range(2):
                    if 0 <= ir.x0 + thickness < pix.width:
                        pix.set_pixel(ir.x0 + thickness, y, (255, 0, 0))
                    if 0 <= ir.x1 - thickness - 1 < pix.width:
                        pix.set_pixel(ir.x1 - thickness - 1, y, (255, 0, 0))

        # Save annotated page
        img_path = os.path.join(render_dir, f"page_{pg_num}.png")
        pix.save(img_path)
        page_images.append(img_path)

    doc.close()
    return page_images


def build_prompt(metadata, page_num=None):
    """Build the AI prompt for field labeling."""
    if page_num:
        fields = [f for f in metadata["fields"] if f["page"] == page_num]
    else:
        fields = metadata["fields"]

    field_list = []
    for i, f in enumerate(fields):
        idx = metadata["fields"].index(f)
        ocr_hint = f' (OCR: "{f["ocr_label"]}")' if f.get("ocr_label") else ""
        field_list.append(
            f'{idx}: {f["field_name"]} [{f["type"]}] '
            f'page={f["page"]} rect=({f["rect"][0]:.0f},{f["rect"][1]:.0f},{f["rect"][2]:.0f},{f["rect"][3]:.0f})'
            f'{ocr_hint}'
        )

    return f"""You are labeling form fields in a Thai government/business form: "{metadata['form_name']}"

Each field is marked with a red rectangle on the attached page image(s).
Below is the field list with OCR hints (may be inaccurate).

FIELDS:
{chr(10).join(field_list)}

For EACH field, provide:
1. "label" — Thai label (what the field is for, e.g. "ชื่อผู้ยื่นคำขอ")
2. "name_en" — English snake_case name (e.g. "applicant_first_name")
3. "description" — Brief Thai description of what to fill in

For checkboxes, describe what checking it means.
For comb fields, describe the expected digit/character format.

Respond with ONLY a JSON array of objects, one per field, in the same order:
[
  {{"field_name": "p1_field_1", "label": "...", "name_en": "...", "description": "..."}},
  ...
]

Important:
- Keep the exact field_name from the list
- Every field must have non-empty label, name_en, and description
- Use Thai for label and description, English for name_en
- name_en should be descriptive and unique (use page prefix if needed)
"""


def call_ai_vision(prompt, image_paths, model="anthropic/claude-sonnet-4-20250514"):
    """Call AI vision model. Supports OpenAI-compatible and Anthropic APIs."""
    import base64

    # Try Anthropic SDK first
    try:
        import anthropic
        client = anthropic.Anthropic()

        content = []
        for img_path in image_paths:
            with open(img_path, "rb") as f:
                img_data = base64.standard_b64encode(f.read()).decode()
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img_data}
            })
        content.append({"type": "text", "text": prompt})

        # Extract model name (strip provider prefix)
        model_name = model.split("/")[-1] if "/" in model else model

        response = client.messages.create(
            model=model_name,
            max_tokens=8192,
            messages=[{"role": "user", "content": content}]
        )
        return response.content[0].text

    except (ImportError, Exception) as e:
        print(f"Anthropic SDK failed ({e}), trying OpenAI-compatible...", file=sys.stderr)

    # Fallback: OpenAI-compatible API
    try:
        import openai
        client = openai.OpenAI()

        content = []
        for img_path in image_paths:
            with open(img_path, "rb") as f:
                img_data = base64.standard_b64encode(f.read()).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_data}"}
            })
        content.append({"type": "text", "text": prompt})

        response = client.chat.completions.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": content}]
        )
        return response.choices[0].message.content

    except Exception as e:
        print(f"OpenAI API also failed: {e}", file=sys.stderr)
        sys.exit(1)


def parse_ai_response(response_text):
    """Extract JSON array from AI response (handles markdown code blocks)."""
    text = response_text.strip()
    # Strip markdown code block
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def merge_labels(metadata, ai_labels):
    """Merge AI-generated labels into metadata."""
    label_map = {l["field_name"]: l for l in ai_labels}
    missing = []
    for f in metadata["fields"]:
        if f["field_name"] in label_map:
            l = label_map[f["field_name"]]
            f["label"] = l.get("label", "")
            f["name_en"] = l.get("name_en", "")
            f["description"] = l.get("description", "")
        else:
            missing.append(f["field_name"])
    return missing


def main():
    parser = argparse.ArgumentParser(description="AI-powered field labeling")
    parser.add_argument("pdf", help="Fillable PDF path")
    parser.add_argument("metadata_json", help="Input metadata JSON (from --metadata)")
    parser.add_argument("output_json", help="Output labeled metadata JSON")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                       help="AI model (default: claude-sonnet-4-20250514)")
    parser.add_argument("--render-dir", default="/tmp/pdf-label-render",
                       help="Directory for rendered page images")
    parser.add_argument("--dry-run", action="store_true",
                       help="Only render images and print prompt, don't call AI")
    parser.add_argument("--max-fields-per-call", type=int, default=100,
                       help="Max fields per AI call (split large forms)")
    args = parser.parse_args()

    # Load metadata
    with open(args.metadata_json, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    print(f"Form: {metadata['form_name']} ({len(metadata['fields'])} fields)")

    # Render annotated pages
    print("Rendering annotated pages...")
    page_images = render_annotated_pages(args.pdf, metadata, args.render_dir)
    print(f"Rendered {len(page_images)} page(s) to {args.render_dir}/")

    if args.dry_run:
        prompt = build_prompt(metadata)
        print("\n" + "=" * 60)
        print("PROMPT:")
        print("=" * 60)
        print(prompt)
        print(f"\nWould send {len(page_images)} image(s) to {args.model}")
        return

    # Call AI (split by page if form is large)
    total_fields = len(metadata["fields"])
    all_labels = []

    if total_fields <= args.max_fields_per_call:
        # Single call for all pages
        prompt = build_prompt(metadata)
        print(f"Calling AI ({args.model}) with {len(page_images)} image(s)...")
        response = call_ai_vision(prompt, page_images, model=args.model)
        all_labels = parse_ai_response(response)
    else:
        # Split by page
        pages = sorted(set(f["page"] for f in metadata["fields"]))
        for pg in pages:
            pg_fields = [f for f in metadata["fields"] if f["page"] == pg]
            prompt = build_prompt(metadata, page_num=pg)
            img = page_images[pg - 1] if pg <= len(page_images) else page_images[-1]
            print(f"Calling AI for page {pg} ({len(pg_fields)} fields)...")
            response = call_ai_vision(prompt, [img], model=args.model)
            page_labels = parse_ai_response(response)
            all_labels.extend(page_labels)

    print(f"AI returned {len(all_labels)} field labels")

    # Merge labels into metadata
    missing = merge_labels(metadata, all_labels)
    if missing:
        print(f"WARNING: {len(missing)} fields not labeled by AI: {missing[:5]}")

    # Validate completeness
    empty = [f["field_name"] for f in metadata["fields"]
             if not f.get("label") or not f.get("name_en") or not f.get("description")]
    if empty:
        print(f"WARNING: {len(empty)} fields with empty labels: {empty[:5]}")

    # Save output
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"Saved: {args.output_json}")


if __name__ == "__main__":
    main()
