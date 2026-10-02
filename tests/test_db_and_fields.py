"""Field parsing and the permanent SQLite history."""
import sqlite3
from decimal import Decimal

import pytest
from conftest import make_candidate, run

from sourcing import db
from sourcing.core import parse_field
from sourcing.report import format_evaluation, to_record


def test_parse_field_verified():
    f = parse_field("price", {"value": 9.99, "source": "user: tag", "retrieved": "2026-10-02"})
    assert f.verified and f.value == 9.99


def test_parse_field_false_is_a_real_value():
    assert parse_field("fragile", {"value": False, "source": "user", "retrieved": "2026-10-02"}).verified


@pytest.mark.parametrize("raw,note", [
    (None, "not provided"),
    (9.99, "no source"),
    ({"value": 9.99}, "missing source, retrieved"),
    ({"value": 9.99, "source": "x", "retrieved": "10/02/2026"}, "not YYYY-MM-DD"),
    ({"unverified": True, "note": "couldn't find it"}, "couldn't find it"),
])
def test_parse_field_unverified(raw, note):
    f = parse_field("price", raw)
    assert not f.verified and note in f.note


@pytest.fixture
def conn():
    return db.connect(":memory:")


@pytest.mark.parametrize("table", db.TABLES)
def test_deletes_are_blocked(conn, rated, table):
    # Triggers fire per row, so put a row in every table first.
    db.set_brand(conn, "TestBrand", "open")
    db.add_ledger(conn, "2026-10-03", "purchase", "-1.00")
    ev = run(rated, make_candidate())
    db.save_evaluation(conn, ev, to_record(ev))
    with pytest.raises(sqlite3.DatabaseError, match="history is permanent"):
        conn.execute(f"DELETE FROM {table}")
    assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1


def test_brand_memory_keeps_history(conn):
    db.set_brand(conn, "TestBrand", "gated", note="needs invoices")
    row = db.set_brand(conn, "testbrand", "ungated", note="approved")
    assert row["status"] == "ungated" and row["complaints"] == 0
    assert db.get_brand(conn, "TESTBRAND")["status"] == "ungated"
    events = conn.execute("SELECT status FROM brand_events ORDER BY id").fetchall()
    assert [e["status"] for e in events] == ["gated", "ungated"]


def test_brand_status_must_be_known(conn):
    with pytest.raises(ValueError):
        db.set_brand(conn, "TestBrand", "maybe")


def test_evaluation_snapshot_is_saved(conn, rated):
    ev = run(rated, make_candidate())
    eid = db.save_evaluation(conn, ev, to_record(ev))
    row = conn.execute("SELECT * FROM evaluations WHERE id = ?", (eid,)).fetchone()
    assert row["verdict"] == "BUY" and row["asin"] == "B0TEST0001" and row["eval_date"] == "2026-10-02"


def test_capital_comes_from_the_ledger(conn, settings):
    assert db.capital(conn, settings)["available"] == Decimal("420.01")
    db.add_ledger(conn, "2026-10-03", "purchase", "-54.40", note="5 x test puzzle")
    assert db.capital(conn, settings)["available"] == Decimal("365.61")


def test_report_renders_every_verdict(rated, settings):
    for cand, s in ((make_candidate(), rated), (make_candidate({"purchase_price": 16}), rated),
                    (make_candidate({"amazon_on_listing": True}), rated), (make_candidate(), settings)):
        text = format_evaluation(run(s, cand))
        assert text.startswith("VERDICT: ")
