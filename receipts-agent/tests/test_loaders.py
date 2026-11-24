"""Statement files in the shapes real card companies export."""

import pytest
from openpyxl import Workbook

from src.loaders import load_statement


def test_hebrew_bank_csv_with_title_lines(tmp_path):
    f = tmp_path / "bank.csv"
    f.write_text("פירוט עסקאות לכרטיס 1234\n\n"
                 "תאריך עסקה,שם בית העסק,סכום עסקה,סכום חיוב,פירוט נוסף\n"
                 "05/11/2026,שופרסל דיל,612.40,\"612.40\",\n"
                 "07.11.26,PAZ YELLOW,300,300,\n"
                 ",סה\"כ,,912.40,\n", encoding="utf-8-sig")
    rows, _ = load_statement(f)
    assert [(r["charge_date"], r["merchant"], r["amount"]) for r in rows] == [
        ("2026-11-05", "שופרסל דיל", 612.4), ("2026-11-07", "PAZ YELLOW", 300.0)]
    assert rows[0]["charge_id"] == "C01"


def test_excel_with_real_dates(tmp_path):
    from datetime import datetime
    wb = Workbook()
    ws = wb.active
    ws.append(["דוח חיובים"])
    ws.append(["תאריך רכישה", "בית עסק", "סכום חיוב", "תשלום"])
    ws.append([datetime(2026, 11, 3), "מחסני חשמל", 415, "1/6"])
    f = tmp_path / "bank.xlsx"
    wb.save(f)
    rows, _ = load_statement(f)
    assert rows[0]["charge_date"] == "2026-11-03" and rows[0]["installment"] == "1/6"


def test_unknown_columns_give_a_clear_message(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("שם,ערך\nמשהו,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="תאריך"):
        load_statement(f)


def test_broken_pdf_gives_a_clear_message(tmp_path):
    f = tmp_path / "broken.pdf"
    f.write_bytes(b"%PDF-1.4 broken")
    with pytest.raises(ValueError, match="PDF"):
        load_statement(f)
