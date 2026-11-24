from datetime import date

from src.reminders import days_left, warranty_calendar

TODAY = date(2026, 11, 24)


def test_calendar_has_one_event_per_active_warranty():
    receipts = [
        {"id": 1, "merchant": "מחסני חשמל", "product": "מיקרוגל", "purchase_date": "2026-11-22",
         "total_amount": 449.0, "warranty_until": "2027-11-22"},
        {"id": 2, "merchant": "ACE", "product": None, "purchase_date": "2024-01-01",
         "total_amount": 99.0, "warranty_until": "2025-01-01"},          # already ended
        {"id": 3, "merchant": "פז", "product": "דלק", "purchase_date": "2026-11-15",
         "total_amount": 300.0, "warranty_until": None},                 # no warranty
        {"id": 4, "merchant": "שקם", "product": "מיקסר", "purchase_date": "2025-12-15",
         "total_amount": 399.0, "warranty_until": "2026-12-10"},         # ends in 16 days
    ]
    ics = warranty_calendar(receipts, TODAY).decode("utf-8")
    assert ics.count("BEGIN:VEVENT") == 2
    assert "DTSTART;VALUE=DATE:20271023" in ics      # a month before the end
    assert "DTSTART;VALUE=DATE:20261124" in ics      # less than a month left: remind today
    assert "מיקרוגל" in ics and "449.00" in ics


def test_days_left():
    assert days_left("2026-12-24", TODAY) == 30
