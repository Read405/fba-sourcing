"""SQLite history. Nothing is ever deleted: triggers block DELETE on every
table, and records are retired by setting active = 0."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from .core import D, cents

TABLES = ("evaluations", "brands", "brand_events", "ledger")
BRAND_STATUSES = ("open", "ungated", "gated")

SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    id           INTEGER PRIMARY KEY,
    created_at   TEXT NOT NULL,            -- ISO-8601 UTC
    eval_date    TEXT NOT NULL,            -- YYYY-MM-DD
    source_type  TEXT NOT NULL,
    store        TEXT NOT NULL,
    channel      TEXT NOT NULL,
    asin         TEXT,
    title        TEXT,
    brand        TEXT,
    fee_category TEXT,
    verdict      TEXT NOT NULL,
    failed_gate  TEXT,
    reason       TEXT,
    input_json   TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS brands (
    name_key     TEXT PRIMARY KEY,         -- lower-case brand name
    name         TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('open', 'ungated', 'gated')),
    complaints   INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    source       TEXT,
    updated_at   TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS brand_events (
    id           INTEGER PRIMARY KEY,
    name_key     TEXT NOT NULL,
    status       TEXT NOT NULL,
    complaints   INTEGER NOT NULL,
    note         TEXT,
    source       TEXT,
    recorded_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    id           INTEGER PRIMARY KEY,
    created_at   TEXT NOT NULL,
    entry_date   TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('capital_in', 'purchase', 'payout', 'expense', 'adjustment')),
    amount       TEXT NOT NULL,            -- decimal string; positive adds capital, negative spends it
    ref          TEXT,
    note         TEXT,
    active       INTEGER NOT NULL DEFAULT 1
);
"""


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table in TABLES:
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS keep_{table} BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'history is permanent: set active = 0 instead of deleting'); END;")
    conn.commit()
    return conn


def get_brand(conn: sqlite3.Connection, name: str | None) -> dict | None:
    if not name:
        return None
    row = conn.execute("SELECT * FROM brands WHERE name_key = ? AND active = 1",
                       (str(name).strip().lower(),)).fetchone()
    return dict(row) if row else None


def set_brand(conn: sqlite3.Connection, name: str, status: str, complaints: bool | None = None,
              note: str | None = None, source: str = "user") -> dict:
    if status not in BRAND_STATUSES:
        raise ValueError(f"status must be one of {', '.join(BRAND_STATUSES)}")
    key = name.strip().lower()
    existing = get_brand(conn, name)
    flag = int(complaints) if complaints is not None else int(existing["complaints"]) if existing else 0
    stamp = now_utc()
    conn.execute(
        "INSERT INTO brands (name_key, name, status, complaints, note, source, updated_at, active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1) "
        "ON CONFLICT(name_key) DO UPDATE SET name = excluded.name, status = excluded.status, "
        "complaints = excluded.complaints, note = excluded.note, source = excluded.source, "
        "updated_at = excluded.updated_at, active = 1",
        (key, name.strip(), status, flag, note, source, stamp))
    conn.execute(
        "INSERT INTO brand_events (name_key, status, complaints, note, source, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
        (key, status, flag, note, source, stamp))
    conn.commit()
    return get_brand(conn, name)


def save_evaluation(conn: sqlite3.Connection, ev, record: dict) -> int:
    c = ev.candidate
    cur = conn.execute(
        "INSERT INTO evaluations (created_at, eval_date, source_type, store, channel, asin, title, brand, "
        "fee_category, verdict, failed_gate, reason, input_json, result_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now_utc(), str(ev.eval_date), c.source_type, c.store, c.channel, c.value("asin"), c.value("title"),
         c.value("brand"), c.value("fee_category"), ev.verdict, ev.failed_gate, ev.reason,
         json.dumps(c.raw, default=str), json.dumps(record, default=str)))
    conn.commit()
    return int(cur.lastrowid)


def add_ledger(conn: sqlite3.Connection, entry_date: str, kind: str, amount, ref: str | None = None,
               note: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO ledger (created_at, entry_date, kind, amount, ref, note) VALUES (?, ?, ?, ?, ?, ?)",
        (now_utc(), entry_date, kind, str(cents(amount)), ref, note))
    conn.commit()
    return int(cur.lastrowid)


def capital(conn: sqlite3.Connection, settings) -> dict:
    """Available capital = starting total - reserved costs + every active ledger entry."""
    ledger_net = sum((D(r["amount"]) for r in conn.execute("SELECT amount FROM ledger WHERE active = 1")),
                     Decimal("0"))
    starting = D(settings.config["capital"]["starting_total"])
    reserved = settings.reserved_total
    return {"starting": starting, "reserved": reserved, "ledger_net": ledger_net,
            "available": cents(starting - reserved + ledger_net)}


def brand_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM brands WHERE active = 1").fetchone()[0]
