"""Matching charges to receipts and handwritten lines, in plain code.

The numbers come straight from section 3ב of the prompt. The model is used
for one thing only: deciding whether two store names are the same business
(passed in as `same_merchant`), so the results are predictable and testable.
"""

from datetime import date
from typing import Callable

AMOUNT_TOLERANCE = 1.0      # shekels, for rounding
REGULAR_DAYS = 3            # regular match: charge up to 3 days after purchase
LOOSE_DAYS = [7, 14]        # loose match attempts 1 and 2
MANUAL_TOLERANCE = 0.10     # handwritten lines: up to 10% off

SameMerchant = Callable[[str, str], bool]


def _months_later(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + y, month=m + 1, day=min(d.day, 28))


def installment_info(charge: dict) -> tuple[int, int]:
    """'3/6' -> (3, 6). No installment -> (1, 1)."""
    if charge.get("installment") and "/" in charge["installment"]:
        k, n = charge["installment"].split("/")
        return int(k), int(n)
    return 1, 1


def expected_for(charge: dict, receipt: dict) -> tuple[float, date]:
    """What this receipt should cost in this charge, and when it should be charged."""
    k, n = installment_info(charge)
    purchase = date.fromisoformat(receipt["purchase_date"])
    if n > 1:
        return round(receipt["total_amount"] / n, 2), _months_later(purchase, k - 1)
    return receipt["total_amount"], purchase


def match_to_receipt(charge: dict, receipts: list[dict], used: set[int],
                     same_merchant: SameMerchant, max_days: int) -> dict | None:
    """Find a receipt for one charge. Returns a result dict or None."""
    charged_on = date.fromisoformat(charge["charge_date"])
    mismatch = None
    for r in receipts:
        if r["id"] in used:
            continue
        amount, due = expected_for(charge, r)
        days = (charged_on - due).days
        if not 0 <= days <= max_days:
            continue
        if not same_merchant(charge["merchant"], r["merchant"]):
            continue
        if abs(charge["amount"] - amount) <= AMOUNT_TOLERANCE:
            return {"charge_id": charge["charge_id"], "status": "matched_receipt",
                    "matched_id": r["id"], "expected_amount": amount,
                    "reason": f"קבלה מ{r['merchant']}, {days} ימים אחרי הקנייה"}
        mismatch = mismatch or {
            "charge_id": charge["charge_id"], "status": "amount_mismatch",
            "matched_id": r["id"], "expected_amount": amount,
            "reason": f"נגבו {charge['amount']:,.2f} ₪, צפוי {amount:,.2f} ₪ "
                      f"(הפרש {charge['amount'] - amount:+,.2f} ₪)"}
    return mismatch


def candidate_pairs(charges: list[dict], receipts: list[dict], used: set[int],
                    max_days: int) -> list[tuple[str, str]]:
    """Store-name pairs that match_to_receipt may ask about (date fits), to ask in one go."""
    pairs = set()
    for c in charges:
        charged_on = date.fromisoformat(c["charge_date"])
        for r in receipts:
            if r["id"] in used:
                continue
            if 0 <= (charged_on - expected_for(c, r)[1]).days <= max_days:
                pairs.add((c["merchant"], r["merchant"]))
    return sorted(pairs)


def manual_pairs(charges: list[dict], entries: list[dict]) -> list[tuple[dict, dict]]:
    """(charge, line) pairs close enough in amount that match_to_manual may check them."""
    return [(c, e) for c in charges for e in entries
            if e["month"] == c["charge_date"][:7]
            and abs(c["amount"] - e["estimated_amount"]) / e["estimated_amount"] <= MANUAL_TOLERANCE]


def match_to_manual(charges: list[dict], entries: list[dict],
                    fits: Callable[[dict, dict], bool] | None = None) -> dict[str, dict]:
    """Match leftover charges to handwritten lines of the same month.

    Pairs are assigned closest-amount first, so one line is never used twice.
    `fits(charge, entry)` is an optional extra check (does the description fit
    the store?), used in the improved version.
    """
    pairs = []
    for c in charges:
        month = c["charge_date"][:7]
        for e in entries:
            if e["month"] != month:
                continue
            diff = abs(c["amount"] - e["estimated_amount"]) / e["estimated_amount"]
            if diff <= MANUAL_TOLERANCE:
                pairs.append((diff, c["charge_id"], e["id"], c, e))
    pairs.sort(key=lambda p: (p[0], p[1]))
    results, used_c, used_e = {}, set(), set()
    for diff, cid, eid, c, e in pairs:
        if cid in used_c or eid in used_e:
            continue
        if fits and not fits(c, e):
            continue
        used_c.add(cid)
        used_e.add(eid)
        results[cid] = {"charge_id": cid, "status": "matched_manual", "matched_id": eid,
                        "expected_amount": e["estimated_amount"],
                        "reason": f"שורה בכתב יד: {e['description']} {e['estimated_amount']:g} "
                                  f"(הפרש {diff:.0%})"}
    return results


def find_duplicate_lines(new_lines: list[dict], existing: list[dict]) -> list[tuple[int, dict]]:
    """Handwritten lines that look like a line already saved (same text, amount within 10%)."""
    dups = []
    for i, n in enumerate(new_lines):
        for e in existing:
            if (n["description"].strip() == e["description"].strip()
                    and abs(n["estimated_amount"] - e["estimated_amount"])
                    <= MANUAL_TOLERANCE * e["estimated_amount"]):
                dups.append((i, e))
                break
    return dups


def summarize(results: list[dict], charges: list[dict]) -> dict:
    counts = {s: 0 for s in ("matched_receipt", "matched_manual", "amount_mismatch", "unrecognized")}
    for r in results:
        counts[r["status"]] += 1
    return {"count": len(charges), "total": round(sum(c["amount"] for c in charges), 2), **counts}
