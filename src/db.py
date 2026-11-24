"""Local SQLite storage for receipts and handwritten shopping-list entries.

Security rule (see section 5ב of the prompt): every query uses "?" parameters.
Text is never pasted into an SQL string, and the model never writes SQL.
"""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "receipts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant        TEXT    NOT NULL,
    purchase_date   TEXT    NOT NULL,          -- YYYY-MM-DD
    total_amount    REAL    NOT NULL,          -- shekels
    product         TEXT,
    installments    INTEGER NOT NULL DEFAULT 1,
    warranty_until  TEXT                       -- YYYY-MM-DD or NULL
);

CREATE TABLE IF NOT EXISTS manual_entries (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    month            TEXT    NOT NULL,         -- YYYY-MM
    description      TEXT    NOT NULL,
    estimated_amount REAL    NOT NULL,
    merchant         TEXT,
    source_page      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS checked_charges (
    charge_id    TEXT NOT NULL,
    month        TEXT NOT NULL,                -- YYYY-MM
    charge_date  TEXT NOT NULL,
    merchant     TEXT NOT NULL,
    amount       REAL NOT NULL,
    installment  TEXT,
    status       TEXT NOT NULL,                -- matched_receipt / matched_manual / ...
    reason       TEXT,
    PRIMARY KEY (month, charge_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,                    -- for example "monthly_budget"
    value TEXT NOT NULL
);
"""


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the database, create the tables if needed, and return rows as dicts."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_receipt(conn, merchant, purchase_date, total_amount,
                product=None, installments=1, warranty_until=None) -> int:
    """Save one receipt and return its new id."""
    cur = conn.execute(
        "INSERT INTO receipts (merchant, purchase_date, total_amount, product, "
        "installments, warranty_until) VALUES (?, ?, ?, ?, ?, ?)",
        (merchant, purchase_date, total_amount, product, installments, warranty_until),
    )
    conn.commit()
    return cur.lastrowid


def add_manual_entry(conn, month, description, estimated_amount,
                     source_page, merchant=None) -> int:
    """Save one line from a handwritten page and return its new id."""
    cur = conn.execute(
        "INSERT INTO manual_entries (month, description, estimated_amount, "
        "merchant, source_page) VALUES (?, ?, ?, ?, ?)",
        (month, description, estimated_amount, merchant, source_page),
    )
    conn.commit()
    return cur.lastrowid


def list_receipts(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM receipts ORDER BY purchase_date")]


def list_manual_entries(conn, month: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM manual_entries WHERE month = ? ORDER BY source_page, id", (month,)
    )
    return [dict(r) for r in rows]


def warranties_ending_between(conn, start: str, end: str) -> list[dict]:
    """Receipts whose warranty ends between two dates (YYYY-MM-DD, inclusive)."""
    rows = conn.execute(
        "SELECT * FROM receipts WHERE warranty_until BETWEEN ? AND ? ORDER BY warranty_until",
        (start, end),
    )
    return [dict(r) for r in rows]


def find_warranty_for_product(conn, product: str) -> list[dict]:
    """Receipts whose product name contains the given text."""
    rows = conn.execute(
        "SELECT * FROM receipts WHERE product LIKE ? ORDER BY purchase_date DESC",
        (f"%{product}%",),
    )
    return [dict(r) for r in rows]


def spent_at_merchant(conn, merchant: str, month: str | None = None) -> list[dict]:
    """Receipts from a store (name contains the text), optionally in one month (YYYY-MM)."""
    sql = "SELECT * FROM receipts WHERE merchant LIKE ?"
    params: list = [f"%{merchant}%"]
    if month:
        sql += " AND substr(purchase_date, 1, 7) = ?"
        params.append(month)
    return [dict(r) for r in conn.execute(sql + " ORDER BY purchase_date", params)]


def next_page_number(conn, month: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(source_page), 0) + 1 FROM manual_entries WHERE month = ?", (month,)
    ).fetchone()
    return row[0]


def save_checked_charges(conn, charges: list[dict], results: dict) -> None:
    """Keep the result of a statement check, so questions can be asked about it later."""
    for c in charges:
        r = results[c["charge_id"]]
        conn.execute(
            "INSERT OR REPLACE INTO checked_charges (charge_id, month, charge_date, merchant, "
            "amount, installment, status, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (c["charge_id"], c["charge_date"][:7], c["charge_date"], c["merchant"], c["amount"],
             c.get("installment", ""), r["status"], r.get("reason")),
        )
    conn.commit()


def list_checked_charges(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM checked_charges ORDER BY charge_date")]


def delete_receipt(conn, receipt_id: int) -> None:
    """Remove a receipt that was saved by mistake."""
    conn.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
    conn.commit()


def find_same_receipt(conn, merchant: str, purchase_date: str, total_amount: float) -> dict | None:
    """A receipt already saved with the same store, date and amount (uploaded twice)."""
    row = conn.execute(
        "SELECT * FROM receipts WHERE merchant = ? AND purchase_date = ? "
        "AND ABS(total_amount - ?) < 0.01", (merchant, purchase_date, total_amount)).fetchone()
    return dict(row) if row else None


def update_receipt(conn, receipt_id: int, merchant: str, purchase_date: str, total_amount: float,
                   product: str | None, warranty_until: str | None) -> None:
    """Fix a receipt the model read wrong (edited in the overview table)."""
    conn.execute(
        "UPDATE receipts SET merchant = ?, purchase_date = ?, total_amount = ?, product = ?, "
        "warranty_until = ? WHERE id = ?",
        (merchant, purchase_date, total_amount, product, warranty_until, receipt_id))
    conn.commit()


def get_setting(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def list_all_manual_entries(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM manual_entries ORDER BY month, id")]
