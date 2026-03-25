#!/usr/bin/env python3
"""
v5 final2: 
- Date → 13 มีนาคม 2569 (both)
- อริตชา: IT items in 2-column table
"""
import json, os, io, time
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from googleapiclient.http import MediaIoBaseDownload

TOKENS_DIR = os.path.expanduser('~/.openclaw/workspace/google_tokens')
WORKSPACE = os.path.expanduser('~/.openclaw/workspace')
DOC_IDS = {
    'airada': '1bVx5CjZnCPn7yAdEAbmOv8Sfs1SYyArk4hPkLOo5TuA',
    'aritcha': '11G2SY1U-QNzfMzmH9vNOWy_z29F3VBqH0Pu56PyjKgg',
}
DATE_TEXT = '13  มีนาคม  2569'


def get_creds(user_id='6871355627'):
    token_file = os.path.join(TOKENS_DIR, f'{user_id}.json')
    with open(token_file) as f:
        t = json.load(f)
    creds = Credentials(
        token=t['token'], refresh_token=t['refresh_token'],
        token_uri=t['token_uri'], client_id=t['client_id'],
        client_secret=t['client_secret']
    )
    if creds.expired:
        creds.refresh(Request())
        t['token'] = creds.token
        with open(token_file, 'w') as f:
            json.dump(t, f, indent=2)
    return creds


def export_pdf(drive_svc, doc_id, output_path):
    request = drive_svc.files().export_media(fileId=doc_id, mimeType='application/pdf')
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    with open(output_path, 'wb') as f:
        f.write(fh.getvalue())
    print(f"  PDF exported: {output_path}")


# ============================================
# BODY TEXT TEMPLATES
# ============================================

BODY_COMMON_BEFORE = """หนังสือข้อตกลงการใช้บัตรเสริมบัตรเครดิตของบริษัท

วันที่  {date}

เรื่อง\tข้อตกลงว่าด้วยการใช้บัตรเสริมบัตรเครดิตของบริษัท

\tบริษัท ลิ้งซ์จิสติกส์ อินเตอร์ เฟรท จำกัด ซึ่งต่อไปในหนังสือฉบับนี้เรียกว่า "บริษัท"
ระหว่าง
\t{employee_name}  ซึ่งต่อไปในหนังสือฉบับนี้เรียกว่า "พนักงาน"

\tโดยที่บริษัทมีความประสงค์จะออกบัตรเสริมบัตรเครดิตจากบัตรหลักของ นางสาวชนิลรัตน์ วิอังศุธร ให้แก่พนักงาน เพื่อใช้ในกิจการของบริษัท โดยมีวัตถุประสงค์ดังนี้
\t1.  เพื่อเพิ่มความคล่องตัวในการปฏิบัติงาน
\t2.  เพื่อเพิ่มประสิทธิภาพในการปฏิบัติงาน

\tคู่สัญญาทั้งสองฝ่ายจึงตกลงทำข้อตกลงไว้ดังมีข้อความต่อไปนี้

ข้อ 1  ขอบเขตการใช้จ่าย
\tพนักงานจะใช้จ่ายผ่านบัตรเสริมได้เฉพาะเมื่อได้รับคำสั่งหรือการอนุมัติจากผู้บริหารแล้วเท่านั้น โดยค่าใช้จ่ายที่ได้รับอนุญาต ได้แก่
"""

# Section1 items for ไอรดา (simple text)
SECTION1_AIRADA = """\t(ก)  ค่าจองที่พัก
\t(ข)  ค่าตั๋วเครื่องบิน
\t(ค)  ค่าซื้อของขวัญสำหรับมอบแก่ลูกค้า
\t(ง)  ค่าใช้จ่ายอื่นใดที่ได้รับอนุมัติจากผู้บริหารเป็นลายลักษณ์อักษร"""

# Section1 for อริตชา - part before IT table
SECTION1_ARITCHA_BEFORE = """\t(ก)  ค่าใช้จ่ายเกี่ยวกับระบบ IT ได้แก่
"""

# IT items for 2-column table (4 rows x 2 cols)
IT_TABLE_DATA = [
    ['1. GitHub', '5. Claude AI'],
    ['2. Google Workspace - MST', '6. TRUE - LYNX'],
    ['3. Google Workspace - LHD', '7. TRUE - LEX'],
    ['4. Amazon', ''],
]

# Section1 for อริตชา - part after IT table
SECTION1_ARITCHA_AFTER = """\t(ข)  ค่าใช้จ่ายอื่นใดที่ได้รับอนุมัติจากผู้บริหารเป็นลายลักษณ์อักษร"""


BODY_AFTER_SECTION1 = """

ข้อ 2  การตั้งเบิกและการชำระเงิน
\tภายหลังการใช้งานบัตรเครดิตทุกครั้ง พนักงานจะต้องติดตามและรวบรวมเอกสาร ได้แก่ สลิปการโอน ใบเสร็จรับเงิน/ใบกำกับภาษีในนามบริษัทฯ และเอกสารประกอบทุกรายการให้แก่พนักงานธุรการ ภายใน 3 วัน นับจากวันใช้บัตรเครดิต และพนักงานธุรการ จะตั้งเบิกล่วงหน้า 7 วัน ก่อนรอบการชำระเงินของบัตรเครดิต เพื่อขออนุมัติ หากไม่สามารถดำเนินการได้ภายในกำหนดเวลาดังกล่าว พนักงานจะต้องชี้แจงเหตุผลและขอขยายเวลาต่อหัวหน้างาน โดยจะถือว่าการตั้งเบิกสมบูรณ์ก็ต่อเมื่อได้รับการอนุมัติจากหัวหน้างานแล้วเท่านั้น
\tบริษัทจะโอนเงินค่าใช้จ่ายไปยังบัญชีที่กำหนด เพื่อชำระตรงตามรอบการชำระเงินของบัตรเครดิต

ข้อ 3  การรายงานและการตรวจสอบ
\tพนักงานมีหน้าที่ติดตามและจัดส่งรายงานการใช้จ่าย (Statement) ของแต่ละรอบบิลให้แก่ฝ่ายบัญชี พร้อมตรวจสอบยอดใช้จ่ายให้ถูกต้องครบถ้วน หากตรวจพบรายการที่ไม่ถูกต้อง พนักงานต้องรายงานให้บริษัทหรือสถาบันผู้ออกบัตรเครดิตทราบโดยทันที เพื่อดำเนินการแก้ไขต่อไป

ข้อ 4  ข้อห้ามและบทลงโทษ
\tห้ามมิให้พนักงานใช้บัตรเสริมเพื่อค่าใช้จ่ายส่วนตัว หรือค่าใช้จ่ายใดๆ ที่มิได้รับอนุมัติตามระเบียบของบริษัท หากตรวจพบว่ามีการฝ่าฝืน ให้ถือว่าเป็นการกระทำทุจริตต่อหน้าที่ บริษัทมีสิทธิ์ดำเนินการดังต่อไปนี้
\t(ก)  เลิกจ้างพนักงานโดยไม่จ่ายค่าชดเชยใดๆ ทั้งสิ้น
\t(ข)  เรียกร้องค่าเสียหาย และ/หรือ ดำเนินคดีตามกฎหมายทั้งทางแพ่งและทางอาญา
\t(ค)  หักเงินจากค่าจ้างงวดล่าสุดของพนักงาน เพื่อชำระค่าใช้จ่ายที่มิชอบดังกล่าว ทั้งนี้เพื่อมิให้เกิดดอกเบี้ยเพิ่มเติม โดยพนักงานให้ความยินยอมไว้ ณ ที่นี้

ข้อ 5  การเก็บรักษาบัตรและข้อมูลบัตร
\tพนักงานต้องเก็บรักษาบัตรเสริมไว้ในที่ปลอดภัย รวมถึงรักษาข้อมูลของบัตร อันได้แก่ หมายเลขบัตร รหัส CVV และวันหมดอายุ ไว้เป็นความลับอย่างเคร่งครัด ห้ามมิให้ผู้อื่นยืมใช้บัตร หรือเปิดเผยข้อมูลบัตรแก่บุคคลภายนอกโดยเด็ดขาด

ข้อ 6  การคืนบัตร
\tเมื่อพนักงานพ้นสภาพการเป็นพนักงาน ไม่ว่าจะด้วยการลาออก เลิกจ้าง หรือเหตุอื่นใด รวมถึงกรณีที่บริษัทเรียกคืนบัตร พนักงานต้องส่งมอบบัตรเสริมคืนแก่บริษัทภายใน 3 วันทำการ ทั้งนี้ พนักงานต้องรับผิดชอบค่าใช้จ่ายที่เกิดขึ้นก่อนวันส่งคืนบัตร เฉพาะส่วนที่มิเกี่ยวข้องกับกิจการของบริษัท

ข้อ 7  กรณีบัตรสูญหายหรือถูกโจรกรรม
\tหากบัตรเสริมสูญหายหรือถูกโจรกรรม พนักงานต้องแจ้งบริษัทและสถาบันผู้ออกบัตรเครดิตทราบโดยทันที หากเกิดความเสียหายอันเนื่องมาจากความล่าช้าในการแจ้ง พนักงานต้องรับผิดชอบค่าใช้จ่ายที่เกิดขึ้นทั้งหมด

ข้อ 8  สิทธิ์ในการยกเลิกบัตร
\tบริษัทสงวนสิทธิ์ในการยกเลิกบัตรเสริมได้ทุกเมื่อ โดยไม่จำต้องแจ้งเหตุผลล่วงหน้า

ข้อ 9  การรับทราบและให้ความยินยอม
\tพนักงานขอรับรองว่าได้อ่านและเข้าใจข้อความในหนังสือข้อตกลงฉบับนี้โดยละเอียดครบถ้วนแล้ว และตกลงยินยอมปฏิบัติตามข้อกำหนดทุกประการ

\tหนังสือข้อตกลงฉบับนี้ทำขึ้นเป็นสองฉบับ มีข้อความถูกต้องตรงกัน คู่สัญญาทั้งสองฝ่ายได้อ่านและเข้าใจข้อความโดยตลอดดีแล้ว จึงลงลายมือชื่อไว้เป็นหลักฐานต่อหน้าพยาน
"""

SIG_DATA = [
    ['ลงชื่อ__________________________ผู้มอบบัตร\n( นางสาวชนิลรัตน์  วิอังศุธร )', None],  # [1] filled per doc
    ['ลงชื่อ__________________________พยาน\n( นางสาวพรปรียา  ศักย์สิริภากร )',
     'ลงชื่อ__________________________พยาน\n( นางสาวนฐมณ  มงคลนภัทร์ )'],
]


def extract_all_text_with_indices(doc):
    """Extract all text runs with their document indices, including table cells."""
    runs = []
    def walk(elements):
        for elem in elements:
            if 'paragraph' in elem:
                for run in elem['paragraph'].get('elements', []):
                    if 'textRun' in run:
                        si = run.get('startIndex', 0)
                        ei = run.get('endIndex', 0)
                        runs.append((si, ei, run['textRun']['content']))
            if 'table' in elem:
                for row in elem['table']['tableRows']:
                    for cell in row['tableCells']:
                        walk(cell.get('content', []))
    walk(doc['body']['content'])
    runs.sort(key=lambda x: x[0])
    return runs


def find_text_index(runs, needle, start_doc_idx=0):
    """Find the document index of needle by searching through all runs."""
    # Build concatenated text mapping
    for si, ei, content in runs:
        if si < start_doc_idx:
            continue
        idx = content.find(needle)
        if idx >= 0:
            return si + idx
    return None


def apply_common_formatting(docs_svc, doc_id, full_text_unused, end_idx, doc):
    """Apply formatting that's common to both documents."""
    runs = extract_all_text_with_indices(doc)

    def fpos(needle, start=0):
        result = find_text_index(runs, needle, start)
        return result if result is not None else None

    fmt = []

    # Page margins
    fmt.append({
        'updateDocumentStyle': {
            'documentStyle': {
                'marginTop': {'magnitude': 56, 'unit': 'PT'},
                'marginBottom': {'magnitude': 42, 'unit': 'PT'},
                'marginLeft': {'magnitude': 71, 'unit': 'PT'},
                'marginRight': {'magnitude': 46, 'unit': 'PT'},
            },
            'fields': 'marginTop,marginBottom,marginLeft,marginRight'
        }
    })

    # Default font: Sarabun 14pt
    fmt.append({
        'updateTextStyle': {
            'range': {'startIndex': 1, 'endIndex': end_idx},
            'textStyle': {
                'fontSize': {'magnitude': 14, 'unit': 'PT'},
                'weightedFontFamily': {'fontFamily': 'Sarabun'}
            },
            'fields': 'fontSize,weightedFontFamily'
        }
    })

    # Line spacing
    fmt.append({
        'updateParagraphStyle': {
            'range': {'startIndex': 1, 'endIndex': end_idx},
            'paragraphStyle': {
                'alignment': 'START',
                'lineSpacing': 100,
            },
            'fields': 'alignment,lineSpacing'
        }
    })

    # Title: 16pt bold centered
    title = 'หนังสือข้อตกลงการใช้บัตรเสริมบัตรเครดิตของบริษัท'
    pos = fpos(title)
    if pos:
        fmt.append({
            'updateTextStyle': {
                'range': {'startIndex': pos, 'endIndex': pos + len(title)},
                'textStyle': {'bold': True, 'fontSize': {'magnitude': 16, 'unit': 'PT'}},
                'fields': 'bold,fontSize'
            }
        })
        fmt.append({
            'updateParagraphStyle': {
                'range': {'startIndex': pos, 'endIndex': pos + len(title)},
                'paragraphStyle': {'alignment': 'CENTER'},
                'fields': 'alignment'
            }
        })

    # Date: right-aligned
    date_full = f'วันที่  {DATE_TEXT}'
    pos = fpos(date_full)
    if pos:
        fmt.append({
            'updateParagraphStyle': {
                'range': {'startIndex': pos, 'endIndex': pos + len(date_full)},
                'paragraphStyle': {'alignment': 'END'},
                'fields': 'alignment'
            }
        })

    # Bold "เรื่อง" full line
    subject_text = 'เรื่อง\tข้อตกลงว่าด้วยการใช้บัตรเสริมบัตรเครดิตของบริษัท'
    pos = fpos(subject_text)
    if pos:
        fmt.append({
            'updateTextStyle': {
                'range': {'startIndex': pos, 'endIndex': pos + len(subject_text)},
                'textStyle': {'bold': True},
                'fields': 'bold'
            }
        })

    # Bold "ระหว่าง"
    pos = fpos('ระหว่าง')
    if pos:
        fmt.append({
            'updateTextStyle': {
                'range': {'startIndex': pos, 'endIndex': pos + len('ระหว่าง')},
                'textStyle': {'bold': True},
                'fields': 'bold'
            }
        })

    # Bold ข้อ headers
    for header in [
        'ข้อ 1  ขอบเขตการใช้จ่าย',
        'ข้อ 2  การตั้งเบิกและการชำระเงิน',
        'ข้อ 3  การรายงานและการตรวจสอบ',
        'ข้อ 4  ข้อห้ามและบทลงโทษ',
        'ข้อ 5  การเก็บรักษาบัตรและข้อมูลบัตร',
        'ข้อ 6  การคืนบัตร',
        'ข้อ 7  กรณีบัตรสูญหายหรือถูกโจรกรรม',
        'ข้อ 8  สิทธิ์ในการยกเลิกบัตร',
        'ข้อ 9  การรับทราบและให้ความยินยอม',
    ]:
        pos = fpos(header)
        if pos:
            fmt.append({
                'updateTextStyle': {
                    'range': {'startIndex': pos, 'endIndex': pos + len(header)},
                    'textStyle': {'bold': True},
                    'fields': 'bold'
                }
            })

    # Find ALL tables
    tables = []
    for elem in doc['body']['content']:
        if 'table' in elem:
            tables.append(elem)

    # Format signature table (last table)
    if tables:
        sig_table = tables[-1]
        sig_start = sig_table.get('startIndex', 0)
        sig_end = sig_table.get('endIndex', 0)

        # Hide borders
        fmt.append({
            'updateTableCellStyle': {
                'tableRange': {
                    'tableCellLocation': {
                        'tableStartLocation': {'index': sig_start},
                        'rowIndex': 0, 'columnIndex': 0
                    },
                    'rowSpan': 2, 'columnSpan': 2
                },
                'tableCellStyle': {
                    'borderTop': {'width': {'magnitude': 0, 'unit': 'PT'}, 'dashStyle': 'SOLID', 'color': {'color': {'rgbColor': {'red': 1, 'green': 1, 'blue': 1}}}},
                    'borderBottom': {'width': {'magnitude': 0, 'unit': 'PT'}, 'dashStyle': 'SOLID', 'color': {'color': {'rgbColor': {'red': 1, 'green': 1, 'blue': 1}}}},
                    'borderLeft': {'width': {'magnitude': 0, 'unit': 'PT'}, 'dashStyle': 'SOLID', 'color': {'color': {'rgbColor': {'red': 1, 'green': 1, 'blue': 1}}}},
                    'borderRight': {'width': {'magnitude': 0, 'unit': 'PT'}, 'dashStyle': 'SOLID', 'color': {'color': {'rgbColor': {'red': 1, 'green': 1, 'blue': 1}}}},
                    'paddingTop': {'magnitude': 4, 'unit': 'PT'},
                    'paddingBottom': {'magnitude': 4, 'unit': 'PT'},
                },
                'fields': 'borderTop,borderBottom,borderLeft,borderRight,paddingTop,paddingBottom'
            }
        })

        # Center text in sig table
        fmt.append({
            'updateParagraphStyle': {
                'range': {'startIndex': sig_start, 'endIndex': sig_end},
                'paragraphStyle': {'alignment': 'CENTER', 'lineSpacing': 100},
                'fields': 'alignment,lineSpacing'
            }
        })

        # Add space between row 1 (ผู้มอบ/รับบัตร) and row 2 (พยาน)
        fmt.append({
            'updateTableCellStyle': {
                'tableRange': {
                    'tableCellLocation': {
                        'tableStartLocation': {'index': sig_start},
                        'rowIndex': 1, 'columnIndex': 0
                    },
                    'rowSpan': 1, 'columnSpan': 2
                },
                'tableCellStyle': {
                    'paddingTop': {'magnitude': 18, 'unit': 'PT'},
                },
                'fields': 'paddingTop'
            }
        })

        # Space before sig table
        last_para_before = None
        for elem in doc['body']['content']:
            if 'paragraph' in elem:
                ei = elem.get('endIndex', 0)
                if ei <= sig_start:
                    last_para_before = elem
        if last_para_before:
            si = last_para_before.get('startIndex', 0)
            ei = last_para_before.get('endIndex', 0)
            fmt.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': si, 'endIndex': ei},
                    'paragraphStyle': {'spaceBelow': {'magnitude': 36, 'unit': 'PT'}},
                    'fields': 'spaceBelow'
                }
            })

    # Shrink trailing empty paragraph
    trailing_para = None
    for elem in doc['body']['content']:
        if 'paragraph' in elem:
            trailing_para = elem
    if trailing_para and tables:
        sig_end = tables[-1].get('endIndex', 0)
        tp_si = trailing_para.get('startIndex', 0)
        tp_ei = trailing_para.get('endIndex', 0)
        if tp_si >= sig_end:
            fmt.append({
                'updateTextStyle': {
                    'range': {'startIndex': tp_si, 'endIndex': tp_ei},
                    'textStyle': {'fontSize': {'magnitude': 1, 'unit': 'PT'}},
                    'fields': 'fontSize'
                }
            })
            fmt.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': tp_si, 'endIndex': tp_ei},
                    'paragraphStyle': {
                        'lineSpacing': 100,
                        'spaceAbove': {'magnitude': 0, 'unit': 'PT'},
                        'spaceBelow': {'magnitude': 0, 'unit': 'PT'},
                    },
                    'fields': 'lineSpacing,spaceAbove,spaceBelow'
                }
            })

    # Format IT table if present (not the last one = sig table)
    if len(tables) >= 2:
        it_table = tables[0]  # first table = IT items
        it_start = it_table.get('startIndex', 0)
        it_end = it_table.get('endIndex', 0)
        n_rows = len(it_table['table']['tableRows'])
        n_cols = it_table['table']['columns']

        # Hide borders
        fmt.append({
            'updateTableCellStyle': {
                'tableRange': {
                    'tableCellLocation': {
                        'tableStartLocation': {'index': it_start},
                        'rowIndex': 0, 'columnIndex': 0
                    },
                    'rowSpan': n_rows, 'columnSpan': n_cols
                },
                'tableCellStyle': {
                    'borderTop': {'width': {'magnitude': 0, 'unit': 'PT'}, 'dashStyle': 'SOLID', 'color': {'color': {'rgbColor': {'red': 1, 'green': 1, 'blue': 1}}}},
                    'borderBottom': {'width': {'magnitude': 0, 'unit': 'PT'}, 'dashStyle': 'SOLID', 'color': {'color': {'rgbColor': {'red': 1, 'green': 1, 'blue': 1}}}},
                    'borderLeft': {'width': {'magnitude': 0, 'unit': 'PT'}, 'dashStyle': 'SOLID', 'color': {'color': {'rgbColor': {'red': 1, 'green': 1, 'blue': 1}}}},
                    'borderRight': {'width': {'magnitude': 0, 'unit': 'PT'}, 'dashStyle': 'SOLID', 'color': {'color': {'rgbColor': {'red': 1, 'green': 1, 'blue': 1}}}},
                    'paddingTop': {'magnitude': 0, 'unit': 'PT'},
                    'paddingBottom': {'magnitude': 0, 'unit': 'PT'},
                    'paddingLeft': {'magnitude': 72, 'unit': 'PT'},
                },
                'fields': 'borderTop,borderBottom,borderLeft,borderRight,paddingTop,paddingBottom,paddingLeft'
            }
        })

        # Single line spacing in IT table
        fmt.append({
            'updateParagraphStyle': {
                'range': {'startIndex': it_start, 'endIndex': it_end},
                'paragraphStyle': {'lineSpacing': 100},
                'fields': 'lineSpacing'
            }
        })

    # Fix (ค) under ข้อ 4: set indentStart so wrapped lines align with first line text
    # Find (ค) under ข้อ 4 (the one about หักเงิน, not ข้อ 1)
    ko4_pos = fpos('ข้อ 4')
    if ko4_pos:
        ka_pos = find_text_index(runs, '(ค)', ko4_pos)
        if ka_pos:
            # Find the end of this paragraph (next newline)
            ka_end = None
            for si, ei, content in runs:
                if si >= ka_pos:
                    nl = content.find('\n', max(0, ka_pos - si))
                    if nl >= 0:
                        ka_end = si + nl + 1
                        break
                    else:
                        ka_end = ei
            if ka_end:
                fmt.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': ka_pos, 'endIndex': ka_end},
                        'paragraphStyle': {
                            'indentStart': {'magnitude': 36, 'unit': 'PT'},
                            'indentFirstLine': {'magnitude': 0, 'unit': 'PT'},
                        },
                        'fields': 'indentStart,indentFirstLine'
                    }
                })

    return fmt


def insert_sig_table(docs_svc, doc_id, employee_full_name):
    """Insert signature table and fill cells."""
    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': [
        {'insertTable': {'rows': 2, 'columns': 2, 'endOfSegmentLocation': {}}}
    ]}).execute()

    doc = docs_svc.documents().get(documentId=doc_id).execute()
    table_elem = None
    for elem in doc['body']['content']:
        if 'table' in elem:
            table_elem = elem['table']

    cells = []
    for row in table_elem['tableRows']:
        for cell in row['tableCells']:
            cells.append(cell['content'][0].get('startIndex', 0))

    sig_texts = [
        f"ลงชื่อ__________________________ผู้มอบบัตร\n( นางสาวชนิลรัตน์  วิอังศุธร )",
        f"ลงชื่อ__________________________ผู้รับบัตรเสริม\n( {employee_full_name} )",
        f"ลงชื่อ__________________________พยาน\n( นางสาวพรปรียา  ศักย์สิริภากร )",
        f"ลงชื่อ__________________________พยาน\n( นางสาวนฐมณ  มงคลนภัทร์ )",
    ]

    reqs = []
    for i in range(3, -1, -1):
        reqs.append({'insertText': {'location': {'index': cells[i]}, 'text': sig_texts[i]}})
    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': reqs}).execute()


def process_airada(docs_svc, drive_svc):
    """ไอรดา: simple text, no IT table."""
    doc_id = DOC_IDS['airada']
    print("\n=== Processing ไอรดา ===")

    # Clear
    doc = docs_svc.documents().get(documentId=doc_id).execute()
    end_index = doc['body']['content'][-1]['endIndex']
    reqs = []
    if end_index > 2:
        reqs.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': end_index - 1}}})

    body = BODY_COMMON_BEFORE.format(date=DATE_TEXT, employee_name='นางสาวไอรดา วิจิตรรัตนกุล')
    body += SECTION1_AIRADA
    body += BODY_AFTER_SECTION1
    body = body.rstrip('\n')

    reqs.append({'insertText': {'location': {'index': 1}, 'text': body}})
    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': reqs}).execute()
    print("  Body inserted")

    # Sig table
    insert_sig_table(docs_svc, doc_id, 'นางสาวไอรดา  วิจิตรรัตนกุล')
    print("  Sig table inserted")

    # Format
    doc = docs_svc.documents().get(documentId=doc_id).execute()
    full_text = ''
    for element in doc['body']['content']:
        if 'paragraph' in element:
            for run in element['paragraph'].get('elements', []):
                if 'textRun' in run:
                    full_text += run['textRun']['content']
    end_idx = doc['body']['content'][-1]['endIndex']

    fmt = apply_common_formatting(docs_svc, doc_id, full_text, end_idx, doc)
    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': fmt}).execute()
    print("  Formatted")

    output = os.path.join(WORKSPACE, 'ข้อตกลงบัตรเสริม_ไอรดา_v5.pdf')
    export_pdf(drive_svc, doc_id, output)


def process_aritcha(docs_svc, drive_svc):
    """อริตชา: IT items in 2-column table."""
    doc_id = DOC_IDS['aritcha']
    print("\n=== Processing อริตชา ===")

    # Clear
    doc = docs_svc.documents().get(documentId=doc_id).execute()
    end_index = doc['body']['content'][-1]['endIndex']
    reqs = []
    if end_index > 2:
        reqs.append({'deleteContentRange': {'range': {'startIndex': 1, 'endIndex': end_index - 1}}})

    # Insert PART A (before IT table)
    part_a = BODY_COMMON_BEFORE.format(date=DATE_TEXT, employee_name='นางสาวอริตชา มณเฑียรทอง')
    part_a += SECTION1_ARITCHA_BEFORE.rstrip('\n')

    reqs.append({'insertText': {'location': {'index': 1}, 'text': part_a}})
    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': reqs}).execute()
    print("  Part A inserted")

    # Insert IT table (4 rows x 2 cols) at end
    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': [
        {'insertTable': {'rows': 4, 'columns': 2, 'endOfSegmentLocation': {}}}
    ]}).execute()
    print("  IT table inserted")

    # Fill IT table cells
    doc = docs_svc.documents().get(documentId=doc_id).execute()
    it_table = None
    for elem in doc['body']['content']:
        if 'table' in elem:
            it_table = elem['table']
            break

    it_cells = []
    for row in it_table['tableRows']:
        for cell in row['tableCells']:
            it_cells.append(cell['content'][0].get('startIndex', 0))

    # Fill in reverse order to maintain indices
    fill_reqs = []
    for r in range(3, -1, -1):
        for c in range(1, -1, -1):
            text = IT_TABLE_DATA[r][c]
            if text:
                idx = r * 2 + c
                fill_reqs.append({
                    'insertText': {'location': {'index': it_cells[idx]}, 'text': text}
                })
    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': fill_reqs}).execute()
    print("  IT table filled")

    # Insert PART B (after IT table)
    doc = docs_svc.documents().get(documentId=doc_id).execute()
    # Find end of IT table
    it_table_end = None
    for elem in doc['body']['content']:
        if 'table' in elem:
            it_table_end = elem.get('endIndex', 0)
            break

    # There should be a paragraph after the table - insert text there
    part_b = SECTION1_ARITCHA_AFTER + BODY_AFTER_SECTION1.rstrip('\n')
    # Find the paragraph right after the IT table
    after_table_para = None
    for elem in doc['body']['content']:
        if 'paragraph' in elem:
            si = elem.get('startIndex', 0)
            if si >= it_table_end:
                after_table_para = elem
                break

    if after_table_para:
        insert_idx = after_table_para.get('startIndex', 0)
        docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': [
            {'insertText': {'location': {'index': insert_idx}, 'text': part_b}}
        ]}).execute()
    print("  Part B inserted")

    # Sig table
    insert_sig_table(docs_svc, doc_id, 'นางสาวอริตชา  มณเฑียรทอง')
    print("  Sig table inserted")

    # Format
    doc = docs_svc.documents().get(documentId=doc_id).execute()
    full_text = ''
    for element in doc['body']['content']:
        if 'paragraph' in element:
            for run in element['paragraph'].get('elements', []):
                if 'textRun' in run:
                    full_text += run['textRun']['content']
    end_idx = doc['body']['content'][-1]['endIndex']

    fmt = apply_common_formatting(docs_svc, doc_id, full_text, end_idx, doc)
    docs_svc.documents().batchUpdate(documentId=doc_id, body={'requests': fmt}).execute()
    print("  Formatted")

    output = os.path.join(WORKSPACE, 'ข้อตกลงบัตรเสริม_อริตชา_v5.pdf')
    export_pdf(drive_svc, doc_id, output)


def main():
    creds = get_creds()
    docs_svc = build('docs', 'v1', credentials=creds)
    drive_svc = build('drive', 'v3', credentials=creds)

    process_airada(docs_svc, drive_svc)
    time.sleep(1)
    process_aritcha(docs_svc, drive_svc)

    # Verify
    import fitz
    for name in ['ข้อตกลงบัตรเสริม_ไอรดา_v5.pdf', 'ข้อตกลงบัตรเสริม_อริตชา_v5.pdf']:
        doc = fitz.open(os.path.join(WORKSPACE, name))
        print(f"  {name}: {len(doc)} pages")
        doc.close()

    print("\n✅ Done!")


if __name__ == '__main__':
    main()
