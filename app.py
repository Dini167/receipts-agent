"""The website (Streamlit). Run:  streamlit run app.py

Three tabs: home (what needs attention now), add (one place for every kind of file),
and all receipts (search, and an edit mode for fixes). Every stop for approval
(interrupt) is shown with buttons, and the graph continues after you answer.
"""

import csv
import html
import io
import os
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from langgraph.types import Command

st.set_page_config(page_title="הקבלות שלי", page_icon="🧾", layout="centered")

# On Streamlit Cloud the keys are kept in "Secrets" instead of a .env file.
# Copy them into the environment, where src/llm.py looks for them.
try:
    for _key, _value in st.secrets.items():
        if isinstance(_value, (str, int, float)):
            os.environ.setdefault(_key, str(_value))
except Exception:            # no secrets file: running on your own computer with .env
    pass

from src import db, insights  # noqa: E402  (after the secrets, so the models see the keys)
from src.ai import ModelAI  # noqa: E402
from src.graph import add_months, build_graph  # noqa: E402
from src.loaders import MAX_FILE_BYTES, file_kind  # noqa: E402
from src.reminders import days_left, warranty_calendar  # noqa: E402

UPLOADS = Path(__file__).parent / "data" / "private" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
STATEMENT_TYPES = {".pdf", ".csv", ".xlsx"}
MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
          "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;600;700;800&display=swap');
:root { --teal: #0F766E; --teal-2: #14B8A6; --ink: #1F2937; --muted: #6B7280;
        --line: #E5ECEA; --card: #FFFFFF; --amber: #B45309; --amber-bg: #FFF7E6;
        --red: #B91C1C; --red-bg: #FEF2F2; --green: #047857; --green-bg: #ECFDF5; }
html, body, p, li, label, h1, h2, h3, h4, h5, input, textarea, td, th, button {
    font-family: 'Heebo', sans-serif; }
[data-testid="stIconMaterial"], .material-symbols-rounded {
    font-family: 'Material Symbols Rounded' !important; }
.main, .stMarkdown, .stTextInput, .stButton, .stChatInput textarea, .stAlert,
[data-testid="stCheckbox"], [data-testid="stHeading"], [data-testid="stMetric"],
[data-testid="stCaptionContainer"], [data-testid="stHorizontalBlock"], [data-testid="stToggle"],
[data-testid="stWidgetLabel"], [data-testid="stFileUploader"], [data-testid="stCameraInput"] {
    direction: rtl; text-align: right; }
[data-testid="stHeader"], [data-testid="stToolbar"], footer, #MainMenu { display: none; }
/* no grey-out while the page refreshes after a click: it looked like the site was stuck */
[data-stale="true"] { opacity: 1 !important; transition: none !important; }
.block-container { padding-top: 1.4rem; padding-bottom: 6rem; max-width: 760px; }

/* header */
.hero { background: linear-gradient(135deg, #0B5F58 0%, #0F766E 45%, #14B8A6 100%); color: white;
        border-radius: 20px; padding: 18px 22px; margin-bottom: 14px; direction: rtl;
        box-shadow: 0 10px 30px rgba(15,118,110,.22); position: relative; overflow: hidden; }
.hero .hi { font-size: .95rem; opacity: .9; margin: 0; }
.hero h1 { color: white; font-size: 1.55rem; font-weight: 800; margin: 2px 0 0 0; padding: 0; }

/* navigation: a soft pill bar (only the chosen page is drawn) */
.st-key-nav, .st-key-nav [data-testid="stElementContainer"], .st-key-nav [data-testid="stButtonGroup"] {
        width: 100% !important; }
.st-key-nav [role="radiogroup"] { direction: rtl; display: flex; width: 100%; max-width: none !important; gap: 4px; background: #E6EFEC;
        padding: 4px; border-radius: 14px; margin-bottom: 6px; }
.st-key-nav button { flex: 1; justify-content: center; border: none !important; border-radius: 10px !important;
        background: transparent !important; color: var(--muted) !important; padding: 8px 6px; box-shadow: none; }
.st-key-nav button p { font-weight: 600; font-size: .98rem; }
.st-key-nav button[aria-checked="true"] { background: white !important; color: var(--teal) !important;
        box-shadow: 0 2px 8px rgba(0,0,0,.07); }

/* buttons */
.stButton > button, .stDownloadButton > button { border-radius: 12px; font-weight: 600; padding: 8px 22px; }
.stButton > button[kind="primary"] { box-shadow: 0 4px 14px rgba(15,118,110,.25); }

/* number cards */
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; direction: rtl; margin-bottom: 14px; }
.stat { background: var(--card); border-radius: 16px; padding: 14px 16px; box-shadow: 0 2px 10px rgba(0,0,0,.05); }
.stat .num { font-size: 1.7rem; font-weight: 800; color: var(--ink); line-height: 1.1; }
.stat .lbl { font-size: .85rem; color: var(--muted); margin-top: 4px; }
.stat.alert .num { color: var(--red); }

/* section title */
.sec { direction: rtl; font-weight: 700; font-size: 1.05rem; color: var(--ink); margin: 18px 0 8px; }

/* "needs attention" rows */
.todo { direction: rtl; display: flex; gap: 12px; align-items: flex-start; background: var(--card);
        border-radius: 14px; padding: 12px 14px; margin-bottom: 8px; box-shadow: 0 1px 6px rgba(0,0,0,.05);
        border-right: 4px solid var(--amber); }
.todo.red { border-right-color: var(--red); } .todo.teal { border-right-color: var(--teal); }
.todo .ic { font-size: 1.3rem; line-height: 1.4; }
.todo .t { font-weight: 600; color: var(--ink); } .todo .s { font-size: .88rem; color: var(--muted); }
.allgood { direction: rtl; background: var(--green-bg); color: var(--green); border-radius: 14px;
        padding: 14px 16px; font-weight: 600; }

/* receipt cards */
.rcard { direction: rtl; display: flex; justify-content: space-between; align-items: center; gap: 12px;
         background: var(--card); border-radius: 14px; padding: 12px 16px; margin-bottom: 8px;
         box-shadow: 0 1px 6px rgba(0,0,0,.05); }
.rcard .title { font-weight: 700; color: var(--ink); }
.rcard .sub { font-size: .85rem; color: var(--muted); }
.rcard .side { text-align: left; white-space: nowrap; }
.rcard .amt { font-weight: 800; color: var(--ink); font-size: 1.05rem; }
.badge { display: inline-block; font-size: .75rem; font-weight: 600; border-radius: 999px; padding: 2px 9px;
         margin-top: 3px; }
.badge.ok { background: var(--green-bg); color: var(--green); }
.badge.soon { background: var(--amber-bg); color: var(--amber); }
.badge.off { background: #F3F4F6; color: var(--muted); }

/* first visit: three steps */
.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; direction: rtl; }
.step { background: var(--card); border-radius: 16px; padding: 16px; box-shadow: 0 2px 10px rgba(0,0,0,.05); }
.step .n { width: 28px; height: 28px; border-radius: 50%; background: var(--teal); color: white;
           display: flex; align-items: center; justify-content: center; font-weight: 700; margin-bottom: 8px; }
.step .t { font-weight: 700; } .step .s { font-size: .88rem; color: var(--muted); }

[data-testid="stChatMessage"] { direction: rtl; background: white; border-radius: 14px;
        box-shadow: 0 1px 6px rgba(0,0,0,.05); }
[data-testid="stFileUploaderDropzone"] { border-radius: 14px; border: 2px dashed #B7D3CD; background: white; }
.result { background: white; border-radius: 14px; padding: 18px 22px; direction: rtl;
          border-right: 5px solid var(--teal); box-shadow: 0 2px 10px rgba(0,0,0,.05); }

/* budget */
.budget { direction: rtl; background: var(--card); border-radius: 16px; padding: 14px 16px; margin-bottom: 8px;
          box-shadow: 0 2px 10px rgba(0,0,0,.05); }
.budget .row { display: flex; justify-content: space-between; color: var(--muted); font-size: .9rem; }
.budget .row .t { font-weight: 700; color: var(--ink); font-size: 1rem; }
.budget .bar { height: 10px; background: #EEF2F1; border-radius: 99px; margin: 10px 0 8px; overflow: hidden; }
.budget .fill { height: 100%; border-radius: 99px; background: linear-gradient(90deg, #14B8A6, #0F766E); }
.budget.warn .fill { background: linear-gradient(90deg, #F59E0B, #B45309); }
.budget.over .fill { background: linear-gradient(90deg, #EF4444, #B91C1C); }
.budget .s { font-size: .92rem; color: var(--ink); } .budget.over .s { color: var(--red); font-weight: 600; }

/* insights */
.insights { display: grid; grid-template-columns: 1fr 1.4fr; gap: 10px; direction: rtl; }
.icard { background: var(--card); border-radius: 16px; padding: 14px 16px; box-shadow: 0 2px 10px rgba(0,0,0,.05); }
.icard .t { font-weight: 700; margin-bottom: 6px; } .icard .s { font-size: .85rem; color: var(--muted); }
.icard .big { font-size: 1.6rem; font-weight: 800; } .icard .big.up { color: var(--red); }
.icard .big.down { color: var(--green); }
.srow { display: flex; justify-content: space-between; font-size: .88rem; margin-top: 6px; }
.sbar { height: 6px; background: #EEF2F1; border-radius: 99px; overflow: hidden; }
.sbar > div { height: 100%; background: var(--teal-2); border-radius: 99px; }
[data-testid="stButtonGroup"] { direction: rtl; }
[data-testid="stPopover"] button, [data-testid="stPopoverButton"] { border-radius: 12px; }
[data-testid="stForm"] { background: white; border-radius: 16px; border: none;
        box-shadow: 0 2px 10px rgba(0,0,0,.05); direction: rtl; }

/* "an answer is on its way": three bouncing dots */
.thinking { direction: rtl; display: flex; align-items: center; gap: 5px; color: var(--teal); }
.thinking b { margin-right: 8px; font-weight: 600; }
.thinking span { width: 8px; height: 8px; border-radius: 50%; background: var(--teal-2);
                 animation: bounce 1s infinite ease-in-out; }
.thinking span:nth-child(2) { animation-delay: .15s; } .thinking span:nth-child(3) { animation-delay: .3s; }
@keyframes bounce { 0%, 80%, 100% { transform: scale(.5); opacity: .4; } 40% { transform: scale(1); opacity: 1; } }

/* the four actions on the add screen, as cards */
.st-key-actions [role="radiogroup"] { display: grid !important; grid-template-columns: 1fr 1fr; gap: 10px;
        direction: rtl; width: 100%; }
.st-key-actions [role="radiogroup"] > div { background: white; border-radius: 14px; padding: 12px 14px;
        box-shadow: 0 1px 6px rgba(0,0,0,.06); border: 2px solid transparent; cursor: pointer; }
.st-key-actions [role="radiogroup"] > div[data-selected="true"] { border-color: var(--teal); background: #F0FAF8; }
.st-key-actions [data-testid="stRadioOption"] p { font-weight: 700; font-size: 1rem; }
.st-key-actions [data-testid="stRadioCaption"] p { font-size: .85rem; }
.st-key-actions [data-testid="stWidgetLabel"] p { font-weight: 700; font-size: 1.05rem; }

@media (max-width: 640px) {        /* phone */
  .block-container { padding-left: .8rem; padding-right: .8rem; padding-top: .8rem; }
  .hero { padding: 14px 16px; border-radius: 16px; } .hero h1 { font-size: 1.2rem; } .hero .hi { font-size: .85rem; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  .stat .num { font-size: 1.4rem; }
  .steps, .insights { grid-template-columns: 1fr; }
  .st-key-nav button { padding: 7px 2px; }
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: .4rem !important; }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
      flex: 1 1 calc(50% - .4rem) !important; min-width: calc(50% - .4rem) !important; }
}
</style>
""", unsafe_allow_html=True)


def password_ok() -> bool:
    """When the site is online, APP_PASSWORD keeps strangers out (receipts are private)."""
    wanted = os.getenv("APP_PASSWORD", "")
    if not wanted or st.session_state.get("logged_in"):
        return True
    st.markdown('<div class="hero"><p class="hi">ברוכים הבאים</p><h1>🧾 הקבלות שלי</h1></div>',
                unsafe_allow_html=True)
    typed = st.text_input("סיסמה", type="password")
    if st.button("כניסה", type="primary"):
        if typed == wanted:
            st.session_state.logged_in = True
            st.rerun()
        st.error("הסיסמה לא נכונה.")
    return False


if not password_ok():
    st.stop()

try:
    now = datetime.now(ZoneInfo("Asia/Jerusalem"))
except Exception:            # a computer without time zone data: use its own clock
    now = datetime.now()
hello = ("בוקר טוב" if 5 <= now.hour < 12 else "צהריים טובים" if now.hour < 17
         else "ערב טוב" if now.hour < 22 else "לילה טוב")
st.markdown(f'<div class="hero"><p class="hi">{hello} 👋 · {now.day} ב{MONTHS[now.month - 1]}</p>'
            '<h1>🧾 הקבלות שלי</h1></div>', unsafe_allow_html=True)


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
    waiting = {"receipt": "קורא את הקבלה... (בדרך כלל כמה שניות)",
               "handwritten": "קורא את הרשימה... (בדרך כלל כמה שניות)",
               "statement": "בודק כל חיוב מול הקבלות והרשימות... (עד כחצי דקה)"}
    with st.spinner(waiting.get(inputs["input_kind"], "עובד על זה..."), show_time=True):
        t = time.time()
        try:
            st.session_state.out = graph.invoke(inputs, _cfg())
            st.session_state.took = time.time() - t
        except Exception as e:      # show a clear message instead of a long error
            st.session_state.out = None
            st.session_state.error = friendly(e)


def resume(value):
    st.session_state.error = ""
    with st.spinner("ממשיך...", show_time=True):
        try:
            st.session_state.out = graph.invoke(Command(resume=value), _cfg())
        except Exception as e:
            st.session_state.out = None
            st.session_state.error = friendly(e)


def _cfg():
    return {"configurable": {"thread_id": st.session_state.thread}}


def real_type(file) -> str | None:
    """The file's true type by its content (a renamed file is still caught):
    ".pdf", ".xlsx", ".png", ".jpg", ".csv", ".txt", or None if it is none of these."""
    kind = file_kind(file.getvalue())
    if kind == "text":
        return ".csv" if Path(file.name).suffix.lower() == ".csv" else ".txt"
    return f".{kind}" if kind else None


def save_upload(file) -> str | None:
    if file.size > MAX_FILE_BYTES:
        st.error("הקובץ גדול מ-10MB")
        return None
    path = UPLOADS / f"{uuid.uuid4().hex}{real_type(file)}"     # named by content, not by its name
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
        instant = quick_answer_now(question)
        if instant:                       # quick-question buttons: answered in code, at once
            st.markdown(instant)
            st.caption(f"⚡ {time.time() - started:.1f} שניות")
            st.session_state.chat.append((question, instant, ""))
            return
        # a moving sign until the first words arrive, so it is clear an answer is on its way
        wait = st.empty()
        wait.markdown('<div class="thinking"><span></span><span></span><span></span>'
                      '<b>מחפש תשובה בנתונים שלך...</b></div>', unsafe_allow_html=True)

        def words_after_wait():
            for i, chunk in enumerate(words()):
                if i == 0:
                    wait.empty()
                yield chunk

        try:
            st.write_stream(words_after_wait())
            wait.empty()
            answer = "".join(parts)
            took = f"{time.time() - started:.1f} שניות" + (f" · {model['name']}" if model["name"] else "")
            if took:
                st.caption(f"⏱️ {took}")
        except Exception as e:
            wait.empty()
            answer = friendly(e)
            st.error(answer)
            took = ""
    st.session_state.chat.append((question, answer, took))


def quick_answer_now(question: str) -> str | None:
    with db.connect() as c:
        return insights.quick_answer(question, db.list_receipts(c), db.list_all_manual_entries(c),
                                     date.today(), float(db.get_setting(c, "monthly_budget", "0") or 0))


# The question box is pinned to the bottom of every page. Enter sends.
question = (st.chat_input("💬 אפשר לשאול כל שאלה על הקניות")
            or st.session_state.pop("quick_q", None))     # or a quick-question button
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


def show_result(only: str | None = None):
    """Show the answer or the approval stop right under the button that started it."""
    kind = st.session_state.get("kind")
    if not kind or (only and kind != only):
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
                                   file_name=f"charges_to_check_{s['month']}.csv", mime="text/csv", on_click="ignore")
            else:
                st.success("כל החיובים מוכרים. אין מה לבדוק 🎉")
        else:
            if not out.get("answer"):
                st.error("לא הצלחתי לקרוא את הקובץ. כדאי לבדוק שזה הקובץ הנכון ולנסות שוב.")
                return
            with st.container(border=True):
                st.markdown(out.get("answer", "").replace("*", "\\*").replace("_", "\\_")
                            .replace("\n", "  \n"))


def esc(text) -> str:
    return html.escape(str(text or ""))


def nice_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def receipt_card(r: dict) -> str:
    """One receipt as a small card: what, where, when, how much, and the warranty."""
    badge = ""
    if r["warranty_until"]:
        left = days_left(r["warranty_until"])
        if left < 0:
            badge = '<span class="badge off">האחריות נגמרה</span>'
        elif left <= 60:
            badge = f'<span class="badge soon">⏰ אחריות עוד {left} ימים</span>'
        else:
            badge = f'<span class="badge ok">🛡️ אחריות עד {nice_date(r["warranty_until"])}</span>'
    title = r["product"] or r["merchant"]
    sub = (f'{esc(r["merchant"])} · ' if r["product"] else "") + nice_date(r["purchase_date"])
    return (f'<div class="rcard"><div><div class="title">{esc(title)}</div><div class="sub">{sub}</div></div>'
            f'<div class="side"><div class="amt">₪{r["total_amount"]:,.2f}</div>{badge}</div></div>')


def last_month(today: date) -> str:
    return (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


QUICK_QUESTIONS = ["כמה הוצאתי החודש?", "איזו אחריות נגמרת?", "איפה הוצאתי הכי הרבה?",
                   "מה קניתי השבוע?"]


def ask_quick(text: str):
    st.session_state.quick_q = text          # read by the question box at the top of the script


def show_budget(summary: dict, month_name: str):
    """The daily reason to open the site: how much is left, and how much per day."""
    if not summary.get("budget"):
        with st.popover("🎯 להגדיר תקציב חודשי", use_container_width=True):
            budget_form(0)
        return
    s = summary
    tone = "ok" if s["on_pace"] else "warn"
    if s["left"] < 0:
        tone, line = "over", f"חרגת מהתקציב ב-₪{-s['left']:,.0f}"
    else:
        line = (f"נשארו ₪{s['left']:,.0f} · אפשר להוציא <b>₪{s['per_day']:,.0f} ליום</b> "
                f"ב-{s['days_left']} הימים שנשארו")
    st.markdown(f'<div class="budget {tone}"><div class="row"><span class="t">🎯 תקציב {month_name}</span>'
                f'<span>₪{s["spent"]:,.0f} מתוך ₪{s["budget"]:,.0f}</span></div>'
                f'<div class="bar"><div class="fill" style="width:{s["used_pct"]}%"></div></div>'
                f'<div class="s">{line}</div></div>', unsafe_allow_html=True)
    with st.popover("⚙️ שינוי התקציב"):
        budget_form(s["budget"])


def budget_form(current: float):
    value = st.number_input("כמה מתכננים להוציא בחודש? (₪)", min_value=0.0, step=500.0,
                            value=float(current or 5000))
    if st.button("שמירת התקציב", type="primary"):
        with db.connect() as c:
            db.set_setting(c, "monthly_budget", str(value))
        st.session_state.toast = "התקציב נשמר ✅"
        st.rerun()


def show_insights(summary: dict, stores: list[tuple[str, float]]):
    """Two small cards: compared with last month, and where the money went."""
    change = summary["change"]
    if summary["last_month_same_days"] == 0:
        compare = '<div class="s">אין עדיין נתונים מהחודש שעבר להשוואה.</div>'
    else:
        arrow, tone, word = ("▲", "up", "יותר") if change > 0 else ("▼", "down", "פחות")
        compare = (f'<div class="big {tone}">{arrow} ₪{abs(change):,.0f}</div>'
                   f'<div class="s">{word} מאשר באותם ימים בחודש שעבר</div>')
    top = stores[0][1] if stores else 1
    bars = "".join(f'<div class="srow"><span>{esc(name)}</span><span>₪{amount:,.0f}</span></div>'
                   f'<div class="sbar"><div style="width:{amount / top * 100:.0f}%"></div></div>'
                   for name, amount in stores) or '<div class="s">עוד אין קניות החודש.</div>'
    st.markdown(f'<div class="insights"><div class="icard"><div class="t">לעומת החודש שעבר</div>{compare}</div>'
                f'<div class="icard"><div class="t">איפה הלך הכסף החודש</div>{bars}</div></div>',
                unsafe_allow_html=True)


def shortcuts():
    """Big buttons that open the add screen on the right action, so it is clear where to go."""
    cols = st.columns(4)
    for col, action in zip(cols, ["receipt", "statement", "handwritten", "manual"]):
        col.button(ACTIONS[action][0], on_click=go_add, args=(action,), use_container_width=True,
                   key=f"go_{action}", help=ACTIONS[action][1])


def show_home():
    """What matters right now: budget, things that need attention, insights, newest receipts."""
    today = date.today()
    with db.connect() as c:
        receipts = db.list_receipts(c)
        manual = db.list_all_manual_entries(c)
        soon = db.warranties_ending_between(c, today.isoformat(),
                                            (today + timedelta(days=60)).isoformat())
        charges = db.list_checked_charges(c)
        budget = float(db.get_setting(c, "monthly_budget", "0") or 0)

    if not receipts and not charges and not manual:          # first visit: show how it works
        st.markdown('<div class="sec">איך מתחילים?</div><div class="steps">'
                    '<div class="step"><div class="n">1</div><div class="t">כל קנייה, בשנייה</div>'
                    '<div class="s">מצלמים קבלה, מעלים רשימה, או מקלידים ידנית. בוחרים בכפתורים למטה.</div></div>'
                    '<div class="step"><div class="n">2</div><div class="t">תקציב חודשי</div>'
                    '<div class="s">רואים כל יום כמה נשאר וכמה אפשר להוציא היום.</div></div>'
                    '<div class="step"><div class="n">3</div><div class="t">אף חיוב לא מתפספס</div>'
                    '<div class="s">פעם בחודש מעלים את פירוט האשראי, ומקבלים תזכורת לפני שהאחריות נגמרת.</div></div>'
                    '</div>', unsafe_allow_html=True)
        st.markdown('<div class="sec">מה רוצים לעשות?</div>', unsafe_allow_html=True)
        shortcuts()
        with st.popover("🎯 להגדיר תקציב חודשי", use_container_width=True):
            budget_form(budget)
        return

    rows = insights.purchases(receipts, manual)
    summary = insights.month_summary(rows, today, budget)
    month_name = MONTHS[today.month - 1]
    active = [r for r in receipts if r["warranty_until"] and r["warranty_until"] >= today.isoformat()]
    unknown = [ch for ch in charges if ch["status"] == "unrecognized"]
    week = sum(1 for r in rows if r["date"] >= (today - timedelta(days=6)).isoformat())
    st.markdown(
        '<div class="stats">'
        f'<div class="stat"><div class="num">₪{summary["spent"]:,.0f}</div><div class="lbl">קניות ב{month_name}</div></div>'
        f'<div class="stat"><div class="num">{week}</div><div class="lbl">קניות נרשמו השבוע</div></div>'
        f'<div class="stat"><div class="num">{len(active)}</div><div class="lbl">אחריות בתוקף</div></div>'
        f'<div class="stat{" alert" if unknown else ""}"><div class="num">{len(unknown)}</div>'
        '<div class="lbl">חיובים לא מוכרים</div></div></div>', unsafe_allow_html=True)
    show_budget(summary, month_name)
    shortcuts()

    # things to do, most urgent first
    todo = []
    for ch in unknown[:5]:
        todo.append(("red", "❓", f"חיוב לא מוכר: {esc(ch['merchant'])} ₪{ch['amount']:,.2f}",
                     f"מ-{nice_date(ch['charge_date'])}. כדאי לבדוק מול חברת האשראי."))
    for r in soon:
        todo.append(("", "⏰", f"האחריות על {esc(r['product'] or r['merchant'])} נגמרת בעוד "
                     f"{days_left(r['warranty_until'])} ימים",
                     f"עד {nice_date(r['warranty_until'])}. אם יש תקלה, זה הזמן לפנות לתיקון."))
    prev = last_month(today)
    if not any(ch["month"] == prev for ch in charges):
        todo.append(("teal", "💳", f"עוד לא נבדק פירוט האשראי של {MONTHS[int(prev[5:]) - 1]}",
                     "לוחצים למעלה על 💳 בדיקת פירוט אשראי ומעלים את הקובץ מחברת האשראי."))
    if not any(r["date"] == today.isoformat() for r in rows):
        todo.append(("teal", "🛒", "קנית משהו היום?",
                     "לוחצים למעלה על 🧾 הוספת קבלה או ⌨️ הקלדה ידנית, וזה לוקח כמה שניות."))
    st.markdown('<div class="sec">מה דורש תשומת לב</div>', unsafe_allow_html=True)
    st.markdown("".join(f'<div class="todo {tone}"><div class="ic">{icon}</div><div>'
                        f'<div class="t">{title}</div><div class="s">{sub}</div></div></div>'
                        for tone, icon, title, sub in todo)
                or '<div class="allgood">✨ הכל מסודר. אין כרגע שום דבר שדורש טיפול.</div>',
                unsafe_allow_html=True)
    if active:
        st.download_button("📅 להוסיף ליומן תזכורות לסוף האחריות", warranty_calendar(receipts),
                           file_name="warranty_reminders.ics", mime="text/calendar", on_click="ignore",
                           help="פותחים את הקובץ בטלפון או במחשב, והיומן יזכיר חודש לפני שהאחריות נגמרת.")

    st.markdown('<div class="sec">תמונת מצב</div>', unsafe_allow_html=True)
    show_insights(summary, insights.top_stores(rows, today))

    st.markdown('<div class="sec">שאלה מהירה</div>', unsafe_allow_html=True)
    cols = st.columns(2)
    for i, q in enumerate(QUICK_QUESTIONS):
        cols[i % 2].button(q, on_click=ask_quick, args=(q,), use_container_width=True, key=f"quick_{q}")

    if receipts:
        st.markdown('<div class="sec">נוספו לאחרונה</div>', unsafe_allow_html=True)
        newest = sorted(receipts, key=lambda r: (r["purchase_date"], r["id"]), reverse=True)[:3]
        st.markdown("".join(receipt_card(r) for r in newest), unsafe_allow_html=True)


def show_manual_form():
    """Type a purchase by hand: no model, saved at once."""
    with st.form("manual_purchase", clear_on_submit=True):
        what = st.text_input("מה קנית? *", placeholder="למשל: נעליים לילדים")
        c1, c2 = st.columns(2)
        amount = c1.number_input("סכום (₪) *", min_value=0.0, step=10.0, format="%.2f")
        when = c2.date_input("תאריך", value=date.today(), format="DD/MM/YYYY")
        c3, c4 = st.columns(2)
        store = c3.text_input("איפה?", placeholder="שם החנות (לא חובה)")
        warranty = c4.number_input("אחריות (חודשים)", min_value=0, max_value=120, step=12)
        if not st.form_submit_button("💾 שמירת הקנייה", type="primary", use_container_width=True):
            return
    if not what.strip() or amount <= 0:
        st.error("צריך למלא מה נקנה ואת הסכום.")
        return
    merchant = store.strip() or what.strip()
    until = add_months(when, int(warranty)).isoformat() if warranty else None
    with db.connect() as c:
        if db.find_same_receipt(c, merchant, when.isoformat(), amount):
            st.warning("הקנייה הזאת כבר שמורה, ולכן לא שמרתי אותה שוב.")
            return
        db.add_receipt(c, merchant, when.isoformat(), float(amount), what.strip(), 1, until)
    st.session_state.toast = f"נשמר: {what.strip()} ₪{amount:,.2f} ✅"
    st.rerun()


# The four actions on the "add" screen: what each one is for, in plain words.
ACTIONS = {
    "receipt": ("🧾 הוספת קבלה",
                "צילום או קובץ של קבלה. אקרא חנות, תאריך, סכום ואחריות, ואשמור."),
    "statement": ("💳 בדיקת פירוט אשראי",
                  "מעלים את הקובץ מחברת האשראי. אבדוק כל חיוב מול הקבלות והרשימות, ואראה מה לא מוכר."),
    "handwritten": ("✍️ רשימת קניות",
                    "דף בכתב יד (תמונה) או קובץ Word של קניות בלי קבלה. אציג מה קראתי לאישור."),
    "manual": ("⌨️ הקלדה ידנית",
               "קנייה בלי קבלה ובלי קובץ: מקלידים מה, כמה ואיפה. נשמר מיד."),
}
# what each action accepts, and the type that belongs to another action
ACCEPTS = {"receipt": {".png", ".jpg", ".txt"}, "statement": STATEMENT_TYPES,
           "handwritten": {".png", ".jpg", ".docx"}}
HOW_IT_WORKS = {
    "receipt": "**מה יקרה:** אקרא את הקבלה ואשמור אותה. אם חסר פרט (סכום או תאריך), אשאל לפני השמירה. "
               "אפשר להעלות כמה קבלות יחד.",
    "statement": "**מה יקרה:** אקרא את כל החיובים ואבדוק שהסכום הכולל תואם. אחר כך אחפש לכל חיוב קבלה "
                 "או שורה ברשימת קניות. לפני שאסמן חיוב כחשוד, אשאל אותך. בסוף תקבלו דוח עם מה שכדאי לבדוק.",
    "handwritten": "**מה יקרה:** אקרא את השורות (מה נקנה וכמה), ואציג אותן לתיקון ואישור לפני השמירה. "
                   "בבדיקת פירוט האשראי, חיוב בלי קבלה יושווה גם לשורות האלה.",
}


def go_add(action: str):
    """Home-screen shortcut: open the add screen on a chosen action."""
    st.session_state.page = st.session_state.last_page = "➕ הוספה"
    st.session_state.action = action


@st.fragment      # a click here reloads only this screen, not the whole page
def show_add():
    """Four clear actions: add a receipt, check a statement, a shopping list, or type by hand.
    The file is still checked by its content, so a wrong file gets a clear message."""
    n = st.session_state.get("upload_n", 0)
    with st.container(key="actions"):
        action = st.radio("מה רוצים לעשות?", list(ACTIONS), key="action",
                          format_func=lambda a: ACTIONS[a][0],
                          captions=[ACTIONS[a][1] for a in ACTIONS])
    st.divider()
    if action == "manual":
        show_manual_form()
        return
    st.info(HOW_IT_WORKS[action])

    if action == "receipt" and st.toggle("📷 לצלם עכשיו במצלמה", key=f"cam{n}"):
        shot = st.camera_input("צילום הקבלה", key=f"shot{n}")
        files = [shot] if shot else []
    else:
        label = {"receipt": "קבלות (תמונה או טקסט, אפשר כמה יחד)",
                 "statement": "קובץ פירוט האשראי (PDF, Excel או CSV), כמו שמורידים מאתר חברת האשראי",
                 "handwritten": "צילום של דף קניות בכתב יד, או קובץ Word"}[action]
        # every box takes every supported type: a file put in the wrong box gets a clear
        # message that says where it belongs (checked by content, below)
        files = st.file_uploader(label, type=["png", "jpg", "jpeg", "txt", "docx", "pdf", "csv", "xlsx"],
                                 key=f"{action}{n}",
                                 accept_multiple_files=(action == "receipt"))
        files = files if isinstance(files, list) else [files] if files else []
    if not files:
        if action == "receipt":
            st.caption("💡 טיפ: הכי קל לצלם את הקבלה מיד בקופה, לפני שהיא הולכת לאיבוד.")
        show_result(action)
        return

    # the file's real type, by its content: a wrong file is stopped here, before any model
    for f in files:
        kind = real_type(f)
        if kind is None:
            st.error(f"הקובץ {f.name} לא נראה כמו קבלה, רשימת קניות או פירוט אשראי.")
            return
        if kind not in ACCEPTS[action]:
            right = next(a for a in ACCEPTS if kind in ACCEPTS[a])
            st.warning(f"הקובץ {f.name} נראה כמו {ACTIONS[right][0]}. "
                       f"כדאי לבחור למעלה \"{ACTIONS[right][0]}\" ולהעלות אותו שם.")
            return

    if action == "handwritten":
        month = st.text_input("לאיזה חודש שייכת הרשימה? (YYYY-MM)", value=date.today().strftime("%Y-%m"))
    label = {"statement": "🔎 לבדוק את הפירוט", "handwritten": "📖 לקרוא את הרשימה",
             "receipt": f"💾 לשמור {len(files)} קבלות" if len(files) > 1 else "💾 לשמור את הקבלה"}[action]
    if st.button(label, type="primary", use_container_width=True):
        if action == "receipt":
            st.session_state.queue = [p for p in map(save_upload, files) if p]
            st.session_state.receipt_log = []
            run_receipt_queue()
            if not st.session_state.get("queue") and st.session_state.receipt_log \
                    and not (st.session_state.out or {}).get("__interrupt__"):
                count = len(st.session_state.receipt_log)
                st.session_state.toast = "נשמרה קבלה ✅" if count == 1 else f"נשמרו {count} קבלות ✅"
        elif path := save_upload(files[0]):
            extra = {"month": month} if action == "handwritten" and month else {}
            start({"input_kind": action, "file_path": path, **extra})
        st.rerun()   # empties the upload box
    show_result(action)


@st.fragment      # a click here reloads only this tab, not the whole page
def show_all_receipts():
    """Every receipt as a card, with search. Fixing and deleting are in a separate edit mode."""
    today = date.today()
    with db.connect() as c:
        receipts = db.list_receipts(c)
    if not receipts:
        st.info("עוד אין קבלות. אפשר להוסיף במסך ➕ הוספה.")
        return
    c1, c2 = st.columns([3, 2])
    search = c1.text_input("חיפוש", placeholder="🔍 חיפוש לפי מוצר או חנות", label_visibility="collapsed")
    only_warranty = c2.toggle("רק עם אחריות בתוקף")
    editing = st.toggle("✏️ מצב עריכה (תיקון פרטים ומחיקה)")

    shown = [r for r in reversed(receipts)
             if search.strip().lower() in f"{r['merchant']} {r['product'] or ''}".lower()
             and (not only_warranty or (r["warranty_until"] or "") >= today.isoformat())]
    if not editing:
        total = sum(r["total_amount"] for r in shown)
        st.caption(f"{len(shown)} קבלות · סה\"כ ₪{total:,.2f}")
        st.markdown("".join(receipt_card(r) for r in shown) or "לא נמצאו קבלות.", unsafe_allow_html=True)
    else:
        edit_receipts(shown)

    d1, d2 = st.columns(2)
    d1.download_button("⬇️ גיבוי לאקסל", to_csv(
        [{"תאריך": r["purchase_date"], "בית עסק": r["merchant"], "מוצר": r["product"] or "",
          "סכום (₪)": r["total_amount"], "תשלומים": r["installments"], "אחריות עד": r["warranty_until"] or ""}
         for r in reversed(receipts)]), file_name=f"receipts_backup_{today:%Y_%m_%d}.csv",
        mime="text/csv", on_click="ignore", use_container_width=True)
    d2.download_button("📅 תזכורות ליומן", warranty_calendar(receipts),
                       file_name="warranty_reminders.ics", mime="text/calendar", on_click="ignore", use_container_width=True)


def edit_receipts(receipts: list[dict]):
    """The editable table: fix a detail that was read wrong, or mark receipts to delete."""
    if not receipts:
        st.caption("לא נמצאו קבלות.")
        return
    table = [{"מחיקה": False, "מס'": r["id"], "תאריך": r["purchase_date"], "בית עסק": r["merchant"],
              "מוצר": r["product"] or "", "סכום (₪)": r["total_amount"],
              "אחריות עד": r["warranty_until"] or ""} for r in receipts]
    edited = st.data_editor(table, hide_index=True, use_container_width=True, key="all_receipts",
                            disabled=["מס'"],
                            column_config={"מס'": None,
                                           "סכום (₪)": st.column_config.NumberColumn(format="%.2f", min_value=0)})
    changed = [row for row, old in zip(edited, table) if row != old and not row["מחיקה"]]
    marked = [row["מס'"] for row in edited if row["מחיקה"]]
    c1, c2 = st.columns(2)
    if changed and c1.button(f"💾 שמירת {len(changed)} תיקונים", type="primary"):
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
            st.session_state.toast = "התיקונים נשמרו ✅"
            st.rerun()
    if marked and c2.button(f"🗑️ מחיקת {len(marked)} קבלות"):
        with db.connect() as c:
            for rid in marked:
                db.delete_receipt(c, rid)
        st.session_state.toast = "נמחק ✅"
        st.rerun()


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


if st.session_state.get("toast"):
    st.toast(st.session_state.pop("toast"))

# Navigation: only the chosen page is built and drawn. (st.tabs draws all three pages at
# once, which made switching and uploading feel stuck on slower computers.)
PAGES = {"🏠 בית": show_home, "➕ הוספה": show_add, "🗂️ כל הקבלות": show_all_receipts}
st.session_state.setdefault("page", "🏠 בית")
with st.container(key="nav"):
    chosen = st.segmented_control("ניווט", list(PAGES), key="page",
                                  label_visibility="collapsed")
if chosen:                                   # clicking the current page again keeps it
    st.session_state.last_page = chosen
PAGES[st.session_state.get("last_page", "🏠 בית")]()

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
