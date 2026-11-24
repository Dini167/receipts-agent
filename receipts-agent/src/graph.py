"""The LangGraph graph: router + four flows (receipt, handwritten, statement, question).

Picture (section 4 of the prompt):

  router ─┬─ receipt     → extract_receipt → [missing?] → ask_receipt_fields (interrupt) → save_receipt
          ├─ handwritten → read_handwritten → confirm_handwritten (interrupt) → save_handwritten
          ├─ statement   → read_statement → check_total (interrupt if totals differ)
          │                → match_regular → [pending?] → loose_match (loop, max 2)
          │                → match_manual → [unrecognized?] → confirm_suspicious (interrupt) → report
          └─ question    → gather_context → write_answer
"""

from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import db, matching
from .loaders import check_upload, load_statement
from .state import AgentState

STATEMENT_TYPES = {".pdf", ".csv", ".xlsx"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg"}
REQUIRED_RECEIPT_FIELDS = ("merchant", "purchase_date", "total_amount")
STATUS_HE = {
    "matched_receipt": "תואמים לקבלה",
    "matched_manual": "תואמים לרשימה בכתב יד",
    "amount_mismatch": "סכום שונה",
    "unrecognized": "לא מוכרים",
}


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + y, month=m + 1, day=min(d.day, 28))


def _sum_by(rows: list[dict], key, field: str) -> dict:
    totals: dict = {}
    for r in rows:
        totals[key(r)] = round(totals.get(key(r), 0) + r[field], 2)
    return totals


def build_graph(ai, db_path=db.DEFAULT_DB_PATH, checkpointer=None, today: date | None = None,
                precompute: bool = True):
    """Build the agent. `ai` is a ModelAI (real models) or a fake for tests.

    precompute=False gives the model only the raw rows (no days left, no sums, no counts).
    It exists only for the "before" experiment of the questions evaluation.
    """

    def conn():
        return closing(db.connect(db_path))

    def now() -> date:
        return today or date.today()

    # ------------------------------------------------------------- router
    def router(state: AgentState) -> dict:
        """Decide what the user gave us: receipt, statement, handwritten page or question."""
        if state.get("input_kind"):
            return {}
        if state.get("question") and not state.get("file_path"):
            return {"input_kind": "question"}
        suffix = Path(state["file_path"]).suffix.lower()
        if suffix in STATEMENT_TYPES:
            return {"input_kind": "statement"}
        if suffix == ".txt":
            return {"input_kind": "receipt"}
        return {"input_kind": ai.image_kind(state["file_path"])}

    # ------------------------------------------------------------- receipt flow
    def extract_receipt(state: AgentState) -> dict:
        """Read the receipt fields with the model."""
        return {"receipt": ai.extract_receipt(state["file_path"])}

    def missing_fields(state: AgentState) -> list[str]:
        return [f for f in REQUIRED_RECEIPT_FIELDS if not state["receipt"].get(f)]

    def ask_receipt_fields(state: AgentState) -> dict:
        """INTERRUPT: a required field is missing, ask the user before saving."""
        fixes = interrupt({"type": "missing_fields", "receipt": state["receipt"],
                           "missing": missing_fields(state)})
        return {"receipt": {**state["receipt"], **(fixes or {})}}

    def save_receipt(state: AgentState) -> dict:
        """Save the receipt and work out when the warranty ends."""
        r = state["receipt"]
        until = None
        if r.get("warranty_months"):
            until = _add_months(date.fromisoformat(r["purchase_date"]),
                                r["warranty_months"]).isoformat()
        with conn() as c:
            if db.find_same_receipt(c, r["merchant"], r["purchase_date"], float(r["total_amount"])):
                return {"answer": f"הקבלה מ{r['merchant']} על סך {float(r['total_amount']):,.2f} ₪ "
                                  f"מ-{date.fromisoformat(r['purchase_date']):%d/%m/%Y} כבר שמורה, "
                                  "ולכן לא שמרתי אותה שוב."}
            db.add_receipt(c, r["merchant"], r["purchase_date"], float(r["total_amount"]),
                           r.get("product"), r.get("installments") or 1, until)
        msg = f"שמרתי קבלה מ{r['merchant']} על סך {float(r['total_amount']):,.2f} ₪."
        if until:
            msg += f" האחריות בתוקף עד {date.fromisoformat(until):%d/%m/%Y}."
        return {"answer": msg}

    # ------------------------------------------------------------- handwritten flow
    def read_handwritten(state: AgentState) -> dict:
        """Read the page with a model that can read images, and look for repeated lines."""
        month = state.get("month") or now().strftime("%Y-%m")
        lines = ai.read_handwritten(state["file_path"])
        with conn() as c:
            existing = db.list_manual_entries(c, month)
        dups = [{"index": i, "existing": e}
                for i, e in matching.find_duplicate_lines(lines, existing)]
        return {"month": month, "lines": lines, "duplicates": dups}

    def confirm_handwritten(state: AgentState) -> dict:
        """INTERRUPT: show what was read, let the user fix it and decide about repeats.

        Resume with {"lines": [...], "drop": [indexes]} or True to accept as is.
        """
        decision = interrupt({"type": "confirm_handwritten", "lines": state["lines"],
                              "duplicates": state["duplicates"]})
        if decision is True or decision is None:
            return {}
        lines = decision.get("lines", state["lines"])
        drop = set(decision.get("drop", []))
        return {"lines": [l for i, l in enumerate(lines) if i not in drop]}

    def save_handwritten(state: AgentState) -> dict:
        with conn() as c:
            page = db.next_page_number(c, state["month"])
            for l in state["lines"]:
                db.add_manual_entry(c, state["month"], l["description"],
                                    float(l["estimated_amount"]), page, l.get("merchant"))
        return {"answer": f"שמרתי {len(state['lines'])} שורות מדף {page} של {state['month']}."}

    # ------------------------------------------------------------- statement flow
    def read_statement(state: AgentState) -> dict:
        """Read the charges from PDF / CSV / Excel. A scanned PDF goes to the model."""
        path = check_upload(state["file_path"])
        charges, total = load_statement(path)
        if not charges and path.suffix.lower() == ".pdf":
            import pdfplumber
            images = []
            with pdfplumber.open(path) as pdf:
                for i, page in enumerate(pdf.pages):
                    out = path.with_name(f"{path.stem}_page{i + 1}.png")
                    page.to_image(resolution=150).original.save(out)
                    images.append(str(out))
            charges, total = ai.read_scanned_statement(images)
        return {"charges": charges, "stated_total": total, "results": {},
                "pending": [c["charge_id"] for c in charges], "used_receipts": [],
                "retry_count": 0}

    def check_total(state: AgentState) -> dict:
        """INTERRUPT if the charges we read don't add up to the printed total."""
        read_total = round(sum(c["amount"] for c in state["charges"]), 2)
        stated = state.get("stated_total")
        if stated is None or abs(read_total - stated) <= 1:
            return {}
        ok = interrupt({"type": "total_mismatch", "read_total": read_total,
                        "stated_total": stated, "count": len(state["charges"])})
        if not ok:
            return {"answer": "עצרתי: הסכום שנקרא לא תואם לפירוט. כדאי לבדוק את הקובץ.",
                    "pending": [], "charges": []}
        return {}

    def _match_receipts(state: AgentState, max_days: int) -> dict:
        with conn() as c:
            receipts = db.list_receipts(c)
        used = set(state["used_receipts"])
        results = dict(state["results"])
        pending = []
        by_id = {c["charge_id"]: c for c in state["charges"]}
        if hasattr(ai, "prefetch_same"):    # one model request for every name pair
            # widest window up front, so the loose-match rounds need no new request
            ai.prefetch_same(matching.candidate_pairs(
                [by_id[cid] for cid in state["pending"]], receipts, used, matching.LOOSE_DAYS[-1]))
        for cid in state["pending"]:
            res = matching.match_to_receipt(by_id[cid], receipts, used,
                                            ai.same_merchant, max_days)
            if res:
                results[cid] = res
                used.add(res["matched_id"])
            else:
                pending.append(cid)
        return {"results": results, "pending": pending, "used_receipts": sorted(used)}

    def match_regular(state: AgentState) -> dict:
        """Regular match: same store, amount within 1 ₪, charged up to 3 days later."""
        return _match_receipts(state, matching.REGULAR_DAYS)

    def loose_match(state: AgentState) -> dict:
        """Loose match (loop): wider date window. Attempt 1 = 7 days, attempt 2 = 14 days."""
        days = matching.LOOSE_DAYS[state["retry_count"]]
        return {**_match_receipts(state, days), "retry_count": state["retry_count"] + 1}

    def match_manual(state: AgentState) -> dict:
        """Charges still without a receipt are compared to this month's handwritten lines."""
        by_id = {c["charge_id"]: c for c in state["charges"]}
        months = {by_id[cid]["charge_date"][:7] for cid in state["pending"]}
        with conn() as c:
            entries = [e for m in months for e in db.list_manual_entries(c, m)]
        left = [by_id[cid] for cid in state["pending"]]
        if hasattr(ai, "prefetch_fits"):    # one model request for every close pair
            ai.prefetch_fits(matching.manual_pairs(left, entries))
        found = matching.match_to_manual(left, entries, ai.manual_fits)
        results = {**state["results"], **found}
        for cid in state["pending"]:
            if cid not in found:
                results[cid] = {"charge_id": cid, "status": "unrecognized", "matched_id": None,
                                "expected_amount": None, "suspicious": True,
                                "reason": "לא נמצאה קבלה ולא שורה בכתב יד"}
        return {"results": results, "pending": []}

    def confirm_suspicious(state: AgentState) -> dict:
        """INTERRUPT: before marking charges as suspicious, ask the user.

        Resume with a list of charge ids the user recognizes (empty list = all suspicious).
        """
        unknown = [c for c in state["charges"]
                   if state["results"][c["charge_id"]]["status"] == "unrecognized"]
        recognized = interrupt({"type": "confirm_suspicious", "charges": unknown}) or []
        results = dict(state["results"])
        for cid in recognized:
            results[cid] = {**results[cid], "suspicious": False,
                            "reason": "המשתמשת אישרה שזו קנייה שלה"}
        return {"results": results}

    def report(state: AgentState) -> dict:
        """Build the summary report (format from section 5ג of the prompt)."""
        charges = state["charges"]
        results = [state["results"][c["charge_id"]] for c in charges]
        s = matching.summarize(results, charges)
        month = charges[0]["charge_date"][:7] if charges else ""
        ok_total = state.get("stated_total") is None or abs(s["total"] - state["stated_total"]) <= 1
        lines = [f"פירוט אשראי, {month}",
                 f"{s['count']} חיובים | סה\"כ {s['total']:,.2f} ₪ | "
                 + ("הסכום תואם לסכום בפירוט" if ok_total else "הסכום לא תואם לפירוט"), ""]
        for key, label in STATUS_HE.items():
            lines.append(f"{label} {'.' * (26 - len(label))} {s[key]}")
        by_id = {c["charge_id"]: c for c in charges}
        exceptions = [r for r in results if r["status"] == "amount_mismatch"
                      or (r["status"] == "unrecognized" and r.get("suspicious", True))]
        if exceptions:
            lines += ["", "פירוט החריגים:"]
            for r in exceptions:
                c = by_id[r["charge_id"]]
                lines.append(f"• {c['merchant']}, {c['charge_date'][8:]}/{c['charge_date'][5:7]}"
                             f" | {c['amount']:,.2f} ₪ | {r['reason']}")
        with conn() as cn:
            db.save_checked_charges(cn, charges, state["results"])
            ending = db.warranties_ending_between(
                cn, now().isoformat(), (now() + timedelta(days=30)).isoformat())
        if ending:
            lines += ["", "אחריות שנגמרת ב-30 הימים הקרובים:"]
            for r in ending:
                lines.append(f"• {r['product']}, נקנה ב{r['merchant']} | עד "
                             f"{date.fromisoformat(r['warranty_until']):%d/%m/%Y}")
        table = [{"תאריך": f"{by_id[r['charge_id']]['charge_date'][8:]}/{by_id[r['charge_id']]['charge_date'][5:7]}",
                  "בית עסק": by_id[r["charge_id"]]["merchant"],
                  "סכום (₪)": by_id[r["charge_id"]]["amount"], "למה": r["reason"]}
                 for r in exceptions]
        return {"answer": "\n".join(lines), "summary": {**s, "month": month, "ok_total": ok_total},
                "exceptions_table": table}

    # ------------------------------------------------------------- question flow
    def gather_context(state: AgentState) -> dict:
        """Collect everything saved: receipts, handwritten lines and checked statements.

        A family has at most a few hundred rows, so the model gets all of them and can
        answer any kind of question (compare, rank, sum, filter). It never writes SQL.
        """
        with conn() as c:
            context = {
                "today": now().isoformat(),
                "receipts": db.list_receipts(c),
                "handwritten_lines": [e for e in c.execute(
                    "SELECT month, description, estimated_amount, merchant, source_page "
                    "FROM manual_entries ORDER BY month, source_page").fetchall()],
                "checked_charges": db.list_checked_charges(c),
            }
        context["handwritten_lines"] = [dict(r) for r in context["handwritten_lines"]]
        context["recent"] = state.get("recent", "")
        context["recent_chat"] = state.get("recent_chat", [])
        if not precompute:
            return {"context": context}
        # Date math is done here, in code: models often get it wrong.
        today = now()
        for r in context["receipts"]:
            r["days_since_purchase"] = (today - date.fromisoformat(r["purchase_date"])).days
            if not r.get("warranty_until"):
                r["warranty_status"] = "אין אחריות"
                continue
            left = (date.fromisoformat(r["warranty_until"]) - today).days
            r["warranty_days_left"] = left
            r["warranty_months_left"] = round(left / 30.4, 1)
            r["warranty_status"] = "בתוקף" if left >= 0 else "נגמרה"
        charges = context["checked_charges"]
        context["summary"] = {          # counts done in code, so the model never miscounts
            "receipts": len(context["receipts"]),
            "warranties_active": sum(r.get("warranty_status") == "בתוקף" for r in context["receipts"]),
            "handwritten_lines": len(context["handwritten_lines"]),
            "checked_charges": len(charges),
            # sums done in code too: models often add long lists of numbers wrongly
            "receipts_total_by_month": _sum_by(context["receipts"], lambda r: r["purchase_date"][:7], "total_amount"),
            "receipts_total_by_merchant": _sum_by(context["receipts"], lambda r: r["merchant"], "total_amount"),
            "handwritten_total_by_month": _sum_by(context["handwritten_lines"], lambda e: e["month"], "estimated_amount"),
            "charges_total_by_month": _sum_by(charges, lambda c: c["month"], "amount"),
            "charges_by_status": {s: sum(c["status"] == s for c in charges)
                                  for s in ("matched_receipt", "matched_manual",
                                            "amount_mismatch", "unrecognized")},
        }
        return {"context": context}

    def write_answer(state: AgentState) -> dict:
        ctx = state["context"]
        if not (ctx["receipts"] or ctx["handwritten_lines"] or ctx["checked_charges"]):
            return {"answer": "עוד לא נשמר שום מידע. אפשר להעלות קבלה, דף בכתב יד או פירוט אשראי."}
        return {"answer": ai.write_answer(state["question"], ctx)}

    # ------------------------------------------------------------- wiring
    g = StateGraph(AgentState)
    for fn in (router, extract_receipt, ask_receipt_fields, save_receipt,
               read_handwritten, confirm_handwritten, save_handwritten,
               read_statement, check_total, match_regular, loose_match, match_manual,
               confirm_suspicious, report, gather_context, write_answer):
        g.add_node(fn.__name__, fn)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", lambda s: s["input_kind"], {
        "receipt": "extract_receipt", "handwritten": "read_handwritten",
        "statement": "read_statement", "question": "gather_context"})

    g.add_conditional_edges("extract_receipt",
                            lambda s: "ask" if missing_fields(s) else "save",
                            {"ask": "ask_receipt_fields", "save": "save_receipt"})
    g.add_edge("ask_receipt_fields", "save_receipt")
    g.add_edge("save_receipt", END)

    g.add_edge("read_handwritten", "confirm_handwritten")
    g.add_edge("confirm_handwritten", "save_handwritten")
    g.add_edge("save_handwritten", END)

    g.add_edge("read_statement", "check_total")
    g.add_conditional_edges("check_total", lambda s: "go" if s["charges"] else "stop",
                            {"go": "match_regular", "stop": END})

    def after_receipt_match(s):
        if s["pending"] and s["retry_count"] < len(matching.LOOSE_DAYS):
            return "loose"
        return "manual"

    g.add_conditional_edges("match_regular", after_receipt_match,
                            {"loose": "loose_match", "manual": "match_manual"})
    g.add_conditional_edges("loose_match", after_receipt_match,
                            {"loose": "loose_match", "manual": "match_manual"})
    g.add_conditional_edges(
        "match_manual",
        lambda s: "ask" if any(r["status"] == "unrecognized" for r in s["results"].values())
        else "report",
        {"ask": "confirm_suspicious", "report": "report"})
    g.add_edge("confirm_suspicious", "report")
    g.add_edge("report", END)

    g.add_edge("gather_context", "write_answer")
    g.add_edge("write_answer", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())
