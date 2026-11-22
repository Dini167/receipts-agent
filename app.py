"""The website (Streamlit). Run:  streamlit run app.py

Runs only on your own computer. Every stop for approval (interrupt) is shown
with buttons, and the graph continues after you answer.
"""

import csv
import io
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from langgraph.types import Command

from src import db
from src.ai import ModelAI
from src.graph import build_graph
from src.loaders import MAX_FILE_BYTES

UPLOADS = Path(__file__).parent / "data" / "private" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="קבלות ואשראי", page_icon="🧾", layout="centered")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700&display=swap');
html, body, p, li, label, h1, h2, h3, input, textarea, td, th {
    font-family: 'Heebo', sans-serif; }
[data-testid="stIconMaterial"], .material-symbols-rounded {
    font-family: 'Material Symbols Rounded' !important; }
.main, .stMarkdown, .stTextInput, .stButton, .stChatInput textarea, .stAlert,
[data-testid="stCheckbox"], [data-testid="stHeading"], [data-testid="stMetric"],
[data-testid="stCaptionContainer"], [data-testid="stHorizontalBlock"],
[data-testid="stWidgetLabel"] { direction: rtl; text-align: right; }
[data-testid="stHeader"] { display: none; }
.block-container { padding-top: 2rem; max-width: 760px; }
.hero { background: linear-gradient(135deg, #0F766E, #14B8A6); color: white;
        border-radius: 18px; padding: 22px 26px; margin-bottom: 18px; direction: rtl;
        box-shadow: 0 6px 20px rgba(15,118,110,.18); }
.hero h1 { color: white; font-size: 1.7rem; margin: 0 0 4px 0; padding: 0; }
.hero p { margin: 0; opacity: .92; font-size: 1rem; }
[data-testid="stTabs"] [role="tablist"] { direction: rtl; gap: 6px; }
[data-testid="stTabs"] button[role="tab"] { background: white; border-radius: 10px 10px 0 0;
        padding: 8px 18px; font-weight: 500; }
[data-testid="stTabs"] [role="tabpanel"] { background: white; border-radius: 0 0 14px 14px;
        padding: 18px; box-shadow: 0 2px 10px rgba(0,0,0,.05); }
.stButton > button { border-radius: 10px; font-weight: 600; padding: 6px 22px; }
[data-testid="stChatMessage"] { direction: rtl; background: white; border-radius: 14px;
        box-shadow: 0 1px 6px rgba(0,0,0,.05); }
@media (max-width: 640px) {        /* phone: numbers in a 2 x 2 grid instead of one long column */
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: .4rem !important; }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
      flex: 1 1 calc(50% - .4rem) !important; min-width: calc(50% - .4rem) !important; }
  [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
  .hero h1 { font-size: 1.3rem; } .hero p { font-size: .9rem; }
  .block-container { padding-left: 1rem; padding-right: 1rem; }
}
.result { background: white; border-radius: 14px; padding: 18px 22px; direction: rtl;
          border-right: 5px solid #0F766E; box-shadow: 0 2px 10px rgba(0,0,0,.05); }
</style>
<div class="hero"><h1>🧾 קבלות, אחריות ובדיקת אשראי</h1>
<p>מעלים קבלות ודפי קניות, בודקים את פירוט האשראי, ושואלים כל שאלה בתיבה למטה.</p></div>
""", unsafe_allow_html=True)


def friendly(e: Exception) -> str:
    if isinstance(e, ValueError) and any("\u0590" <= ch <= "\u05ff" for ch in str(e)):
        return str(e)                    # our own clear Hebrew message (bad file and so on)
    text = str(e)
    if "RESOURCE_EXHAUSTED" in text and "per day" in text:
        return ("נגמרה המכסה היומית של המודל החינמי. היא מתחדשת בכל יום בסביבות 10:00 בבוקר. "
                "אפשר גם להוסיף ב-‎.env‎ מפתח של Groq או OpenRouter כגיבוי.")
    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        return "המודל החינמי קיבל יותר מדי בקשות בדקה האחרונה. כדאי לחכות כחצי דקה ולנסות שוב."
    if "API key" in text or "API_KEY" in text:
        return "מפתח ה-API לא תקין. כדאי לבדוק את הקובץ ‎.env‎."
    return f"משהו השתבש: {text[:200]}"

if "graph" not in st.session_state:
    st.session_state.graph = build_graph(ModelAI(improved=True))
    st.session_state.thread = None
    st.session_state.out = None
    st.session_state.chat = []      # [(question, answer), ...]
graph = st.session_state.graph


def start(inputs: dict):
    # a new key empties the upload boxes, so the same file is not sent twice by mistake
    st.session_state.upload_n = st.session_state.get("upload_n", 0) + 1
    st.session_state.thread = str(uuid.uuid4())
    st.session_state.kind = inputs["input_kind"]
    st.session_state.last = "upload"    # the newest thing is the upload: hide old chat below it
    st.session_state.error = ""
    with st.spinner("חושב..."):
        t = time.time()
        try:
            st.session_state.out = graph.invoke(inputs, _cfg())
            st.session_state.took = time.time() - t
        except Exception as e:      # show a clear message instead of a long error
            st.session_state.out = None
            st.session_state.error = friendly(e)


def resume(value):
    st.session_state.error = ""
    with st.spinner("ממשיך..."):
        try:
            st.session_state.out = graph.invoke(Command(resume=value), _cfg())
        except Exception as e:
            st.session_state.out = None
            st.session_state.error = friendly(e)


def _cfg():
    return {"configurable": {"thread_id": st.session_state.thread}}


def save_upload(file) -> str | None:
    if file.size > MAX_FILE_BYTES:
        st.error("הקובץ גדול מ-10MB")
        return None
    path = UPLOADS / f"{uuid.uuid4().hex}{Path(file.name).suffix.lower()}"
    path.write_bytes(file.getvalue())
    return str(path)


def ask(question: str):
    """Questions run in their own thread, so they never disturb an upload in progress.

    The answer is streamed: words appear as the model writes them, instead of waiting
    for the whole answer.
    """
    cfg = {"configurable": {"thread_id": f"q-{uuid.uuid4()}"}}
    out = st.session_state.out or {}
    inputs = {"input_kind": "question", "question": question,
              "recent": out.get("answer", "") if st.session_state.get("after_upload") else "",
              "recent_chat": [{"q": q, "a": a[:500]} for q, a, _ in st.session_state.chat[-3:]]}
    with st.chat_message("user", avatar="🙋"):
        st.markdown(question)

    parts: list[str] = []
    model = {"name": ""}
    started = time.time()

    def words():
        for mode, data in graph.stream(inputs, cfg, stream_mode=["messages", "values"]):
            if mode == "messages":
                msg, info = data
                if info.get("langgraph_node") == "write_answer":
                    model["name"] = msg.response_metadata.get("model_name") or model["name"]
                if info.get("langgraph_node") == "write_answer" and msg.text:
                    parts.append(msg.text)
                    yield msg.text
            elif data.get("answer") and not parts:          # answered without the model
                parts.append(data["answer"])
                yield data["answer"]

    with st.chat_message("assistant", avatar="🧾"):
        try:
            st.write_stream(words())
            answer = "".join(parts)
            took = f"{time.time() - started:.1f} שניות" + (f" · {model['name']}" if model["name"] else "")
            if took:
                st.caption(f"⏱️ {took}")
        except Exception as e:
            answer = friendly(e)
            st.error(answer)
            took = ""
    st.session_state.chat.append((question, answer, took))


# The question box is pinned to the bottom of every page. Enter sends.
question = st.chat_input("אפשר לשאול כל שאלה על הקניות וללחוץ Enter")
if question:      # answered at the bottom of the page, so the tabs above stay as they are
    st.session_state.after_upload = st.session_state.get("last") == "upload"
    st.session_state.last = "question"

def check_fixes(fixes: dict) -> str:
    """A short message if a detail typed by the user is not valid, else ''."""
    if "merchant" in fixes and not fixes["merchant"].strip():
        return "יש למלא את שם בית העסק."
    if "purchase_date" in fixes:
        try:
            date.fromisoformat(fixes["purchase_date"].strip())
        except ValueError:
            return "התאריך צריך להיות בצורה 2026-11-22."
    if "total_amount" in fixes:
        try:
            if float(fixes["total_amount"].replace(",", "")) <= 0:
                return "הסכום צריך להיות גדול מאפס."
        except ValueError:
            return "הסכום צריך להיות מספר, למשל 349.90"
    return ""


def run_receipt_queue():
    """Save the uploaded receipts one by one. A receipt with a missing detail stops the
    queue and asks; after the answer the rest continue (see the "שמירה" button below)."""
    while st.session_state.get("queue"):
        start({"input_kind": "receipt", "file_path": st.session_state.queue.pop(0)})
        out = st.session_state.out
        if not out or out.get("__interrupt__"):
            return
        st.session_state.receipt_log.append(out["answer"])


def show_result(kind: str):
    """Show the answer or the approval stop right under the button that started it."""
    if st.session_state.get("kind") != kind:
        return
    out = st.session_state.out
    if st.session_state.get("error"):
        st.error(st.session_state.error)
    if kind == "receipt" and st.session_state.get("receipt_log"):
        for line in st.session_state.receipt_log:
            st.success(line, icon="✅")
        if out and not out.get("__interrupt__"):
            return                                      # the last answer is already in the list
    if out and st.session_state.get("took"):
        st.caption(f"⏱️ {st.session_state.took:.1f} שניות")
    if out:
        if out.get("__interrupt__"):
            stop = out["__interrupt__"][0].value
            if stop["type"] == "missing_fields":
                st.warning("חסרים פרטים בקבלה. יש להשלים אותם לפני השמירה:")
                fixes = {}
                for field in stop["missing"]:
                    label = {"merchant": "בית עסק", "purchase_date": "תאריך (YYYY-MM-DD)",
                             "total_amount": "סכום"}[field]
                    fixes[field] = st.text_input(label, key=f"fix_{field}")
                if st.button("שמירה"):
                    problem = check_fixes(fixes)
                    if problem:
                        st.error(problem)
                    else:
                        if "total_amount" in fixes:
                            fixes["total_amount"] = float(fixes["total_amount"].replace(",", ""))
                        resume(fixes)
                        done = st.session_state.out
                        if done and not done.get("__interrupt__"):
                            st.session_state.setdefault("receipt_log", []).append(done["answer"])
                            run_receipt_queue()
                        st.rerun()

            elif stop["type"] == "confirm_handwritten":
                st.info("זה מה שקראתי מהדף. אפשר לתקן לפני השמירה:")
                edited = st.data_editor(stop["lines"], num_rows="dynamic", key="lines",
                                        use_container_width=True, column_config={
                                            "description": "מה נקנה",
                                            "estimated_amount": st.column_config.NumberColumn(
                                                "סכום משוער (₪)", format="%.2f"),
                                            "merchant": "חנות (אם כתוב)"})
                drop = []
                for d in stop["duplicates"]:
                    line = stop["lines"][d["index"]]
                    if st.checkbox(f"\"{line['description']} {line['estimated_amount']:g}\" כבר מופיע "
                                   f"בדף {d['existing']['source_page']}. זו אותה קנייה (לא לספור פעמיים)",
                                   value=True, key=f"dup{d['index']}"):
                        drop.append(d["index"])
                if st.button("אישור ושמירה"):
                    resume({"lines": edited, "drop": drop})
                    st.rerun()

            elif stop["type"] == "total_mismatch":
                st.error(f"קראתי {stop['count']} חיובים בסך {stop['read_total']:,.2f} ₪, "
                         f"אבל בפירוט כתוב {stop['stated_total']:,.2f} ₪.")
                c1, c2 = st.columns(2)
                if c1.button("להמשיך בכל זאת"):
                    resume(True)
                    st.rerun()
                if c2.button("לעצור"):
                    resume(False)
                    st.rerun()

            elif stop["type"] == "confirm_suspicious":
                st.warning("לא נמצאה קבלה או שורה בכתב יד לחיובים האלה. יש לסמן את החיובים המוכרים:")
                recognized = [c["charge_id"] for c in stop["charges"] if st.checkbox(
                    f"{c['charge_date']} | {c['merchant']} | {c['amount']:,.2f} ₪", key=c["charge_id"])]
                if st.button("סיום והפקת דוח"):
                    resume(recognized)
                    st.rerun()
        elif out.get("summary"):                       # statement report: cards + table
            s = out["summary"]
            st.subheader(f"💳 פירוט אשראי {s['month']}")
            st.caption(f"{s['count']} חיובים, סה\"כ {s['total']:,.2f} ₪. "
                       + ("הסכום תואם לפירוט ✅" if s["ok_total"] else "הסכום לא תואם לפירוט ⚠️"))
            cols = st.columns(4)
            for col, (key, label) in zip(cols, [("matched_receipt", "יש קבלה"),
                                                ("matched_manual", "בכתב יד"),
                                                ("amount_mismatch", "סכום שונה"),
                                                ("unrecognized", "לא מוכר")]):
                col.metric(label, s[key])
            if out.get("exceptions_table"):
                st.markdown("**חיובים שכדאי לבדוק:**")
                st.dataframe(out["exceptions_table"], hide_index=True, use_container_width=True,
                             column_config={"סכום (₪)": st.column_config.NumberColumn(format="%.2f")})
                st.download_button("⬇️ הורדת החיובים לבדיקה (Excel/CSV)", to_csv(out["exceptions_table"]),
                                   file_name=f"charges_to_check_{s['month']}.csv", mime="text/csv")
            else:
                st.success("כל החיובים מוכרים. אין מה לבדוק 🎉")
        else:
            with st.container(border=True):
                st.markdown(out.get("answer", "").replace("*", "\\*").replace("_", "\\_")
                            .replace("\n", "  \n"))


def show_overview():
    """Everything saved, at a glance: numbers, warranties ending soon, and all receipts."""
    today = date.today()
    with db.connect() as c:
        receipts = db.list_receipts(c)
        soon = db.warranties_ending_between(c, today.isoformat(),
                                            (today + timedelta(days=60)).isoformat())
        charges = db.list_checked_charges(c)
    if not receipts and not charges:
        st.info("עוד לא נשמר שום מידע. אפשר להתחיל בהעלאת קבלה או פירוט אשראי.")
        return
    month = today.strftime("%Y-%m")
    active = [r for r in receipts if r["warranty_until"] and r["warranty_until"] >= today.isoformat()]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("קבלות שמורות", len(receipts))
    c2.metric("קניות החודש (₪)", f"{sum(r['total_amount'] for r in receipts if r['purchase_date'][:7] == month):,.0f}")
    c3.metric("אחריות בתוקף", len(active))
    c4.metric("חיובים לא מוכרים", sum(ch["status"] == "unrecognized" for ch in charges))
    if soon:
        st.warning("⏰ אחריות שנגמרת ב-60 הימים הקרובים: " + ", ".join(
            f"{r['product'] or r['merchant']} (עד {date.fromisoformat(r['warranty_until']):%d/%m/%Y})"
            for r in soon))
    if not receipts:
        return
    st.markdown("**כל הקבלות** · אפשר לתקן פרט שנקרא לא נכון, או לסמן קבלה למחיקה")
    table = [{"מחיקה": False, "מס'": r["id"], "תאריך": r["purchase_date"], "בית עסק": r["merchant"],
              "מוצר": r["product"] or "", "סכום (₪)": r["total_amount"],
              "תשלומים": r["installments"], "אחריות עד": r["warranty_until"] or ""}
             for r in reversed(receipts)]
    edited = st.data_editor(table, hide_index=True, use_container_width=True, key="all_receipts",
                            disabled=["מס'", "תשלומים"],
                            column_config={"מס'": None,
                                           "סכום (₪)": st.column_config.NumberColumn(format="%.2f", min_value=0)})
    changed = [row for row, old in zip(edited, table) if row != old and not row["מחיקה"]]
    marked = [row["מס'"] for row in edited if row["מחיקה"]]
    c1, c2, c3 = st.columns(3)
    if changed and c1.button(f"💾 שמירת {len(changed)} תיקונים"):
        bad = [row for row in changed if not (_valid_date(row["תאריך"]) and
               (not row["אחריות עד"] or _valid_date(row["אחריות עד"])) and row["בית עסק"].strip())]
        if bad:
            st.error("יש לתקן: תאריכים בצורה 2026-11-22, ושם בית עסק לא ריק.")
        else:
            with db.connect() as c:
                for row in changed:
                    db.update_receipt(c, row["מס'"], row["בית עסק"].strip(), row["תאריך"],
                                      float(row["סכום (₪)"]), row["מוצר"] or None,
                                      row["אחריות עד"] or None)
            st.rerun()
    if marked and c2.button(f"🗑️ מחיקת {len(marked)} קבלות"):
        with db.connect() as c:
            for rid in marked:
                db.delete_receipt(c, rid)
        st.rerun()
    c3.download_button("⬇️ גיבוי כל הקבלות (CSV)", to_csv([{k: v for k, v in row.items() if k != "מחיקה"}
                                                          for row in table]),
                       file_name=f"receipts_backup_{today:%Y_%m_%d}.csv", mime="text/csv")


def _valid_date(text: str) -> bool:
    try:
        date.fromisoformat(str(text).strip())
        return True
    except ValueError:
        return False


def to_csv(rows: list[dict]) -> bytes:
    """CSV that Excel opens correctly in Hebrew (UTF-8 with BOM)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


tab_overview, tab_receipt, tab_hand, tab_statement = st.tabs(
    ["📊 סקירה", "🧾 קבלה", "✍️ דף בכתב יד", "💳 פירוט אשראי"])

with tab_overview:
    show_overview()

with tab_receipt:
    files = st.file_uploader("העלאת קבלות (אפשר כמה יחד)", type=["png", "jpg", "jpeg", "txt"],
                             key=f"r{st.session_state.get('upload_n', 0)}", accept_multiple_files=True)
    if files and st.button(f"שמירת {len(files)} קבלות" if len(files) > 1 else "שמירת קבלה"):
        st.session_state.queue = [p for p in map(save_upload, files) if p]
        st.session_state.receipt_log = []
        run_receipt_queue()
        st.rerun()   # empties the upload box
    show_result("receipt")

with tab_hand:
    f = st.file_uploader("צילום דף קניות בכתב יד", type=["png", "jpg", "jpeg"], key=f"h{st.session_state.get('upload_n', 0)}")
    month = st.text_input("חודש (YYYY-MM)", value=date.today().strftime("%Y-%m"))
    if f and st.button("קריאת הדף"):
        if path := save_upload(f):
            start({"input_kind": "handwritten", "file_path": path, **({"month": month} if month else {})})
            st.rerun()   # empties the upload box
    show_result("handwritten")

with tab_statement:
    f = st.file_uploader("העלאת פירוט אשראי", type=["pdf", "csv", "xlsx"], key=f"s{st.session_state.get('upload_n', 0)}")
    if f and st.button("בדיקת הפירוט"):
        if path := save_upload(f):
            start({"input_kind": "statement", "file_path": path})
            st.rerun()   # empties the upload box
    show_result("statement")

# Old questions are shown only when a question was the last thing done, so an upload
# result is never pushed up the page by older chat.
if (st.session_state.chat or question) and st.session_state.get("last") != "upload":
    st.divider()
    for q, a, took in st.session_state.chat[-5:]:
        with st.chat_message("user", avatar="🙋"):
            st.markdown(q)
        with st.chat_message("assistant", avatar="🧾"):
            st.markdown(a.replace("\n", "  \n"))
            if took:
                st.caption(f"⏱️ {took}")

if question:
    ask(question)
