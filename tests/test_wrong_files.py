"""A file that is not a receipt, page or statement stops at once with a clear message."""

import pytest
from reportlab.pdfgen import canvas

from src import db
from src.graph import NOT_RECEIPT, NOT_STATEMENT, build_graph
from src.loaders import file_kind
from tests.fake_ai import FakeAI, ROOT


def test_file_kind_reads_the_content_not_the_name(tmp_path):
    assert file_kind((ROOT / "data/statements/statement_2026_11.pdf").read_bytes()) == "pdf"
    assert file_kind((ROOT / "data/statements/statement_2026_11.xlsx").read_bytes()) == "xlsx"
    assert file_kind((ROOT / "data/receipts/receipt_01.png").read_bytes()) == "png"
    assert file_kind("קבלה מסופר".encode("utf-8")) == "text"
    assert file_kind(bytes(range(256)) * 4) is None          # some other program's file


def test_pdf_that_is_not_a_statement_stops_without_the_model(tmp_path):
    path = tmp_path / "letter.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(100, 750, "Dear friend, here are the notes from our meeting on Sunday.")
    c.save()
    g = build_graph(FakeAI(), tmp_path / "t.db")
    with pytest.raises(ValueError, match=NOT_STATEMENT[:20]):
        g.invoke({"input_kind": "statement", "file_path": str(path)},
                 {"configurable": {"thread_id": "x"}})


def test_image_that_is_not_a_receipt_stops(tmp_path):
    g = build_graph(FakeAI(receipt={"merchant": None, "purchase_date": None, "total_amount": None}),
                    tmp_path / "t.db")
    with pytest.raises(ValueError, match=NOT_RECEIPT[:15]):
        g.invoke({"input_kind": "receipt", "file_path": str(ROOT / "data/receipts/receipt_01.png")},
                 {"configurable": {"thread_id": "y"}})
    with db.connect(tmp_path / "t.db") as c:
        assert db.list_receipts(c) == []
