"""A typed shopping list in Word goes through the same flow as a handwritten page."""

import zipfile

from langgraph.types import Command

from src import db
from src.graph import build_graph
from src.loaders import docx_text, file_kind
from tests.fake_ai import FakeAI

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(path, lines):
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")


def test_word_list_is_read_and_saved(tmp_path):
    path = tmp_path / "list.docx"
    make_docx(path, ["קניות מזדמנות", "מתנה ליום הולדת 120", "שוק 85"])
    assert file_kind(path.read_bytes()) == "docx"
    assert docx_text(path) == "קניות מזדמנות\nמתנה ליום הולדת 120\nשוק 85"

    lines = [{"description": "מתנה ליום הולדת", "estimated_amount": 120.0, "merchant": None},
             {"description": "שוק", "estimated_amount": 85.0, "merchant": None}]
    g = build_graph(FakeAI(handwritten=lines), tmp_path / "t.db")
    cfg = {"configurable": {"thread_id": "w"}}
    out = g.invoke({"input_kind": "handwritten", "file_path": str(path), "month": "2026-11"}, cfg)
    assert out["__interrupt__"][0].value["type"] == "confirm_handwritten"
    g.invoke(Command(resume=True), cfg)
    with db.connect(tmp_path / "t.db") as c:
        assert [e["description"] for e in db.list_manual_entries(c, "2026-11")] == ["מתנה ליום הולדת", "שוק"]
