"""Reminders that bring the user back at the right time, without a server.

The website makes a calendar file (.ics). Opening it on the phone or computer adds
one event per warranty to the user's own calendar (Google, Outlook, iPhone), so the
calendar reminds them before the warranty ends, even when the website is closed.
"""

from datetime import date, timedelta

DAYS_BEFORE = 30   # the reminder is on the calendar a month before the warranty ends


def _text(value: str) -> str:
    """Calendar files need commas, semicolons and new lines escaped."""
    return (str(value).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def warranty_calendar(receipts: list[dict], today: date | None = None) -> bytes:
    """One all-day event for each warranty that has not ended yet."""
    today = today or date.today()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//receipts-agent//HE",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for r in receipts:
        if not r.get("warranty_until"):
            continue
        end = date.fromisoformat(r["warranty_until"])
        if end < today:
            continue
        remind = max(today, end - timedelta(days=DAYS_BEFORE))
        name = r.get("product") or r["merchant"]
        lines += [
            "BEGIN:VEVENT",
            f"UID:warranty-{r['id']}-{end:%Y%m%d}@receipts-agent",
            f"DTSTAMP:{today:%Y%m%d}T000000Z",
            f"DTSTART;VALUE=DATE:{remind:%Y%m%d}",
            f"DTEND;VALUE=DATE:{remind + timedelta(days=1):%Y%m%d}",
            "SUMMARY:" + _text(f"האחריות על {name} נגמרת ב-{end:%d/%m/%Y}"),
            "DESCRIPTION:" + _text(f"נקנה ב{r['merchant']} ב-{r['purchase_date']} "
                                   f"בסך {float(r['total_amount']):,.2f} ₪. "
                                   "אם יש תקלה, זה הזמן לפנות לתיקון באחריות."),
            "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT0M",
            "DESCRIPTION:" + _text(f"האחריות על {name} נגמרת בקרוב"), "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def days_left(until: str, today: date | None = None) -> int:
    return (date.fromisoformat(until) - (today or date.today())).days
