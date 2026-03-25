---
name: doc-vault
description: Store and manage important documents (ID cards, house registrations, company certificates, VAT registrations) for people and companies. Retrieve stored documents for crossout without re-uploading. Track expiry dates and warn when documents are expired or stale. Use when user wants to store/update/list documents, or requests crossout of stored documents.
---

# Doc Vault

Store important documents locally so crossout can be done by name — no need to re-send files each time.

## Storage Structure

```
skills/doc-vault/
├── SKILL.md
├── vault.json            ← metadata index
└── docs/
    ├── person/
    │   └── {name}/       ← e.g. "สมชาย ใจดี"
    │       ├── id_card.pdf
    │       └── house_reg.pdf
    └── company/
        └── {name}/       ← e.g. "บริษัท ตัวอย่าง จำกัด"
            ├── cert.pdf          (หนังสือรับรอง)
            └── vat_reg.pdf       (ภ.พ.20)
```

## vault.json Schema

```json
{
  "persons": {
    "สมชาย ใจดี": {
      "nickname": "พี่ชาย",
      "documents": {
        "id_card": {
          "file": "docs/person/สมชาย ใจดี/id_card.pdf",
          "expiry": "2030-05-15",
          "added": "2026-02-11",
          "note": ""
        },
        "house_reg": {
          "file": "docs/person/สมชาย ใจดี/house_reg.pdf",
          "expiry": null,
          "added": "2026-02-11",
          "note": ""
        }
      }
    }
  },
  "companies": {
    "บริษัท ตัวอย่าง จำกัด": {
      "short_name": "Example Co.",
      "documents": {
        "cert": {
          "file": "docs/company/บริษัท ตัวอย่าง จำกัด/cert.pdf",
          "issued": "2026-01-27",
          "max_age_months": null,
          "added": "2026-02-11",
          "note": "4 pages"
        },
        "vat_reg": {
          "file": "docs/company/บริษัท ตัวอย่าง จำกัด/vat_reg.pdf",
          "expiry": null,
          "added": "2026-02-11",
          "note": "ภ.พ.20"
        }
      }
    }
  }
}
```

## Document Types

| Type | Key | Owner | Expiry |
|------|-----|-------|--------|
| บัตรประชาชน (หน้า) | `id_card` | person | มีวันหมดอายุ → `expiry` |
| บัตรประชาชน (หน้า+หลัง) | `id_card_full` | person | มีวันหมดอายุ → `expiry` |
| ทะเบียนบ้าน | `house_reg` | person | ไม่หมดอายุ |
| หนังสือรับรองบริษัท | `cert` | company | ตาม `max_age_months` ที่ผู้ใช้กำหนด (นับจาก `issued`) |
| ภ.พ.20 | `vat_reg` | company | ไม่หมดอายุ |

## Workflows

### Store Document

1. User sends PDF + บอกว่าเป็นเอกสารอะไร ของใคร/บริษัทไหน
2. Copy file to `docs/person/{name}/` or `docs/company/{name}/`
3. Update `vault.json` with metadata (expiry, issued date, etc.)
4. Confirm to user

### Update Document

1. User sends new version of existing document
2. Replace file in docs folder
3. Update metadata in `vault.json`
4. Confirm: old → new

### List Documents

Read `vault.json` and show summary with expiry status.

### Crossout from Vault

1. User requests crossout — e.g. "ขอสำเนาบัตร/ทะเบียนบ้าน สมชาย สมหญิง ขีดคร่อมว่า xxx"
2. Look up documents in `vault.json`
3. **Check expiry/age before proceeding:**
   - `id_card`/`id_card_full`: ⚠️ warn if **expired** OR **จะหมดอายุภายใน 1 เดือน** → แจ้ง user + ถามว่าจะดำเนินการต่อไหม
   - `cert`: **แจ้งอายุหนังสือรับรองทุกครั้ง** เช่น "หนังสือรับรองออกเมื่อ 27 ม.ค. 69 (อายุ 1 เดือน 3 วัน)" — ถ้า `max_age_months` ถูกกำหนดและเกิน → warn + ถาม
   - If expired/stale → warn user and ask whether to proceed
4. Build crossout commands using `pdf-crossout` skill:
   - **เอกสารส่วนบุคคล** (บัตร/ทะเบียนบ้าน): `--cert-name` = เจ้าของเอกสารคนเดียว
   - **เอกสารบริษัท** (หนังสือรับรอง/ภ.พ.20): `--cert-name` = ผู้เซ็นตามที่ user ระบุ (อาจ 1-3 คน)
   - **บัตร ปชช.**: ใช้ `--preserve-id --no-wrap` เสมอ — หลบเลข 13 หลัก (ลดมุมเป็น 20° + เลื่อนเส้นลง 25%)
   - **บัตร ปชช. ปิดทึบ sensitive data**: ถ้า user ขอปิดหมู่เลือด/ศาสนา ใช้ `--redact "ศาสนา" --redact "หมู่เลือด"` — ปิดเฉพาะค่า (value) ด้วยแถบเทา ไม่ปิดตัว label
   - **บัตร ปชช. มี 2 แบบ**: `id_card` (ด้านหน้าอย่างเดียว) กับ `id_card_full` (หน้า+หลัง)
     - **Default ใช้ด้านหน้าอย่างเดียว (`id_card`)** ยกเว้น user ระบุว่าต้องการหน้า/หลัง → ใช้ `id_card_full`
   - **ขีดคร่อมหลายคน**: ขีดคร่อมแยกทีละไฟล์ แต่ละไฟล์ `--cert-name` = เจ้าของเอกสารนั้นคนเดียว
5. **รัน sequential** (ทีละไฟล์) — ห้ามรัน parallel เพราะ OCR กิน RAM สูง
6. ส่งผลลัพธ์ทีละไฟล์ พร้อมระบุชื่อเอกสาร + เจ้าของ
7. ถ้า user ขอ print:
   - Use appropriate printer command
8. ถ้า user ขอส่ง email → ใช้ Gmail API (your-email@example.com) แนบ PDF ขีดคร่อม

### Expiry Check Logic

```python
from datetime import date, timedelta

today = date.today()

# ID card — warn if expired OR expiring within 1 month
if doc.get("expiry"):
    expiry = date.fromisoformat(doc["expiry"])
    if today > expiry:
        warn(f"⚠️ บัตรหมดอายุแล้ว! (หมดอายุ {doc['expiry']})")
    elif expiry - today <= timedelta(days=30):
        days_left = (expiry - today).days
        warn(f"⚠️ บัตรจะหมดอายุใน {days_left} วัน ({doc['expiry']})")

# Company cert — ALWAYS show age, warn if over max_age_months
if doc.get("issued"):
    issued = date.fromisoformat(doc["issued"])
    delta = today - issued
    months = delta.days // 30
    days = delta.days % 30
    info(f"📄 หนังสือรับรองออกเมื่อ {doc['issued']} (อายุ {months} เดือน {days} วัน)")
    if doc.get("max_age_months") and months > doc["max_age_months"]:
        warn(f"⚠️ เกิน {doc['max_age_months']} เดือนแล้ว!")
```

## Notes

- All paths relative to `skills/doc-vault/`
- Nicknames are optional but useful for natural language lookups
- When user says "เอกสารของพี่ชาย" → match by nickname
- When user says "เอกสารบริษัทตัวอย่าง" → match by name or short_name
- `max_age_months` for cert is not set by default — user specifies per request (e.g. "หนังสือรับรองไม่เกิน 3 เดือน")
