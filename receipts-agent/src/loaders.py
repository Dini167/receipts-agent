"""Read a credit card statement from CSV, Excel or PDF into one common format.

Every loader returns (charges, stated_total):
  charges      -> list of dicts: charge_id, charge_date, merchant, amount, installment
  stated_total -> the total printed on the statement (or None if there is none),
                  used later for the "does the total match?" check.
"""

import csv
import re
from pathlib import Path

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".pdf"}
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10MB, see the security section
_HEBREW = re.compile(r"[֐-׿]")


def check_upload(path: str | Path) -> Path:
    """Reject files with a type we don't accept or that are too large."""
    path = Path(path)
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"סוג קובץ לא נתמך: {path.suffix}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("הקובץ גדול מ-10MB")
    return path


def _row(charge_id, charge_date, merchant, amount, installment) -> dict:
    return {
        "charge_id": str(charge_id).strip(),
        "charge_date": str(charge_date).strip(),
        "merchant": str(merchant).strip(),
        "amount": round(float(str(amount).replace(",", "").replace("₪", "")), 2),
        "installment": (str(installment).strip() if installment else "") or "",
    }


# Column names seen in real exports (our sample files, and Israeli card companies in Hebrew).
_ALIASES = {
    "charge_date": ["charge_date", "date", "תאריך", "תאריך עסקה", "תאריך רכישה", "תאריך חיוב",
                    "תאריך העסקה"],
    "merchant": ["merchant", "שם בית העסק", "שם בית עסק", "בית עסק", "בית העסק", "תיאור",
                 "שם העסק"],
    "amount": ["amount", "סכום חיוב", "סכום החיוב", "סכום לחיוב", "סכום חיוב ₪", "סכום",
               "סכום העסקה", "סכום בש\"ח"],
    "installment": ["installment", "תשלום", "תשלומים", "מספר תשלום"],
    "charge_id": ["charge_id", "מספר", "אסמכתא", "מס' שובר"],
}
_NEEDED = {"charge_date": "תאריך", "merchant": "בית עסק", "amount": "סכום"}


def _clean(h) -> str:
    return re.sub(r"\s+", " ", str(h or "")).strip().strip(":").lower()


def _columns(header: list) -> dict[str, int] | None:
    """Which column holds which field, or None if this row is not a header."""
    names = [_clean(h) for h in header]
    found = {}
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if alias.lower() in names:
                found[field] = names.index(alias.lower())
                break
    return found if "charge_date" in found and "amount" in found else None


def _iso_date(value) -> str | None:
    """2026-11-05, 05/11/2026, 5.11.26 or an Excel date -> 2026-11-05."""
    if value is None or value == "":
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2}).*", text)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", text)
        if not m:
            return None
        d, mo, y = m.groups()
        y = "20" + y if len(y) == 2 else y
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def _rows_from_table(table: list[list]) -> list[dict]:
    """Find the header row (bank files often start with title lines), then read the rows."""
    for i, header in enumerate(table[:20]):
        cols = _columns(list(header))
        if cols:
            break
    else:
        raise ValueError("לא מצאתי בקובץ עמודות של תאריך וסכום. הקובץ צריך לכלול לפחות "
                         "עמודות של " + ", ".join(_NEEDED.values()) + ".")
    if "merchant" not in cols:
        raise ValueError("לא מצאתי בקובץ עמודה של שם בית העסק.")
    rows = []
    for r in table[i + 1:]:
        r = list(r) + [None] * 10
        when, amount = _iso_date(r[cols["charge_date"]]), r[cols["amount"]]
        if not when or amount in (None, ""):
            continue                     # empty lines and "total" lines
        try:
            amount = float(str(amount).replace(",", "").replace("₪", "").strip())
        except ValueError:
            continue
        cid = r[cols["charge_id"]] if "charge_id" in cols else None
        rows.append(_row(cid or f"C{len(rows) + 1:02d}", when, r[cols["merchant"]], amount,
                         r[cols["installment"]] if "installment" in cols else ""))
    if not rows:
        raise ValueError("לא מצאתי בקובץ אף חיוב.")
    return rows


def load_statement_csv(path) -> tuple[list[dict], float | None]:
    with open(check_upload(path), encoding="utf-8-sig", newline="") as f:
        return _rows_from_table(list(csv.reader(f))), None


def load_statement_xlsx(path) -> tuple[list[dict], float | None]:
    from openpyxl import load_workbook
    try:
        ws = load_workbook(check_upload(path), read_only=True, data_only=True).active
    except Exception as e:
        raise ValueError("לא הצלחתי לפתוח את קובץ ה-Excel. ייתכן שהוא פגום.") from e
    return _rows_from_table([list(r) for r in ws.iter_rows(values_only=True)]), None


def _fix_hebrew(text: str) -> str:
    """PDF text extraction returns Hebrew in visual order; flip it back to logical order."""
    if not text or not _HEBREW.search(text):
        return text
    from bidi.algorithm import get_display
    return get_display(text)


def load_statement_pdf(path) -> tuple[list[dict], float | None]:
    """Read the charges table and the printed total from a text-based PDF.

    A scanned PDF (no text layer) returns no rows; the graph then sends the
    page image to a model that can read images instead.
    """
    import pdfplumber

    rows, stated_total = [], None
    try:
        pdf = pdfplumber.open(check_upload(path))
    except Exception as e:
        raise ValueError("לא הצלחתי לפתוח את קובץ ה-PDF. ייתכן שהוא פגום או מוגן בסיסמה.") from e
    with pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for cells in table:
                    cells = [c or "" for c in cells]
                    if re.fullmatch(r"C\d+", cells[0].strip()):
                        rows.append(_row(cells[0], cells[1], _fix_hebrew(cells[2]),
                                         cells[3], cells[4] if len(cells) > 4 else ""))
            text = page.extract_text() or ""
            m = re.search(r"TOTAL[:\s]+([\d,]+\.\d{2})", text)
            if m:
                stated_total = float(m.group(1).replace(",", ""))
    return rows, stated_total


def load_statement(path) -> tuple[list[dict], float | None]:
    """Pick the right loader by file type."""
    loaders = {
        ".csv": load_statement_csv,
        ".xlsx": load_statement_xlsx,
        ".pdf": load_statement_pdf,
    }
    return loaders[check_upload(path).suffix.lower()](path)
