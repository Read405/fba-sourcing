"""Verdict rules and the data rule: no BUY without every required field
verified, and a number without a source is never verified."""
import datetime as dt

import pytest
from conftest import GOOD_FIELDS, make_candidate, run

from sourcing.core import BUY, CHECK_MANUALLY, FAIL, PASS, SOFT_FAIL, UNVERIFIED, WATCH, GateResult, REJECT
from sourcing.evaluator import decide
from sourcing import db
from sourcing.session import fee_freshness


def gate(number, *statuses):
    g = GateResult(number, f"gate {number}")
    for i, s in enumerate(statuses):
        g.add(f"check {i}", s, "detail")
    return g


def test_decide_order():
    assert decide([gate(1, PASS), gate(2, PASS)])[0] == BUY
    assert decide([gate(1, PASS, UNVERIFIED)])[0] == CHECK_MANUALLY
    assert decide([gate(1, UNVERIFIED), gate(3, SOFT_FAIL)])[0] == WATCH
    assert decide([gate(1, PASS), gate(3, SOFT_FAIL), gate(4, FAIL)])[:2] == (REJECT, "4")


@pytest.mark.parametrize("name", sorted(set(GOOD_FIELDS) - {"title", "asin"}))
def test_every_required_field_blocks_buy_when_unverified(rated, name):
    ev = run(rated, make_candidate({name: {"unverified": True, "note": "test"}}))
    assert ev.verdict != BUY, name


def test_value_without_source_is_unverified(rated):
    ev = run(rated, make_candidate({"sales_rank": {"value": 5000}}))
    assert ev.verdict == CHECK_MANUALLY


def test_value_with_bad_date_is_unverified(rated):
    ev = run(rated, make_candidate({"sales_rank": {"value": 5000, "source": "x", "retrieved": "Oct 2"}}))
    assert ev.verdict == CHECK_MANUALLY


def test_fee_data_reverify_triggers(settings):
    assert fee_freshness(settings, "amazon_fba", dt.date(2026, 10, 10))[2] == []
    reasons = fee_freshness(settings, "amazon_fba", dt.date(2026, 11, 5))[2]
    assert any("days old" in r for r in reasons)
    assert any("holiday peak" in r for r in reasons)
    assert any("new year" in r for r in fee_freshness(settings, "amazon_fba", dt.date(2027, 1, 2))[2])


def test_sell_window_past_published_fees_blocks_buy(rated):
    ev = run(rated, make_candidate(), today=dt.date(2026, 12, 1))
    assert ev.verdict == CHECK_MANUALLY
    assert any("FBA fulfillment fee" in item or "Profit" in item for item in ev.to_confirm)
