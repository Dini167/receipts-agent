"""Step 1 is done when: the database is created, and the sample receipts,
statement (PDF, CSV, Excel) and handwritten pages load without errors.

Run:  python -m pytest tests -q
"""

import csv
import json
from pathlib import Path

import pytest

from src import db
from src.loaders import check_upload, load_statement

ROOT = Path(__file__).resolve().parent.parent
STATEMENTS = ROOT / "data" / "statements"


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test.db")


def test_receipts_load_into_db(conn):
    truth = json.loads((ROOT / "eval" / "receipts_truth.json").read_text(encoding="utf-8"))
    assert len(truth) == 15
    for r in truth:
        db.add_receipt(conn, r["merchant"], r["purchase_date"], r["total_amount"],
                       r["product"], r["installments"], r["warranty_until"])
    assert len(db.list_receipts(conn)) == 15
    for i in range(1, 16):
        assert (ROOT / "data" / "receipts" / f"receipt_{i:02d}.txt").exists()


def test_warranty_question(conn):
    db.add_receipt(conn, "חשמל העיר", "2025-12-15", 899, "מיקסר", 1, "2026-12-15")
    db.add_receipt(conn, "מחסני חשמל", "2026-11-03", 2490, "מקרר", 6, "2029-11-03")
    ending = db.warranties_ending_between(conn, "2026-11-21", "2026-12-21")
    assert [r["product"] for r in ending] == ["מיקסר"]


def test_handwritten_entries_load(conn):
    lines = json.loads((ROOT / "eval" / "handwritten_truth.json").read_text(encoding="utf-8"))
    for e in lines:
        db.add_manual_entry(conn, e["month"], e["description"], e["estimated_amount"],
                            e["source_page"])
    assert len(db.list_manual_entries(conn, "2026-11")) == 16
    assert (ROOT / "data" / "handwritten" / "page_1.png").exists()
    assert (ROOT / "data" / "handwritten" / "page_2.png").exists()


def test_pdf_csv_and_excel_give_the_same_charges():
    csv_rows, _ = load_statement(STATEMENTS / "statement_2026_11.csv")
    xlsx_rows, _ = load_statement(STATEMENTS / "statement_2026_11.xlsx")
    pdf_rows, pdf_total = load_statement(STATEMENTS / "statement_2026_11.pdf")
    assert len(csv_rows) == 40
    assert csv_rows == xlsx_rows == pdf_rows
    # the printed total matches the sum of the rows (the "total check" step)
    assert pdf_total == round(sum(r["amount"] for r in pdf_rows), 2)


def test_labels_cover_every_charge():
    rows, _ = load_statement(STATEMENTS / "statement_2026_11.csv")
    with open(ROOT / "eval" / "statement_labels.csv", encoding="utf-8") as f:
        labels = list(csv.DictReader(f))
    assert [l["charge_id"] for l in labels] == [r["charge_id"] for r in rows]
    allowed = {"matched_receipt", "matched_manual", "amount_mismatch", "unrecognized"}
    assert {l["expected_status"] for l in labels} == allowed


def test_upload_rules(tmp_path):
    bad = tmp_path / "virus.exe"
    bad.write_bytes(b"x")
    with pytest.raises(ValueError):
        check_upload(bad)


def test_sql_injection_is_just_text(conn):
    db.add_receipt(conn, "x'); DROP TABLE receipts; --", "2026-11-01", 1.0)
    assert len(db.list_receipts(conn)) == 1


def test_delete_receipt(tmp_path):
    from src import db
    with db.connect(tmp_path / "d.db") as c:
        rid = db.add_receipt(c, "חנות", "2026-11-01", 10.0)
        db.delete_receipt(c, rid)
        assert db.list_receipts(c) == []


def test_update_receipt(tmp_path):
    from src import db
    with db.connect(tmp_path / "u.db") as c:
        rid = db.add_receipt(c, "חנות", "2026-11-01", 10.0)
        db.update_receipt(c, rid, "חנות נכונה", "2026-11-02", 12.5, "כיסא", "2027-11-02")
        r = db.list_receipts(c)[0]
        assert (r["merchant"], r["total_amount"], r["warranty_until"]) == ("חנות נכונה", 12.5, "2027-11-02")
