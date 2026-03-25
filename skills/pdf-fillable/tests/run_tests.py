#!/usr/bin/env python3
"""Regression test for make_fillable_v4.py (text-layer PDFs only)

Compares output field count and positions against expected baselines.
Run:
    cd ~/openclaw_skills
    .venv/bin/python3 -m pytest pdf-fillable/tests/run_tests.py -v
"""
import subprocess, os, json
import fitz
import pytest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(_THIS_DIR, "..", "scripts", "make_fillable_v4.py")
INPUTS = os.path.join(_THIS_DIR, "inputs")
EXPECTED = os.path.join(_THIS_DIR, "expected")
METADATA = os.path.join(_THIS_DIR, "metadata")
TMP_DIR = "/tmp/pdf-fillable-test"

# Text-layer forms only (total, text, checkbox, comb)
EXPECTED_COUNTS = {
    "DLT_คำขอโอนรับโอน": (84, 84, 0, 0),
    "บต44": (91, 81, 10, 0),
    "สปส1-03": (94, 35, 38, 21),
    "สัญญาซื้อขายรถยนต์": (47, 45, 2, 0),
    "RG013_โอนบัญชีธนาคาร": (20, 9, 11, 0),
    "ใบสมัครงาน_ไทยฮง": (395, 278, 117, 0),
    "OT_Air": (158, 132, 26, 0),
    "ror01": (100, 62, 20, 18),
}


def count_fields(pdf_path):
    """Count fields by type in a PDF."""
    doc = fitz.open(pdf_path)
    text = cb = comb = 0
    fields = []
    for page in doc:
        for w in page.widgets():
            ft = w.field_type
            if ft == fitz.PDF_WIDGET_TYPE_TEXT:
                if w.text_maxlen and w.text_maxlen > 0:
                    comb += 1
                else:
                    text += 1
            elif ft == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                cb += 1
            fields.append({
                "name": w.field_name,
                "type": ft,
                "rect": [round(x, 1) for x in w.rect],
            })
    doc.close()
    return text + cb + comb, text, cb, comb, fields


def compare_fields(expected_fields, actual_fields, tolerance=5.0):
    """Compare field positions with tolerance."""
    if len(expected_fields) != len(actual_fields):
        return False, f"field count {len(actual_fields)} != expected {len(expected_fields)}"

    def pos_key(f):
        r = f["rect"]
        # Extract page number from field name (e.g. "p1_field_1" → 1)
        name = f.get("name", "")
        page = int(name.split("_")[0][1:]) if name.startswith("p") and "_" in name else 0
        return (page, round(r[1] / 10) * 10, r[0])

    expected_sorted = sorted(expected_fields, key=pos_key)
    actual_sorted = sorted(actual_fields, key=pos_key)

    mismatches = []
    for i, (ef, af) in enumerate(zip(expected_sorted, actual_sorted)):
        label = ef.get("name", f"field[{i}]")
        for j, (ev, av) in enumerate(zip(ef["rect"], af["rect"])):
            if abs(ev - av) > tolerance:
                mismatches.append(f"{label} rect[{j}]: {av} != {ev} (diff={abs(ev-av):.1f})")
                break

    if mismatches:
        return False, "; ".join(mismatches[:5])
    return True, "OK"


def validate_metadata(metadata_path, pdf_path):
    """Validate metadata JSON against PDF fields."""
    if not os.path.exists(metadata_path):
        return True, "no metadata file (skip)"

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    issues = []
    if "form_name" not in meta:
        issues.append("missing 'form_name'")
    if "fields" not in meta or not isinstance(meta["fields"], list):
        issues.append("missing or invalid 'fields' array")
        return False, "; ".join(issues)

    required_keys = {"field_name", "type", "page", "rect"}
    for i, f in enumerate(meta["fields"]):
        for k in required_keys:
            if k not in f:
                issues.append(f"field[{i}] missing '{k}'")

    _, _, _, _, pdf_fields = count_fields(pdf_path)
    if len(meta["fields"]) != len(pdf_fields):
        issues.append(f"field count {len(meta['fields'])} != PDF {len(pdf_fields)}")

    meta_names = [f["field_name"] for f in meta["fields"]]
    pdf_names = [f["name"] for f in pdf_fields]
    if meta_names != pdf_names:
        mismatches = [(i, m, p) for i, (m, p) in enumerate(zip(meta_names, pdf_names)) if m != p]
        if mismatches:
            i, m, p = mismatches[0]
            issues.append(f"field name mismatch at [{i}]: meta='{m}' pdf='{p}'")

    if issues:
        return False, "; ".join(issues[:3])
    return True, "OK"


# ── pytest parametrized ──

@pytest.fixture(scope="session", autouse=True)
def setup_tmpdir():
    os.makedirs(TMP_DIR, exist_ok=True)
    yield
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)


def _form_ids():
    return sorted(EXPECTED_COUNTS.keys())


@pytest.mark.parametrize("name", _form_ids())
def test_field_counts(name):
    """Field counts must match expected (total, text, checkbox, comb)."""
    exp_total, exp_text, exp_cb, exp_comb = EXPECTED_COUNTS[name]
    input_path = os.path.join(INPUTS, f"{name}.pdf")
    output_path = os.path.join(TMP_DIR, f"{name}.pdf")

    assert os.path.exists(input_path), f"input not found: {input_path}"

    venv_python = os.path.join(os.path.expanduser("~"), ".openclaw", "workspace", ".venv", "bin", "python3")
    result = subprocess.run(
        [venv_python, SCRIPT, input_path, output_path],
        capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, f"script error: {result.stderr[:500]}"

    total, text, cb, comb, _ = count_fields(output_path)
    assert (total, text, cb, comb) == (exp_total, exp_text, exp_cb, exp_comb), \
        f"got ({total}, {text}, {cb}, {comb}) != expected ({exp_total}, {exp_text}, {exp_cb}, {exp_comb})"


@pytest.mark.parametrize("name", _form_ids())
def test_field_positions(name):
    """Field positions must match golden baselines within 5pt tolerance."""
    input_path = os.path.join(INPUTS, f"{name}.pdf")
    expected_path = os.path.join(EXPECTED, f"{name}.pdf")
    output_path = os.path.join(TMP_DIR, f"{name}.pdf")

    if not os.path.exists(expected_path):
        pytest.skip("no expected baseline")
    if not os.path.exists(output_path):
        pytest.skip("output not generated (run test_field_counts first)")

    _, _, _, _, expected_fields = count_fields(expected_path)
    _, _, _, _, actual_fields = count_fields(output_path)

    ok, msg = compare_fields(expected_fields, actual_fields)
    assert ok, msg


@pytest.mark.parametrize("name", _form_ids())
def test_metadata(name):
    """Metadata JSON must match PDF fields if it exists."""
    expected_path = os.path.join(EXPECTED, f"{name}.pdf")
    meta_path = os.path.join(METADATA, f"{name}.json")

    if not os.path.exists(meta_path):
        pytest.skip("no metadata file")
    if not os.path.exists(expected_path):
        pytest.skip("no expected baseline")

    ok, msg = validate_metadata(meta_path, expected_path)
    assert ok, msg


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
