"""Step 2 is done when: each of the four inputs goes through the graph from start
to end, and every stop for approval shows up and continues after an answer.

These tests use FakeAI, so they run without API keys.
"""

import csv
from datetime import date
from pathlib import Path

from langgraph.types import Command

from src import db
from src.graph import build_graph
from tests.fake_ai import FakeAI, load_truth_into_db

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 30)


def run(graph, inputs, thread="t1"):
    return graph.invoke(inputs, {"configurable": {"thread_id": thread}})


def resume(graph, value, thread="t1"):
    return graph.invoke(Command(resume=value), {"configurable": {"thread_id": thread}})


def test_statement_flow_gets_all_40_right(tmp_path):
    path = tmp_path / "t.db"
    with db.connect(path) as c:
        load_truth_into_db(c, db)
    g = build_graph(FakeAI(), path, today=TODAY)
    for f in ("statement_2026_11.pdf", "statement_2026_11.csv", "statement_2026_11.xlsx"):
        thread = f
        out = run(g, {"file_path": str(ROOT / "data" / "statements" / f)}, thread)
        # stops before marking charges as suspicious
        assert out["__interrupt__"][0].value["type"] == "confirm_suspicious"
        assert len(out["__interrupt__"][0].value["charges"]) == 12
        out = resume(g, [], thread)
        with open(ROOT / "eval" / "statement_labels.csv", encoding="utf-8") as fh:
            labels = {r["charge_id"]: r["expected_status"] for r in csv.DictReader(fh)}
        got = {cid: r["status"] for cid, r in out["results"].items()}
        wrong = {cid: (got[cid], labels[cid]) for cid in labels if got[cid] != labels[cid]}
        assert not wrong, wrong
        assert out["retry_count"] >= 1          # the loose-matching loop ran
        assert "מיקסר" in out["answer"]          # warranty ending soon is in the report


def test_total_mismatch_stops(tmp_path):
    bad = tmp_path / "bad.pdf"
    src = ROOT / "data" / "statements" / "statement_2026_11.pdf"
    bad.write_bytes(src.read_bytes())
    g = build_graph(FakeAI(), tmp_path / "t.db", today=TODAY)
    from unittest.mock import patch
    rows_total = __import__("src.loaders", fromlist=["x"]).load_statement(src)
    with patch("src.graph.load_statement", return_value=(rows_total[0][:-1], rows_total[1])):
        out = run(g, {"file_path": str(bad)})
        assert out["__interrupt__"][0].value["type"] == "total_mismatch"
        out = resume(g, False)
    assert "עצרתי" in out["answer"]


def test_receipt_with_missing_amount_asks_first(tmp_path):
    ai = FakeAI(receipt={"merchant": "ACE", "purchase_date": "2026-11-12", "total_amount": None,
                         "product": "מקדחה", "installments": 1, "warranty_months": 24})
    g = build_graph(ai, tmp_path / "t.db", today=TODAY)
    out = run(g, {"file_path": str(ROOT / "data" / "receipts" / "receipt_06.png")})
    stop = out["__interrupt__"][0].value
    assert stop["type"] == "missing_fields" and stop["missing"] == ["total_amount"]
    out = resume(g, {"total_amount": 349.0})
    assert "12/11/2028" in out["answer"]
    with db.connect(tmp_path / "t.db") as c:
        assert db.list_receipts(c)[0]["total_amount"] == 349.0


def test_handwritten_repeat_is_asked_about(tmp_path):
    path = tmp_path / "t.db"
    with db.connect(path) as c:
        db.add_manual_entry(c, "2026-11", "חוג לילדים", 280, 1)
    ai = FakeAI(handwritten=[{"description": "חוג לילדים", "estimated_amount": 280},
                             {"description": "פיצה", "estimated_amount": 95}])
    g = build_graph(ai, path, today=TODAY)
    out = run(g, {"file_path": str(ROOT / "data" / "handwritten" / "page_2.png"),
                  "month": "2026-11"})
    stop = out["__interrupt__"][0].value
    assert stop["type"] == "confirm_handwritten"
    assert [d["index"] for d in stop["duplicates"]] == [0]
    out = resume(g, {"drop": [0]})               # "it's the same purchase"
    with db.connect(path) as c:
        assert len(db.list_manual_entries(c, "2026-11")) == 2
    assert "דף 2" in out["answer"]


def test_question_gets_all_saved_data(tmp_path):
    path = tmp_path / "t.db"
    with db.connect(path) as c:
        db.add_receipt(c, "מחסני חשמל", "2026-11-03", 2490, "מקרר", 6, "2029-11-03")
        db.add_receipt(c, "ACE", "2026-11-12", 349, "מקדחה", 1, "2028-11-12")
        db.add_manual_entry(c, "2026-11", "פיצה", 95, 1)
    g = build_graph(FakeAI(), path)
    out = run(g, {"question": "לאיזה מוצר יש אחריות לטווח הרחוק ביותר?"})
    assert "מקרר" in out["answer"] and "מקדחה" in out["answer"]
    assert out["context"]["handwritten_lines"][0]["description"] == "פיצה"


def test_question_with_no_data_does_not_invent(tmp_path):
    g = build_graph(FakeAI(), tmp_path / "t.db")
    out = run(g, {"question": "מתי נגמרת האחריות על המזגן?"})
    assert "עוד לא נשמר" in out["answer"]


def test_statement_check_is_saved_for_questions(tmp_path):
    path = tmp_path / "t.db"
    with db.connect(path) as c:
        load_truth_into_db(c, db)
    g = build_graph(FakeAI(), path, today=TODAY)
    run(g, {"file_path": str(ROOT / "data" / "statements" / "statement_2026_11.csv")}, "s")
    resume(g, [], "s")
    with db.connect(path) as c:
        assert len(db.list_checked_charges(c)) == 40


def test_warranty_time_left_is_computed_in_code(tmp_path):
    """The model gets the days left ready-made, so it never does date math itself."""
    from datetime import date
    seen = {}

    class AI(FakeAI):
        def write_answer(self, question, context):
            seen.update({r["product"]: r for r in context["receipts"]})
            return "ok"

    path = tmp_path / "t.db"
    with db.connect(path) as c:
        db.add_receipt(c, "חשמל העיר", "2025-12-15", 899, "מיקסר", warranty_until="2026-12-15")
        db.add_receipt(c, "מכולת", "2026-11-01", 50, "לחם")
    g = build_graph(AI(), path, today=date(2026, 11, 22))
    g.invoke({"input_kind": "question", "question": "מה האחריות?"},
             {"configurable": {"thread_id": "w"}})
    assert seen["מיקסר"]["warranty_days_left"] == 23
    assert seen["מיקסר"]["warranty_status"] == "בתוקף"
    assert seen["לחם"]["warranty_status"] == "אין אחריות"


def test_same_receipt_twice_is_saved_once(tmp_path):
    ai = FakeAI(receipt={"merchant": "ACE", "purchase_date": "2026-11-12", "total_amount": 349.0,
                         "product": "מקדחה", "installments": 1, "warranty_months": 24})
    g = build_graph(ai, tmp_path / "t.db", today=TODAY)
    for i in range(2):
        out = g.invoke({"file_path": str(ROOT / "data" / "receipts" / "receipt_06.png")},
                       {"configurable": {"thread_id": f"r{i}"}})
    assert "כבר שמורה" in out["answer"]
    with db.connect(tmp_path / "t.db") as c:
        assert len(db.list_receipts(c)) == 1
