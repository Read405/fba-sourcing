"""Shared fixtures. GOOD_FIELDS is a made-up, fully verified candidate that
earns a BUY once a carrier rate is set and its brand is open. The numbers it
produces are worked by hand in test_profit.py."""
from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal

import pytest

from sourcing.config import ROOT, load
from sourcing.core import Candidate, EvalContext
from sourcing.evaluator import evaluate

TODAY = dt.date(2026, 10, 2)
SRC = "https://example.test/listing"


def f(value, source=SRC, retrieved="2026-10-02", **extra) -> dict:
    return {"value": value, "source": source, "retrieved": retrieved, **extra}


GOOD_FIELDS = {
    "purchase_price": f(10.00, source="user: shelf tag"),
    "asin": f("B0TEST0001"),
    "title": f("Test Puzzle"),
    "brand": f("TestBrand"),
    "fee_category": f("Toys and Games"),
    "rank_category": f("Toys & Games"),
    "sales_rank": f(5000),
    "category_size": f(1_000_000),
    "seasonality": f({"label": "YEAR-ROUND"}),
    "current_price": f(29.99),
    "avg_price_90d": f(31.50),
    "unit_weight_lb": f(0.9),
    "length_in": f(8),
    "width_in": f(6),
    "height_in": f(3),
    "is_hazmat": f(False),
    "has_expiry": f(False),
    "amazon_on_listing": f(False),
    "brand_owner_only_seller": f(False),
    "fba_offers_near_buybox": f(6),
    "exact_match": f({"upc": True, "model": True, "size": True, "color": "n/a",
                      "edition": "n/a", "pack_count": True}),
    "fragile": f(False),
}


def make_candidate(overrides: dict | None = None, drop: tuple = (), **top) -> Candidate:
    """GOOD_FIELDS with overrides. A plain override value is wrapped as a
    verified field; a dict with 'value' or 'unverified' is used as-is."""
    data = {"source_type": "retail_store", "store": "Test Store", "channel": "amazon_fba",
            "condition": "new", "fields": copy.deepcopy(GOOD_FIELDS)}
    data.update(top)
    for name in drop:
        data["fields"].pop(name, None)
    for name, value in (overrides or {}).items():
        raw = isinstance(value, dict) and ({"value", "unverified"} & value.keys())
        data["fields"][name] = value if raw else f(value)
    return Candidate.from_dict(data)


def run(settings, cand: Candidate, brand_status: str | None = "open", today: dt.date = TODAY,
        capital: Decimal | None = Decimal("420.01"), complaints: bool = False):
    brand = None if brand_status is None else {
        "name": "TestBrand", "status": brand_status, "complaints": int(complaints),
        "updated_at": "2026-10-01T00:00:00+00:00"}
    return evaluate(cand, EvalContext(settings, today, brand=brand, capital_available=capital))


def checks_named(ev, gate: int, name: str):
    return [c for c in ev.gate(gate).checks if c.name == name]


@pytest.fixture
def settings():
    """Real config and fee data, with no carrier rate (as on day one)."""
    return load(ROOT)


@pytest.fixture
def rated(settings):
    """Real config plus a test carrier rate of $0.50/lb, so BUY is reachable."""
    settings.config["unverified_costs"]["inbound_shipping_per_lb"].update(
        value=0.50, source="test fixture", retrieved="2026-10-02")
    return settings
