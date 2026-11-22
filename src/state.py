"""The state that flows through the LangGraph graph."""

from typing import Literal, TypedDict

InputKind = Literal["receipt", "statement", "handwritten", "question"]
ChargeStatus = Literal["matched_receipt", "matched_manual", "amount_mismatch", "unrecognized"]


class ChargeResult(TypedDict, total=False):
    charge_id: str
    status: ChargeStatus
    matched_id: int | None
    expected_amount: float | None
    reason: str
    suspicious: bool               # unrecognized and not approved by the user


class AgentState(TypedDict, total=False):
    # input
    input_kind: InputKind          # set by the UI, or decided by the router node
    file_path: str                 # uploaded file, if any
    question: str                  # user question, if any
    recent: str                    # what the website showed just before the question
    recent_chat: list              # last questions and answers, for short follow-ups
    month: str                     # YYYY-MM, for handwritten pages

    # receipt flow
    receipt: dict                  # fields read from the receipt

    # handwritten flow
    lines: list[dict]              # lines read from the page
    duplicates: list[dict]         # lines that look like ones already saved

    # statement flow
    charges: list[dict]            # rows read from the statement
    stated_total: float | None     # total printed on the statement
    results: dict[str, ChargeResult]  # charge_id -> result
    pending: list[str]             # charge ids still without a match
    used_receipts: list[int]       # receipts already matched (catches double charges)
    retry_count: int               # loose-matching attempts so far (max 2)

    # question flow
    context: dict                  # everything saved, given to the model to answer

    # output
    answer: str                    # final text shown to the user
    summary: dict                  # statement report: counts and totals (for the website)
    exceptions_table: list[dict]   # statement report: charges to look at (for the website)
