---
name: pdf-crossout
description: Add diagonal cross-out lines and overlay text to PDF documents. Use when a user needs to stamp, watermark, or mark PDFs with cross lines and text (e.g. for power of attorney documents, copy certification, document restrictions). Supports Thai text.
---

# PDF Cross-Out

Add parallel diagonal lines with rotated text overlay, and "สำเนาถูกต้อง" certification block to all pages of a PDF. Image-based approach (renders page → draws overlay with PIL → stamps back) for pixel-perfect results. Font: Sarabun Bold (bundled, full Thai + ASCII support).

## Dependencies

Requires `PyMuPDF`, `Pillow`, and `pytesseract` (+ system `tesseract-ocr` with Thai):

```bash
cd /path/to/workspace && .venv/bin/pip install PyMuPDF Pillow pytesseract -q
sudo apt-get install -y tesseract-ocr tesseract-ocr-tha
```

## Usage

```bash
.venv/bin/python3 scripts/crossout.py <input.pdf> <output.pdf> [options]
```

### Options

- `--text LINE` — rotated text line between parallel lines (repeatable, max 5). Font auto-sizes to ≥30% cluster width.
- `--opacity FLOAT` — 0-1 (default: 0.7)
- `--line-width INT` — parallel line width in pixels (default: 2)
- `--font-path PATH` — TTF font (default: bundled Sarabun-Bold)
- `--no-cert` — skip "สำเนาถูกต้อง" certification block
- `--cert-position` — auto|bottom-right|bottom-left|bottom-center (default: auto)
- `--cert-name NAME` — name in parentheses under signature line (repeatable for multiple signers)
- `--dpi INT` — render DPI (default: 200)
- `--quality INT` — JPEG quality 1-100 (default: 90)
- `--preserve-id` — หลบเลขประจำตัวประชาชน 13 หลัก: ลดมุมเป็น max 20° + เลื่อน center ลง 25% ของ cluster (เฉพาะบัตร ปชช.)
- `--no-wrap` — ไม่ตัดบรรทัด ยอมให้ข้อความยาวได้ถึง 150% ของ cluster width ก่อน wrap (default: wrap ที่ 70%)
- `--angle N` — กำหนดมุมหมุนเอง (default: 45°)
- `--redact FIELD` — ปิดทึบค่า sensitive field ด้วยแถบสี (repeatable). ใช้ OCR หาตำแหน่ง label แล้วปิดเฉพาะ value ที่อยู่ถัดไปทางขวา. เช่น `--redact "ศาสนา"` `--redact "หมู่เลือด"`. มี positional fallback สำหรับบัตร ปชช. (หา "Date of Birth" แล้วลงมา 1 บรรทัด) กรณี OCR อ่านภาษาไทยผิด. แถบมี min width 80px (ขยายขวา) เดาจำนวนตัวอักษรไม่ได้, สูง fix ตามขนาดบรรทัด
- `--redact-color R,G,B` — สีแถบ redact (default: 128,128,128 เทา)

### Examples

Single signer:
```bash
.venv/bin/python3 scripts/crossout.py input.pdf output.pdf \
  --text "สำหรับขึ้นทะเบียนแรงงานต่างด้าวเท่านั้น" \
  --cert-name "สมชาย ใจดี"
```

Multiple signers:
```bash
.venv/bin/python3 scripts/crossout.py input.pdf output.pdf \
  --text "สำหรับทดสอบการทำงานของ AI เท่านั้น" \
  --cert-name "สมชาย ใจดี" \
  --cert-name "สมหญิง รักไทย"
```

ID card — preserve 13-digit number:
```bash
.venv/bin/python3 scripts/crossout.py id_card.pdf output.pdf \
  --text "ใช้สำหรับประกอบการสมัครเรียนเท่านั้น" \
  --cert-name "สมชาย ใจดี" \
  --preserve-id --no-wrap
```

ID card — redact sensitive fields (ศาสนา, หมู่เลือด):
```bash
.venv/bin/python3 scripts/crossout.py id_card.pdf output.pdf \
  --text "ใช้สำหรับยกเลิกบริการเท่านั้น" \
  --cert-name "สมชาย ใจดี" \
  --preserve-id --no-wrap \
  --redact "ศาสนา" --redact "หมู่เลือด"
```

Resolve `scripts/crossout.py` relative to this skill's directory.

## Processing Pipeline

### Step 1: Render PDF → Image
- แปลงแต่ละหน้าเป็นรูปภาพด้วย PyMuPDF (default DPI 200)

### Step 2: Content Cluster Detection
- สแกนทุกแถวของภาพหา pixel สีเข้ม (threshold < 230)
- จัดกลุ่มแถวที่มีเนื้อหา (density > 5%) เป็น "content bands"
- ถ้ามีช่องว่างระหว่าง bands > 6% ของหน้า → แยกเป็น cluster ใหม่
- **กรอง noise**: ลบ cluster ที่สูง < 5% ของหน้า (ขอบ, artifact)
- **กรอง footer**: ลบ cluster สุดท้ายที่อยู่ล่างสุด 15% ของหน้า และมีขนาดเล็ก (< 30% ของ cluster ใหญ่สุด หรือ < 15% ของหน้า)

ตัวอย่างผลลัพธ์:
- บัตร ปชช. หน้า-หลังรวมหน้าเดียว → 2 clusters
- บัตร ปชช. หน้าเดียว → 1 cluster
- หนังสือรับรอง (มี footer) → 1 cluster (footer ถูกกรองออก)
- ทะเบียนบ้าน บน-ล่าง → 2 clusters

### Step 3: Header Detection
- ทำเฉพาะ cluster ใหญ่ (> 25% ของหน้า)
- สแกน 35% บนสุดของ cluster หาช่องว่าง (density < 2% ติดต่อกัน ≥ 1.5% ของ cluster height)
- ถ้าเจอช่องว่าง → ส่วนบนคือ header (ตราครุฑ, logo) → **ไม่ขีดคร่อม**
- เริ่มขีดคร่อมใต้ header เท่านั้น

### Step 4: Preserve ID (บัตร ปชช. + `--preserve-id`)
- OCR detect ประเภทเอกสาร → ถ้าเป็น `id_card`:
  - ลดมุมเป็น max 20° (จาก default 45°)
  - เลื่อน center ของ crossout ลงมา 25% ของ cluster height
- เลข 13 หลักอยู่ด้านบนของบัตร → เส้นขีดคร่อมพาดกลาง-ล่างแทน ไม่ทับเลข

### Step 5: Crossout Drawing (ทำแยกแต่ละ cluster)
- คำนวณ font size ให้ text กว้าง ≥ 30% ของ cluster width (สูงสุด 100pt)
- **`--no-wrap`**: wrap ที่ 150% ของ cluster width (ข้อความบรรทัดเดียวล้นออกนอกบัตรได้)
- **default**: wrap ที่ 70% ของ cluster width
- สร้าง band image: ข้อความ + เส้นขนาน 2 เส้น (ยาวเท่า text + padding)
- หมุนตามองศาที่กำหนด (default 45°, preserve-id ลดเป็น 20°) แล้ววาง centered บน cluster
- Opacity 70%, เส้น 2px

### Step 6: Document Type Detection (OCR)
- ดึงข้อความจาก PDF text layer ก่อน (PyMuPDF)
- ถ้าไม่มี text layer (เอกสาร scan) → ใช้ **Tesseract OCR** (tha+eng)
- ตรวจ keyword เพื่อจำแนกประเภท:
  - `บัตรประจำตัวประชาชน` / `National ID Card` → **บัตร ปชช.** (personal)
  - `ทะเบียนบ้าน` / `รายการบุคคล` → **ทะเบียนบ้าน** (personal)
  - อื่นๆ → **เอกสารบริษัท** (corporate)

### Step 7: Owner Detection (เอกสารส่วนบุคคลเท่านั้น)
- **บัตร ปชช.**: หาชื่อเจ้าของจากทั้งหน้า
- **ทะเบียนบ้าน**: หาชื่อเฉพาะจากส่วน "รายการบุคคล" (ไม่สนเจ้าบ้าน/ผู้ขอเลขบ้าน)
- Matching 3 ระดับ:
  1. **Exact**: ชื่อเต็ม (ลบคำนำหน้า นาย/นาง/นางสาว + ลบช่องว่าง) ตรงเป๊ะ
  2. **Fuzzy word**: ชื่อ/นามสกุล (≥ 3 ตัวอักษร) ปรากฏในข้อความ
  3. **Consonant fuzzy**: ตัดสระ/วรรณยุกต์ออก เทียบเฉพาะพยัญชนะ 4 ตัวแรก (แก้ปัญหา OCR อ่านสระผิด เช่น "สมชย" match "สมชาย")

### Step 8: Certification Block (สำเนาถูกต้อง)

**เอกสารส่วนบุคคล** (บัตร ปชช. / ทะเบียนบ้าน):
- เจ้าของเอกสาร (จาก OCR) เซ็นต์ **คนเดียว**
- วางใต้ cluster สุดท้าย

**เอกสารบริษัท** (หนังสือรับรอง ฯลฯ):
- **ทุกคน** เซ็นต์ด้วยกัน เรียงตามจำนวนคน
- หาตำแหน่งว่างด้วย empty band scan
- Respects 2cm bottom margin

แต่ละ cert block ประกอบด้วย:
- "สำเนาถูกต้อง" text
- เส้นลายเซ็นต์ (generous space for signing)
- (ชื่อ) ในวงเล็บ
- วันที่ `___/___/___`

### Step 9: Output
- แปลงกลับเป็น JPEG (quality 90) แล้วแทนที่หน้าเดิมใน PDF
- บีบอัด + garbage collect

## Bug Fixes

### 2026-02-11: Crossout text ตกขอบหน้า (overflow on small clusters)
- **ปัญหา**: หน้าที่มี content น้อย (เช่น หนังสือรับรองหน้าสุดท้าย) ข้อความขีดคร่อมหมุน 45° แล้วล้นขอบหน้า
- **แก้ไข**: ใช้ diagonal ของ cluster (`sqrt(cw² + ch²)`) แทน diagonal ของทั้งหน้า (`sqrt(W² + H²)`) + clamp paste position ไม่ให้เกินขอบหน้า

### 2026-02-11: Cert block ชิดขอบขวา (personal docs with 1 signer)
- **ปัญหา**: เอกสารส่วนบุคคล (บัตร ปชช./ทะเบียนบ้าน) ที่ส่ง `--cert-name` มา 1 ชื่อ ไม่เข้าเงื่อนไข personal path (เดิมต้อง `len(names) >= 2`) ทำให้ไปใช้ corporate path ที่วาง cert block ด้าน bottom-right
- **แก้ไข**: ลบเงื่อนไข `len(names) >= 2` ออก — ให้เข้า personal path ทุกกรณีที่เป็น id_card/house_reg + center cert block กลางหน้า (`W // 2`) แทนกลาง cluster

### 2026-02-13: Preserve ID — หลบเลข 13 หลักบนบัตร ปชช.
- **ปัญหา**: ขีดคร่อมบัตร ปชช. แล้วเส้นทับเลขประจำตัว 13 หลัก ซึ่งอยู่ด้านบนของบัตร
- **แก้ไข**: เพิ่ม `--preserve-id` — detect ว่าเป็นบัตร ปชช. (OCR) แล้ว:
  - ลดมุมเป็น max 20° (เส้นเฉียงน้อยลง ไม่พุ่งขึ้นไปถึงเลข)
  - เลื่อน center ลง 25% ของ cluster height (เส้นพาดกลาง-ล่างบัตร)
- เพิ่ม `--no-wrap` — บรรทัดเดียว (wrap ที่ 150% แทน 70%) ข้อความล้นออกนอกบัตรได้
- เพิ่ม `--angle N` — กำหนดมุมหมุนเอง

### Step 10: Redact Sensitive Fields (`--redact`)

1. **OCR text match**: Tesseract TSV → merge ตัวอักษรใกล้กัน → หา label (เช่น "ศาสนา") → ปิดทึบ value ทางขวา
2. **Positional fallback** (บัตร ปชช.): ถ้า OCR อ่าน Thai ผิด (เช่น "ศา"→"ถี") → หา "Date of Birth" (English, OCR อ่านได้แม่น) → ศาสนาอยู่บรรทัดถัดลงมา ~30px
3. **Filter artifacts**: ขอบบัตร ("=", "|") ถูกกรองออก (x > 40% ของภาพ + ต้องมี Thai/Latin char)
4. **Normalize rectangle**:
   - สูง fix 22px (ไม่ใช้ OCR box height ที่สูงเกินจริง)
   - กว้างขั้นต่ำ 80px ขยายไปทางขวาเท่านั้น (ไม่ชิด label)
   - เดาจำนวนตัวอักษรไม่ได้
5. Redact ก่อน crossout → แถบอยู่ใต้เส้นขีดคร่อม

## Performance

- Image-only PDFs (scan) ต้องใช้ Tesseract OCR → **ช้ามาก** (~30-60 วินาทีต่อไฟล์)
- **ห้ามรัน parallel มากกว่า 2 jobs** — OCR + PIL กิน RAM สูง รันพร้อม 6 ตัวจะ hang/OOM
- รันทีละตัว (sequential) เสถียรที่สุด ใช้เวลา ~30s/file
- PDFs ที่มี text layer จะเร็วกว่ามาก (ไม่ต้อง OCR)

## Notes

- Font: Sarabun Bold — supports full Thai glyphs + ASCII
- Image-based: original PDF is rasterized at specified DPI, overlay drawn as JPEG, then re-embedded as image PDF
- Output uses JPEG compression (quality 90) — keeps file size similar to or smaller than input
- For archival quality, use `--dpi 300 --quality 95`
- OCR requires `tesseract-ocr` and `tesseract-ocr-tha` system packages
