from datetime import date

from src.insights import month_summary, purchases, top_stores

TODAY = date(2026, 11, 15)
RECEIPTS = [
    {"purchase_date": "2026-11-02", "merchant": "שופרסל", "total_amount": 600.0},
    {"purchase_date": "2026-11-10", "merchant": "פז", "total_amount": 300.0},
    {"purchase_date": "2026-10-05", "merchant": "שופרסל", "total_amount": 400.0},
    {"purchase_date": "2026-10-20", "merchant": "איקאה", "total_amount": 999.0},   # after the 15th
]
MANUAL = [{"month": "2026-11", "merchant": None, "description": "שוק", "estimated_amount": 100.0}]


def test_month_summary_with_budget():
    s = month_summary(purchases(RECEIPTS, MANUAL), TODAY, budget=3000)
    assert s["spent"] == 1000                     # 600 + 300 + 100 from the handwritten line
    assert s["last_month_same_days"] == 400       # only Oct 1-15
    assert s["change"] == 600
    assert s["left"] == 2000 and s["days_left"] == 16 and s["per_day"] == 125
    assert s["on_pace"]                            # 1000 <= 3000 * 15/30


def test_top_stores():
    assert top_stores(purchases(RECEIPTS, MANUAL), TODAY) == [("שופרסל", 600), ("פז", 300), ("שוק", 100)]


def test_quick_answers_need_no_model():
    from src.insights import quick_answer
    receipts = RECEIPTS + [{"purchase_date": "2026-11-12", "merchant": "מחסני חשמל", "product": "מיקרוגל",
                            "total_amount": 449.0, "warranty_until": "2026-12-15"}]
    for r in receipts:
        r.setdefault("product", None)
        r.setdefault("warranty_until", None)
    assert "1,449.00" in quick_answer("כמה הוצאתי החודש?", receipts, MANUAL, TODAY, 3000)
    assert "מיקרוגל" in quick_answer("איזו אחריות נגמרת?", receipts, MANUAL, TODAY)
    assert "1. **שופרסל**" in quick_answer("איפה הוצאתי הכי הרבה?", receipts, MANUAL, TODAY)
    assert "2 קניות" in quick_answer("מה קניתי השבוע?", receipts, MANUAL, TODAY)
    assert quick_answer("שאלה אחרת", receipts, MANUAL, TODAY) is None
