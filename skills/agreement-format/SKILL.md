---
name: agreement-format
description: รูปแบบและ layout สำหรับสร้างเอกสารสัญญา/ข้อตกลง/หนังสือมอบอำนาจ เป็น PDF ภาษาไทย ผ่าน Google Docs API + PyMuPDF ใช้เมื่อต้องการสร้างเอกสารทางการที่ต้องลงลายเซ็น
version: 1.0.1
---

# Agreement Format — รูปแบบเอกสารสัญญา/ข้อตกลง

## เมื่อไหร่ใช้ Skill นี้
- ต้องการสร้างเอกสารสัญญา, ข้อตกลง, หนังสือมอบอำนาจ, หรือเอกสารทางการอื่นๆ ที่ต้องลงลายเซ็น
- ต้องการ PDF ที่พิมพ์ได้ ฟอนต์ภาษาไทยถูกต้อง

## ใช้ร่วมกับ
- **standard-agreement-form** — ถ้าเป็นเอกสารในนามบริษัท ต้องอ่าน skill standard-agreement-form ด้วยเสมอ

## เครื่องมือ
- **Google Docs API** — สร้างเนื้อหาและจัดฟอร์แมต
- **Google Drive API** — export PDF
- **PyMuPDF (fitz)** — เพิ่มเลขหน้า + ตรวจสอบ PDF output
- ❌ **ห้ามใช้ weasyprint** สำหรับเอกสารภาษาไทย (ตัว ำ render ผิด)

## ฟอนต์
- ใช้ **Sarabun** (Google Fonts) เท่านั้น
- ❌ ห้ามใช้ "TH Sarabun New" ใน API (ไม่มีใน Google Fonts → fallback ผิด)
- Body: **14pt** / Title: **16pt bold**
- เลขหน้า: **10pt Sarabun** (ใช้ไฟล์ `~/workspace/fonts/Sarabun-Regular.ttf` กับ PyMuPDF)

## Page Layout
- A4 (596×842pt)
- Margins: Top=56pt, Bottom=42pt, Left=71pt, Right=46pt
- Line spacing: **100 (Single)**
- Text alignment: **JUSTIFIED** (ชิดซ้าย-ขวา)

## โครงสร้างเอกสาร

### ส่วนหัว
- Title: 16pt bold, **center**
- วันที่: **right-aligned**
- เรื่อง + ข้อตกลงว่าด้วย...: **bold ทั้งบรรทัด**

### ส่วนคู่สัญญา
- เริ่มด้วย "\tสัญญานี้เป็นข้อตกลงซึ่งจัดทำขึ้น"
- "โดยและระหว่าง" — **bold**
- **(1)** ฝ่ายที่ 1 + ที่อยู่สำนักงาน + ตัวแทน + ตำแหน่ง → "ฝ่ายหนึ่ง กับ"
- **(2)** ฝ่ายที่ 2 + ที่อยู่ → "อีกฝ่ายหนึ่ง"

### เนื้อหา
- หัวข้อแต่ละข้อ: **bold**
- ย่อหน้า: ใช้ `\t` (tab) → indent ~x=107pt
- ข้อย่อย (ก)(ข)(ค): ใช้ `\t` → indent ตรงกับเนื้อหา
- ระยะห่างระหว่างข้อ: เว้น **1 บรรทัดว่าง** (`\n\n` ในข้อความ)
- ถ้าข้อย่อยยาว wrap → ตั้ง `indentStart: 36pt`, `indentFirstLine: 0pt`

### รายการ 2 คอลัมน์
- ใช้ **Google Docs table** (ไม่ใช่ tab — proportional font ทำให้ไม่ตรง)
- ซ่อนเส้นขอบ: border color=white, width=0
- ตั้ง paddingLeft ให้ตรง indent ที่ต้องการ

### กล่องลายเซ็น
- ใช้ **table 2×2** (ไม่ใช่ text)
- Row 1: ฝ่ายที่ 1 (ซ้าย) | ฝ่ายที่ 2 (ขวา)
- Row 2: พยาน 1 (ซ้าย) | พยาน 2 (ขวา)
- ซ่อนเส้นขอบ, **center-align**, line spacing=100
- ช่องว่างระหว่าง Row 1-2: paddingTop=18pt บน Row 2
- ย่อหน้าสุดท้ายก่อน sig table: `spaceBelow: 36pt`
- **Label หลังลงชื่อ**: ใช้คำสั้น เช่น "กรรมการ", "พนักงาน" — ไม่ใช่ "ผู้แทนบริษัท" หรือ "พนักงานผู้รับบัตรเสริม" (คำยาวจะตกบรรทัด)
- **ถ้า label ยาวเกิน**: แยกเป็นบรรทัดใหม่ใต้เส้นลงชื่อ

### เลขหน้า
- ใช้ PyMuPDF เพิ่มหลัง export PDF จาก Google Docs
- Format: **"- 1/3 -"** กึ่งกลางด้านล่าง
- ฟอนต์: **Sarabun 10pt** (ไฟล์ `~/workspace/fonts/Sarabun-Regular.ttf`)
- ตำแหน่ง: y = rect.height - 25, x = กึ่งกลาง

### ส่วนปิด
- "หนังสือข้อตกลงฉบับนี้ทำขึ้นเป็นสองฉบับ... เก็บรักษาไว้ฝ่ายละหนึ่งฉบับ"

## เทคนิคสำคัญ

### Trailing Paragraph
Google Docs มี paragraph ว่างท้ายเอกสารเสมอ (ลบไม่ได้) → shrink เป็น fontSize=1pt, lineSpacing=100, space=0

### Text Index เมื่อมี Table
❌ ห้ามค้นหา text จาก top-level paragraphs เท่านั้น (index จะเลื่อน)
✅ ใช้ recursive walk ลงไปใน table cells → เก็บ (startIndex, endIndex, content) ทุก text run

### ลำดับการสร้าง
1. Clear เนื้อหาเดิม (หรือสร้าง Doc ใหม่)
2. Insert body text (ส่วน 1)
3. Insert table (ถ้ามี) ที่ endOfSegment
4. Insert body text (ส่วน 2)
5. Insert signature table (2×2)
6. Apply formatting ทั้งหมดใน **batch เดียว**
7. Export PDF
8. เพิ่มเลขหน้าด้วย PyMuPDF
9. แชร์สิทธิ์ Google Doc (ตาม TOOLS.md)

### Google Docs vs PDF
- ❌ Google Docs API **ไม่รองรับ** การแก้ named style (NORMAL_TEXT) — browser จะแสดงผลต่างจาก PDF
- ✅ **PDF เป็นฉบับจริง** สำหรับลงนาม — Google Doc ไว้ reference เนื้อหาเท่านั้น
- ตรวจสอบ: ทุกย่อหน้าต้องมี explicit font + size + alignment (ไม่พึ่ง INHERITED)

## Self-Test Checklist ก่อนนำเสนอ

❗ **ต้องทำทุกข้อก่อนส่งให้คนตรวจ** — ห้ามส่งโดยไม่ test

1. ✅ ตรวจ PDF — เปิดอ่านเนื้อหาทุกหน้าผ่าน PyMuPDF
2. ✅ ตรวจจำนวนหน้า — ต้องเท่ากับที่คาดหวัง
3. ✅ ตรวจเลขหน้า — ฟอนต์ถูกต้อง ไม่เป็นกล่อง □
4. ✅ ตรวจลายเซ็น — label ไม่ตกบรรทัด ชื่อ-นามสกุลถูกต้อง (จาก vault)
5. ✅ ตรวจคำนำหน้า/ตำแหน่ง — ตรงกับ vault
6. ✅ ตรวจ alignment — เนื้อหา JUSTIFIED, หัวเรื่อง CENTER, วันที่ END
7. ✅ ตรวจ Google Doc — เปิด API verify ทุก paragraph มี explicit formatting
8. ✅ ตรวจสิทธิ์ — แชร์ให้ผู้เกี่ยวข้องแล้ว
9. ✅ เทียบ PDF กับ Google Doc — เนื้อหาตรงกัน

## บทเรียน

| ปัญหา | วิธีแก้ |
|--------|---------|
| ฟอนต์เพี้ยน Type3/Tahoma | ใช้ "Sarabun" ไม่ใช่ "TH Sarabun New" |
| ตัวหนาผิดตำแหน่ง | ค้นหา text รวม table cells ด้วย |
| ล้น 3 หน้า | shrink trailing paragraph เป็น 1pt |
| ำ เป็น ;า | ใช้ Google Docs API แทน weasyprint |
| Tab ไม่ตรง 2 คอลัมน์ | ใช้ table แทน tab |
| บรรทัด wrap ไม่ตรง | ตั้ง indentStart + indentFirstLine |
| เลขหน้าเป็น □□□ | NotoSansThai ไม่มีตัวเลข → ใช้ Sarabun TTF |
| label ลายเซ็นตกบรรทัด | ใช้คำสั้น เช่น "กรรมการ" แทน "ผู้แทนบริษัท" |
| Google Doc ดูต่างจาก PDF | ข้อจำกัด API — ใช้ PDF เป็นฉบับจริง |
| ชื่อ-นามสกุลผิด | ดึงจาก vault.json เสมอ ห้ามแปลจาก metadata |

## Script อ้างอิง
- `~/workspace/gen_agreement_v6_gdocs.py` (ตัวอย่างล่าสุด)
- `~/openclaw_skills/agreement-form/patch_v5_final2.py` (ตัวอย่างเดิม)
