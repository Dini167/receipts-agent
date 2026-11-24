"""A fake model for tests: same methods as ModelAI, fixed answers, no API keys."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# what a perfect model would answer for "same business?"
SAME = {
    ("SHUFERSAL DEAL", "שופרסל דיל"), ("MACHSANEY HASHMAL", "מחסני חשמל"),
    ("רמי לוי שיווק השקמה", "רמי לוי"), ("SUPER-PHARM", "סופר-פארם"),
    ("ACE AUTO DEPOT", "ACE"), ("BUG MULTISYSTEM", "באג מולטיסיסטם"),
    ("PAZ YELLOW", "פז"), ("IKEA NETANYA", "איקאה"), ("CAFE GREG", "קפה גרג"),
    ("TIV TAAM", "טיב טעם"), ("TZOMET SFARIM", "צומת ספרים"),
    ("HOME CENTER", "הום סנטר"), ("GOOD PHARM", "גוד פארם"),
}


# pairs a good model rejects: similar amount, but the store sells something else
NOT_FITS = {("GYM ACTIVE", "מסעדה")}


class FakeAI:
    def __init__(self, receipt=None, handwritten=None, query=None):
        self.receipt = receipt
        self.handwritten = handwritten
        self.query = query

    def image_kind(self, path):
        return "handwritten" if "page" in Path(path).name else "receipt"

    def extract_receipt(self, path):
        return dict(self.receipt)

    def read_handwritten(self, path):
        return [dict(l) for l in self.handwritten]

    def read_scanned_statement(self, image_paths):
        return [], None

    def same_merchant(self, a, b):
        return (a, b) in SAME

    def manual_fits(self, charge, entry):
        return (charge["merchant"], entry["description"]) not in NOT_FITS

    def write_answer(self, question, context):
        return "; ".join(f"{r['product']} עד {r['warranty_until']}" for r in context["receipts"])


def load_truth_into_db(conn, db):
    """Fill the DB with the correct receipts and handwritten lines (repeats removed)."""
    for r in json.loads((ROOT / "eval" / "receipts_truth.json").read_text(encoding="utf-8")):
        r["db_id"] = db.add_receipt(conn, r["merchant"], r["purchase_date"], r["total_amount"],
                                    r["product"], r["installments"], r["warranty_until"])
    for e in json.loads((ROOT / "eval" / "handwritten_truth.json").read_text(encoding="utf-8")):
        if not e["duplicate_of"]:
            db.add_manual_entry(conn, e["month"], e["description"], e["estimated_amount"],
                                e["source_page"])
