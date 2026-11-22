"""Generate all the made-up sample data for the project.

Run:  python scripts/make_sample_data.py

Creates:
  data/receipts/receipt_XX.txt (+ 3 photographed-style PNGs)
  data/statements/statement_2026_11.csv / .xlsx / .pdf
  data/handwritten/page_1.png, page_2.png
  eval/receipts_truth.json          what each receipt should be read as
  eval/handwritten_truth.json       what each handwritten line should be read as
  eval/statement_labels.csv         the right answer for each of the 40 charges

All data is invented. No real people, cards or purchases.
"""

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DATA, EVAL = ROOT / "data", ROOT / "eval"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
random.seed(7)

# ---------------------------------------------------------------- receipts
# id, merchant, purchase_date, product, total, installments, warranty_months
RECEIPTS = [
    ("R01", "מחסני חשמל", "2026-11-03", "מקרר", 2490.00, 6, 36),
    ("R02", "באג מולטיסיסטם", "2026-09-14", "אוזניות", 360.00, 3, 12),
    ("R03", "שופרסל דיל", "2026-11-02", "מצרכים", 612.40, 1, 0),
    ("R04", "רמי לוי", "2026-11-09", "מצרכים", 845.90, 1, 0),
    ("R05", "סופר-פארם", "2026-11-11", "מוצרי טיפוח", 189.70, 1, 0),
    ("R06", "ACE", "2026-11-12", "מקדחה", 349.00, 1, 24),
    ("R07", "חשמל העיר", "2025-12-15", "מיקסר", 899.00, 1, 12),
    ("R08", "פז", "2026-11-15", "דלק", 300.00, 1, 0),
    ("R09", "איקאה", "2026-11-17", "מדף", 520.00, 1, 0),
    ("R10", "קפה גרג", "2026-11-18", "ארוחת בוקר", 64.00, 1, 0),
    ("R11", "טיב טעם", "2026-11-20", "מצרכים", 233.50, 1, 0),
    ("R12", "צומת ספרים", "2026-11-21", "ספרים", 158.00, 1, 0),
    ("R13", "מחסני חשמל", "2026-11-22", "מיקרוגל", 449.00, 1, 12),
    ("R14", "הום סנטר", "2026-11-24", "מנורה", 129.90, 1, 12),
    ("R15", "גוד פארם", "2026-11-25", "תרופות", 76.30, 1, 0),
]
PHOTO_RECEIPTS = {"R01", "R06", "R14"}

# ---------------------------------------------------------------- handwritten pages
# id, page, description, estimated_amount, duplicate_of
HANDWRITTEN = [
    ("M01", 1, "סופר", 450, None),
    ("M02", 1, "נעליים לילדים", 200, None),
    ("M03", 1, "ירקות", 120, None),
    ("M04", 1, "דלק", 250, None),
    ("M05", 1, "מתנה ליום הולדת", 150, None),
    ("M06", 1, "חוג לילדים", 280, None),
    ("M07", 1, "מספרה", 90, None),
    ("M08", 1, "מסעדה", 200, None),
    ("M09", 2, "חוג לילדים", 280, "M06"),   # same purchase written twice
    ("M10", 2, "תרופות", 60, None),
    ("M11", 2, "חשמלאי", 400, None),
    ("M12", 2, "סופר", 380, None),
    ("M13", 2, "פיצה", 95, None),
    ("M14", 2, "מתנה לחתונה", 500, None),
    ("M15", 2, "בגדים", 350, None),
    ("M16", 2, "טיפול לרכב", 600, None),
]

# ---------------------------------------------------------------- statement
# charge_date, merchant (as the card company prints it), amount, installment,
# expected_status, matched_ref, why this case is in the dataset
CHARGES = [
    ("2026-11-01", "MATNAS GILO", 280.00, "", "matched_manual", "M06", "handwritten, exact amount"),
    ("2026-11-01", "CLOUD STORAGE PLUS", 19.90, "", "unrecognized", "", "forgotten subscription"),
    ("2026-11-02", "SHUFERSAL DEAL", 612.40, "", "matched_receipt", "R03", "English vs Hebrew name"),
    ("2026-11-03", "GYM ACTIVE", 199.00, "", "unrecognized", "", "forgotten subscription"),
    ("2026-11-05", "MACHSANEY HASHMAL", 415.00, "1/6", "matched_receipt", "R01", "installment 1 of 6"),
    ("2026-11-05", "AMZN MKTP US", 87.40, "", "unrecognized", "", "foreign online charge"),
    ("2026-11-06", "OSHER AD", 462.30, "", "matched_manual", "M01", "handwritten, 2.7% off, no merchant"),
    ("2026-11-07", "SHOE STATION", 199.90, "", "matched_manual", "M02", "handwritten, rounded amount"),
    ("2026-11-08", "PERI VEYEREK HADAR", 118.00, "", "matched_manual", "M03", "handwritten"),
    ("2026-11-08", "DELEK MOTOR", 250.00, "", "matched_manual", "M04", "handwritten fuel, not the receipt one"),
    ("2026-11-09", "PAYPAL *XGAMES", 45.00, "", "unrecognized", "", "unknown online charge"),
    ("2026-11-10", "רמי לוי שיווק השקמה", 845.90, "", "matched_receipt", "R04", "Hebrew name on statement, date +1"),
    ("2026-11-10", "PARKING TLV", 18.00, "", "unrecognized", "", "small charge, no record"),
    ("2026-11-11", "SUPER-PHARM", 189.70, "", "matched_receipt", "R05", "English vs Hebrew name"),
    ("2026-11-12", "TOYS CENTER", 159.00, "", "matched_manual", "M05", "handwritten, 6% off"),
    ("2026-11-13", "ACE AUTO DEPOT", 349.00, "", "matched_receipt", "R06", "longer name, date +1"),
    ("2026-11-14", "BUG MULTISYSTEM", 120.00, "3/3", "matched_receipt", "R02", "last installment of a September purchase"),
    ("2026-11-14", "ALIEXPRESS", 32.80, "", "unrecognized", "", "foreign online charge"),
    ("2026-11-15", "PAZ YELLOW", 300.00, "", "matched_receipt", "R08", "fuel with receipt"),
    ("2026-11-16", "BARBER SHOP", 90.00, "", "matched_manual", "M07", "handwritten"),
    ("2026-11-17", "IKEA NETANYA", 545.00, "", "amount_mismatch", "R09", "charged 25 more than receipt"),
    ("2026-11-18", "CAFE GREG", 64.00, "", "matched_receipt", "R10", "English vs Hebrew name"),
    ("2026-11-18", "MEAT BAR", 260.00, "", "unrecognized", "", "handwritten 'restaurant 200' is 30% off, too far"),
    ("2026-11-19", "BE PHARM", 57.50, "", "matched_manual", "M10", "handwritten, 4% off"),
    ("2026-11-19", "PAYBOX*YOSSI", 400.00, "", "matched_manual", "M11", "handwritten, payment app"),
    ("2026-11-20", "WOLT", 112.00, "", "unrecognized", "", "no record"),
    ("2026-11-22", "MACHSANEY HASHMAL", 459.00, "", "amount_mismatch", "R13", "charged 10 more than receipt"),
    ("2026-11-23", "TIV TAAM", 233.50, "", "matched_receipt", "R11", "date +3, edge of regular window"),
    ("2026-11-23", "CELLCOM", 49.90, "", "unrecognized", "", "monthly bill, no record"),
    ("2026-11-21", "TZOMET SFARIM", 158.00, "", "matched_receipt", "R12", "transliterated name"),
    ("2026-11-25", "GOOD PHARM", 76.30, "", "matched_receipt", "R15", "first of a double charge"),
    ("2026-11-25", "UNKNOWN MERCHANT 8841", 750.00, "", "unrecognized", "", "suspicious foreign charge"),
    ("2026-11-26", "GOOD PHARM", 76.30, "", "unrecognized", "", "double charge, receipt already used"),
    ("2026-11-26", "HAMASHBIR", 489.00, "", "matched_manual", "M14", "handwritten, 2% off"),
    ("2026-11-27", "YOCHANANOF", 371.20, "", "matched_manual", "M12", "second 'super' line on page 2"),
    ("2026-11-27", "PIZZA HUT", 98.00, "", "matched_manual", "M13", "handwritten, 3% off"),
    ("2026-11-28", "CASTRO", 349.90, "", "matched_manual", "M15", "handwritten"),
    ("2026-11-28", "APPLE.COM/BILL", 14.90, "", "unrecognized", "", "small subscription"),
    ("2026-11-29", "HOME CENTER", 129.90, "", "matched_receipt", "R14", "date +5: needs loose matching"),
    ("2026-11-30", "MOSACH HATZAFON", 640.00, "", "matched_manual", "M16", "handwritten, 6.7% off"),
]


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + y, month=m + 1)


def rtl(text: str) -> str:
    """Reorder Hebrew for reportlab, which draws left to right (Pillow handles RTL itself)."""
    return get_display(text)


def receipt_text(r) -> str:
    rid, merchant, d, product, total, inst, warranty = r
    lines = [
        merchant,
        "חשבונית מס / קבלה",
        f"תאריך: {date.fromisoformat(d):%d/%m/%Y}",
        f"מס' קבלה: {random.randint(10000, 99999)}",
        "-" * 24,
        f"{product}    {total:,.2f} ₪",
        "-" * 24,
        f'סה"כ לתשלום: {total:,.2f} ₪',
        "שולם באשראי: XXXX-XXXX-XXXX-4321",
    ]
    if inst > 1:
        lines.append(f"מספר תשלומים: {inst}")
    if warranty:
        lines.append(f"אחריות: {warranty // 12 if warranty >= 12 else warranty} "
                     f"{'שנים' if warranty >= 24 else 'שנה' if warranty == 12 else 'חודשים'}")
    lines.append("תודה ולהתראות!")
    return "\n".join(lines)


def draw_receipt_png(text: str, out: Path):
    font = ImageFont.truetype(FONT, 22)
    lines = text.splitlines()
    img = Image.new("RGB", (460, 50 + 36 * len(lines)), (250, 249, 244))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((430, 25 + 36 * i), line, font=font, fill=(40, 40, 40), anchor="ra")
    img.rotate(random.uniform(-2, 2), expand=True, fillcolor=(200, 200, 200)).save(out)


def draw_handwritten_png(lines: list[str], out: Path, title: str):
    font = ImageFont.truetype(FONT, 30)
    w, h = 700, 120 + 62 * len(lines)
    img = Image.new("RGB", (w, h), (253, 252, 245))
    d = ImageDraw.Draw(img)
    for y in range(90, h, 62):
        d.line([(30, y + 40), (w - 30, y + 40)], fill=(190, 205, 230), width=2)
    d.text((w - 50, 30), title, font=font, fill=(30, 50, 140), anchor="ra")
    for i, line in enumerate(lines):
        x = w - 50 + random.randint(-12, 4)
        y = 100 + 62 * i + random.randint(-4, 4)
        d.text((x, y), line, font=font, fill=(30, 50, 140), anchor="ra")
    img.rotate(random.uniform(-1.5, 1.5), expand=True, fillcolor=(220, 220, 220)).save(out)


def write_statement_pdf(rows, total, out: Path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib.styles import ParagraphStyle

    pdfmetrics.registerFont(TTFont("DejaVu", FONT))
    style = ParagraphStyle("h", fontName="DejaVu", fontSize=13)
    doc = SimpleDocTemplate(str(out), pagesize=A4)
    data = [["ID", "DATE", "MERCHANT", "AMOUNT", "INST."]]
    data += [[r["charge_id"], r["charge_date"], rtl(r["merchant"]),
              f'{r["amount"]:,.2f}', r["installment"]] for r in rows]
    table = Table(data, colWidths=[40, 80, 200, 80, 50])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde4ee")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
    ]))
    doc.build([
        Paragraph(rtl("פירוט חיובים בכרטיס אשראי, נובמבר 2026") + "   CARD ****4321", style),
        Spacer(1, 12), table, Spacer(1, 12),
        Paragraph(f"TOTAL: {total:,.2f}", style),
    ])


def main():
    for p in (DATA / "receipts", DATA / "statements", DATA / "handwritten", EVAL):
        p.mkdir(parents=True, exist_ok=True)

    # receipts
    truth = []
    for r in RECEIPTS:
        rid, merchant, d, product, total, inst, warranty = r
        text = receipt_text(r)
        n = rid[1:]
        (DATA / "receipts" / f"receipt_{n}.txt").write_text(text, encoding="utf-8")
        if rid in PHOTO_RECEIPTS:
            draw_receipt_png(text, DATA / "receipts" / f"receipt_{n}.png")
        until = add_months(date.fromisoformat(d), warranty).isoformat() if warranty else None
        truth.append({"ref": rid, "merchant": merchant, "purchase_date": d,
                      "total_amount": total, "product": product,
                      "installments": inst, "warranty_until": until})
    (EVAL / "receipts_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")

    # handwritten pages
    for page in (1, 2):
        lines = [f"{desc} {amt}" for _, p, desc, amt, _ in HANDWRITTEN if p == page]
        draw_handwritten_png(lines, DATA / "handwritten" / f"page_{page}.png",
                             f"קניות נובמבר - דף {page}")
    hw = [{"ref": ref, "month": "2026-11", "source_page": p, "description": desc,
           "estimated_amount": amt, "merchant": None, "duplicate_of": dup}
          for ref, p, desc, amt, dup in HANDWRITTEN]
    (EVAL / "handwritten_truth.json").write_text(
        json.dumps(hw, ensure_ascii=False, indent=2), encoding="utf-8")

    # statement: CSV, XLSX, PDF, and the labels
    rows = [{"charge_id": f"C{i:02d}", "charge_date": c[0], "merchant": c[1],
             "amount": c[2], "installment": c[3]} for i, c in enumerate(CHARGES, 1)]
    total = round(sum(r["amount"] for r in rows), 2)
    fields = ["charge_id", "charge_date", "merchant", "amount", "installment"]
    with open(DATA / "statements" / "statement_2026_11.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(fields)
    for r in rows:
        ws.append([r[k] for k in fields])
    wb.save(DATA / "statements" / "statement_2026_11.xlsx")

    write_statement_pdf(rows, total, DATA / "statements" / "statement_2026_11.pdf")

    with open(EVAL / "statement_labels.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["charge_id", "expected_status", "matched_ref", "case"])
        for r, c in zip(rows, CHARGES):
            w.writerow([r["charge_id"], c[4], c[5], c[6]])

    counts = {}
    for c in CHARGES:
        counts[c[4]] = counts.get(c[4], 0) + 1
    print(f"{len(RECEIPTS)} receipts, {len(HANDWRITTEN)} handwritten lines, "
          f"{len(rows)} charges, total {total:,.2f}")
    print(counts)


if __name__ == "__main__":
    main()
