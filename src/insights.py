"""Numbers for the home screen: budget, comparison with last month, where the money went.

Plain code, no model: it is instant and always the same answer.
Purchases = saved receipts + lines from handwritten pages / Word lists (estimated amounts).
"""

import calendar
from datetime import date, timedelta


def purchases(receipts: list[dict], manual: list[dict]) -> list[dict]:
    """Receipts and handwritten lines in one list: date, store, amount."""
    rows = [{"date": r["purchase_date"], "store": r["merchant"], "amount": r["total_amount"]}
            for r in receipts]
    # a handwritten line has a month but no day: count it on the 1st of that month
    rows += [{"date": e["month"] + "-01", "store": e["merchant"] or e["description"],
              "amount": e["estimated_amount"]} for e in manual]
    return rows


def spent(rows: list[dict], start: date, end: date) -> float:
    """Total between two dates, both included."""
    return round(sum(r["amount"] for r in rows if start.isoformat() <= r["date"] <= end.isoformat()), 2)


def month_summary(rows: list[dict], today: date, budget: float | None = None) -> dict:
    """This month so far, the same days of last month, and what is left of the budget."""
    first = today.replace(day=1)
    last_month_first = (first - timedelta(days=1)).replace(day=1)
    last_month_same_day = last_month_first.replace(
        day=min(today.day, calendar.monthrange(last_month_first.year, last_month_first.month)[1]))
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_left = days_in_month - today.day + 1                      # today included
    now = spent(rows, first, today)
    before = spent(rows, last_month_first, last_month_same_day)
    out = {"spent": now, "last_month_same_days": before, "change": round(now - before, 2),
           "days_left": days_left}
    if budget:
        left = round(budget - now, 2)
        out.update({"budget": budget, "left": left, "per_day": round(max(left, 0) / days_left, 2),
                    "used_pct": min(round(now / budget * 100), 100),
                    # on pace = spent no more than the part of the month that has passed
                    "on_pace": now <= budget * today.day / days_in_month})
    return out


def top_stores(rows: list[dict], today: date, n: int = 3) -> list[tuple[str, float]]:
    """Where most of this month's money went."""
    totals: dict[str, float] = {}
    for r in rows:
        if r["date"][:7] == today.strftime("%Y-%m"):
            totals[r["store"]] = round(totals.get(r["store"], 0) + r["amount"], 2)
    return sorted(totals.items(), key=lambda kv: -kv[1])[:n]


# ------------------------------------------------------------- instant answers
# The quick-question buttons on the home screen are answered here, in code, in a split second.
# Every other question still goes to the model.

def _money(x: float) -> str:
    return f"₪{x:,.2f}"


def quick_answer(question: str, receipts: list[dict], manual: list[dict], today: date,
                 budget: float | None = None) -> str | None:
    """The answer to a quick-question button, or None for any other question."""
    rows = purchases(receipts, manual)
    if question == "כמה הוצאתי החודש?":
        s = month_summary(rows, today, budget)
        text = f"החודש נרשמו קניות בסך **{_money(s['spent'])}**."
        if s["last_month_same_days"]:
            word = "יותר" if s["change"] > 0 else "פחות"
            text += f" זה {_money(abs(s['change']))} {word} מאשר באותם ימים בחודש שעבר."
        if budget:
            text += (f" נשארו {_money(s['left'])} מהתקציב, כלומר כ-{_money(s['per_day'])} ליום."
                     if s["left"] >= 0 else f" חרגתם מהתקציב ב-{_money(-s['left'])}.")
        return text
    if question == "איזו אחריות נגמרת?":
        soon = sorted((r for r in receipts if r["warranty_until"]
                       and 0 <= (date.fromisoformat(r["warranty_until"]) - today).days <= 90),
                      key=lambda r: r["warranty_until"])
        if not soon:
            return "אין אחריות שנגמרת ב-3 החודשים הקרובים."
        return "אחריות שנגמרת ב-3 החודשים הקרובים:\n" + "\n".join(
            f"- **{r['product'] or r['merchant']}** ({r['merchant']}): עד "
            f"{date.fromisoformat(r['warranty_until']):%d/%m/%Y}, "
            f"עוד {(date.fromisoformat(r['warranty_until']) - today).days} ימים" for r in soon)
    if question == "איפה הוצאתי הכי הרבה?":
        top = top_stores(rows, today, 5)
        if not top:
            return "עוד אין קניות החודש."
        return "איפה הוצאתם הכי הרבה החודש:\n" + "\n".join(
            f"{i}. **{name}**: {_money(amount)}" for i, (name, amount) in enumerate(top, 1))
    if question == "מה קניתי השבוע?":
        week = sorted((r for r in receipts
                       if (today - timedelta(days=6)).isoformat() <= r["purchase_date"] <= today.isoformat()),
                      key=lambda r: r["purchase_date"], reverse=True)
        if not week:
            return "לא נרשמו קבלות ב-7 הימים האחרונים."
        total = sum(r["total_amount"] for r in week)
        return f"ב-7 הימים האחרונים נרשמו {len(week)} קניות בסך **{_money(total)}**:\n" + "\n".join(
            f"- {date.fromisoformat(r['purchase_date']):%d/%m}: {r['product'] or r['merchant']} "
            f"({r['merchant']}), {_money(r['total_amount'])}" for r in week)
    return None
