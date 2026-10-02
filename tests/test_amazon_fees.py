"""Amazon fee math, checked against the worked examples on Amazon's own fee
pages (retrieved 2026-10-02)."""
import datetime as dt
from decimal import Decimal

import pytest

from sourcing.channels import amazon_fees as af
from sourcing.core import D


@pytest.fixture
def fees(settings):
    return settings.fee_data("amazon_fba")


@pytest.fixture
def ful(fees):
    return fees["fulfillment"]


def card(ful, name):
    return next(c for c in ful["rate_cards"] if c["name"] == name)


# (dims in, unit weight lb, price, tier, 2026 non-peak fee, 2026 peak fee): Amazon's examples
AMAZON_EXAMPLES = [
    pytest.param((13.8, 9, 0.7), "0.18", 5, "small_standard", "2.49", "2.68", id="mobile case"),
    pytest.param((12.6, 6.6, 5.5), "3.35", 20, "large_standard", "7.13", "7.67", id="iron"),
    pytest.param((24, 7.5, 6), "7.90", 60, "small_bulky", "10.21", "11.25", id="baby cot"),
    pytest.param((54, 35, 3.5), "41", 30, "extra_large_0_50", "44.19", "46.92", id="monitor"),
    pytest.param((65, 20, 7), "62", 60, "extra_large_50_70", "48.57", "51.38", id="tv"),
]


@pytest.mark.parametrize("dims,unit,price,tier,non_peak,peak", AMAZON_EXAMPLES)
def test_fulfillment_fee_matches_amazon_examples(ful, dims, unit, price, tier, non_peak, peak):
    size = af.classify(D(unit), *dims, ful)
    assert size.tier == tier
    band = af.price_band(price, ful)
    by_name = {c["name"]: c for c in ful["rate_cards"]}
    assert af.card_fee(card(ful, "2026 non-peak"), by_name, size.tier, size.fee_weight_lb, band) == D(non_peak)
    assert af.card_fee(card(ful, "2026 holiday peak"), by_name, size.tier, size.fee_weight_lb, band) == D(peak)


@pytest.mark.parametrize("dims,unit,expected", [
    ((12.6, 6.6, 5.5), "3.35", "3.29"),    # iron
    ((24, 7.5, 6), "7.90", "7.77"),        # baby cot
    ((54, 35, 3.5), "41", "47.59"),        # monitor
    ((65, 20, 7), "62", "65.47"),          # tv
])
def test_dimensional_weight_matches_amazon_examples(ful, dims, unit, expected):
    size = af.classify(D(unit), *dims, ful)
    assert round(size.dim_weight_lb, 2) == D(expected)


def test_small_standard_uses_unit_weight_for_fees(ful):
    size = af.classify(D("0.18"), 13.8, 9, 0.7, ful)
    assert size.fee_weight_lb == D("0.18")
    assert size.dim_weight_lb > size.fee_weight_lb


def test_thicker_than_three_quarters_inch_is_large_standard(ful):
    assert af.classify(D("0.5"), 10, 8, 0.8, ful).tier == "large_standard"


@pytest.mark.parametrize("price,band", [("9.99", 0), ("10.00", 1), ("50.00", 1), ("50.01", 2)])
def test_price_band_edges(ful, price, band):
    assert af.price_band(price, ful) == band


@pytest.mark.parametrize("category,price,expected", [
    ("Toys and Games", "29.99", "4.50"),
    ("Toys and Games", "1.00", "0.30"),                       # per-item minimum
    ("Beauty, Health and Personal Care", "10.00", "0.80"),    # 8% at or under $10
    ("Beauty, Health and Personal Care", "10.01", "1.50"),    # 15% on the whole price above $10
    ("Electronics Accessories", "150.00", "19.00"),           # 15% of $100 + 8% of $50
    ("Clothing and Accessories", "18.00", "1.80"),            # 10% tier
    ("Grocery and Gourmet", "2.00", "0.16"),                  # no minimum
    ("Watches", "8.00", "1.28"),                              # Amazon's watch examples
    ("Watches", "1500.00", "240.00"),
    ("Watches", "7000.00", "405.00"),
])
def test_referral_fee(fees, category, price, expected):
    name = af.find_category(fees["referral"]["categories"], category)
    assert af.referral_fee(fees["referral"]["categories"][name], price) == D(expected)


def test_category_lookup_ignores_case(fees):
    assert af.find_category(fees["referral"]["categories"], "toys and games") == "Toys and Games"


def _test_size(ful):
    return af.classify(D("0.9"), 8, 6, 3, ful)   # large standard, 1.04 lb dimensional


def test_window_overlapping_peak_uses_peak_rate_plus_surcharge(ful):
    fee, detail = af.fulfillment_fee(ful, "Toys and Games", _test_size(ful), "29.99",
                                     dt.date(2026, 10, 2), dt.date(2026, 12, 31))
    assert fee == D("5.53")              # $5.34 peak x 1.035
    assert "holiday peak" in detail


def test_window_before_surcharge_uses_plain_non_peak_rate(ful):
    fee, _ = af.fulfillment_fee(ful, "Toys and Games", _test_size(ful), "29.99",
                                dt.date(2026, 1, 20), dt.date(2026, 4, 1))
    assert fee == D("5.04")


def test_window_reaching_surcharge_date_adds_it(ful):
    fee, _ = af.fulfillment_fee(ful, "Toys and Games", _test_size(ful), "29.99",
                                dt.date(2026, 2, 1), dt.date(2026, 5, 2))
    assert fee == D("5.22")              # $5.04 x 1.035


def test_window_past_published_rates_is_unverified(ful):
    fee, detail = af.fulfillment_fee(ful, "Toys and Games", _test_size(ful), "29.99",
                                     dt.date(2026, 12, 1), dt.date(2027, 3, 1))
    assert fee is None
    assert "re-verify" in detail


def test_apparel_uses_apparel_rates(ful):
    fee, detail = af.fulfillment_fee(ful, "Clothing and Accessories", _test_size(ful), "29.99",
                                     dt.date(2026, 10, 2), dt.date(2026, 12, 31))
    assert fee == D("6.46")              # $6.24 apparel peak x 1.035
    assert "apparel" in detail


def test_storage_uses_q4_rate_when_window_touches_q4(fees, ful):
    size = _test_size(ful)
    q4, _ = af.storage_fee(fees["storage"], size, dt.date(2026, 10, 2), dt.date(2026, 12, 31), 1)
    spring, _ = af.storage_fee(fees["storage"], size, dt.date(2026, 2, 1), dt.date(2026, 5, 1), 1)
    assert q4 == D("0.20")               # 144 cu in / 1728 x $2.40
    assert spring == D("0.07")           # 144 cu in / 1728 x $0.78 = $0.065, rounded half up


def test_placement_fee_charges_top_of_range(fees, ful):
    placement = fees["inbound_placement"]
    large = _test_size(ful)
    small = af.classify(D("0.375"), 10, 8, 0.5, ful)          # 6 oz small standard
    tv = af.classify(D("62"), 65, 20, 7, ful)
    assert af.placement_fee(placement, "minimal_splits", large, "high")[0] == D("0.50")
    assert af.placement_fee(placement, "minimal_splits", small, "high")[0] == D("0.32")
    assert af.placement_fee(placement, "minimal_splits", tv, "high")[0] == Decimal(0)
