"""Each gate's pass, fail and UNVERIFIED paths."""
import pytest
from conftest import checks_named, make_candidate, run

from sourcing.core import BUY, CHECK_MANUALLY, FLAG, REJECT, UNVERIFIED
from sourcing.sources import SourceNotAvailable


# --- Gate 1: can I sell it? ---------------------------------------------

def test_gated_brand_rejects_at_gate_1(rated):
    ev = run(rated, make_candidate(), brand_status="gated")
    assert ev.verdict == REJECT and ev.failed_gate == "1"
    assert len(ev.gates) == 1


def test_unchecked_brand_is_check_manually(rated):
    ev = run(rated, make_candidate(), brand_status=None)
    assert ev.verdict == CHECK_MANUALLY
    assert checks_named(ev, 1, "Brand eligibility")[0].status == UNVERIFIED


def test_likely_gated_hint_is_shown(rated):
    ev = run(rated, make_candidate({"likely_gated": True}), brand_status=None)
    assert "LIKELY GATED" in checks_named(ev, 1, "Brand eligibility")[0].detail


def test_hazmat_rejects(rated):
    ev = run(rated, make_candidate({"is_hazmat": True}))
    assert ev.verdict == REJECT and ev.failed_gate == "1"


@pytest.mark.parametrize("months,verdict", [(4, REJECT), (6, BUY), (8, BUY)])
def test_expiry_minimum(rated, months, verdict):
    ev = run(rated, make_candidate({"has_expiry": True, "months_to_expiry": months}))
    assert ev.verdict == verdict


def test_expiry_without_months_is_check_manually(rated):
    assert run(rated, make_candidate({"has_expiry": True})).verdict == CHECK_MANUALLY


@pytest.mark.parametrize("days,verdict", [(5, BUY), (7, REJECT)])
def test_online_delivery_limit(rated, days, verdict):
    cand = make_candidate({"shipping_total": 0, "units_in_order": 3, "delivery_days": days},
                          source_type="retail_online")
    assert run(rated, cand).verdict == verdict


def test_complaint_brand_is_flagged_not_rejected(rated):
    ev = run(rated, make_candidate(), complaints=True)
    assert ev.verdict == BUY
    assert checks_named(ev, 1, "Authenticity risk")[0].status == FLAG


# --- Gate 2: will it sell? -------------------------------------------------

def test_rank_outside_percentile_rejects_and_stops(rated):
    ev = run(rated, make_candidate({"sales_rank": 30_000}))     # 3% of 1,000,000
    assert ev.verdict == REJECT and ev.failed_gate == "2"
    assert len(ev.gates) == 2


def test_missing_category_size_is_check_manually(rated):
    ev = run(rated, make_candidate(drop=("category_size",)))
    assert ev.verdict == CHECK_MANUALLY
    assert "category_size" in checks_named(ev, 2, "Sales rank")[0].detail


def test_seasonal_is_labelled_and_flagged(rated):
    season = {"label": "SEASONAL", "season": "Christmas", "demand_drops": "2026-12-26"}
    ev = run(rated, make_candidate({"seasonality": season}))
    check = checks_named(ev, 2, "Seasonality")[0]
    assert ev.verdict == BUY and check.status == FLAG
    assert "Christmas" in check.detail and "85 days" in check.detail


def test_seasonal_without_drop_date_is_check_manually(rated):
    ev = run(rated, make_candidate({"seasonality": {"label": "SEASONAL", "season": "Halloween"}}))
    assert ev.verdict == CHECK_MANUALLY


# --- Gate 3: will I make money? ------------------------------------------

@pytest.mark.parametrize("overrides", [
    {"current_price": 14.99, "avg_price_90d": 14.99},            # under the price range
    {"current_price": 52.00, "avg_price_90d": 52.00},            # over the price range
    {"unit_weight_lb": 2.5},                                     # over max weight
    {"length_in": 20, "width_in": 10, "height_in": 10, "unit_weight_lb": 1.5},  # oversize
])
def test_gate_3_limits_reject(rated, overrides):
    ev = run(rated, make_candidate(overrides))
    assert ev.verdict == REJECT and ev.failed_gate == "3"


# --- Gate 4: what can go wrong? -------------------------------------------

@pytest.mark.parametrize("overrides", [
    {"amazon_on_listing": True},
    {"brand_owner_only_seller": True},
    {"fba_offers_near_buybox": 21},
    {"exact_match": {"upc": True, "model": True, "size": True, "color": "n/a",
                     "edition": "n/a", "pack_count": False}},
])
def test_gate_4_risks_reject(rated, overrides):
    ev = run(rated, make_candidate(overrides))
    assert ev.verdict == REJECT and ev.failed_gate == "4"


def test_offer_count_at_limit_passes(rated):
    assert run(rated, make_candidate({"fba_offers_near_buybox": 20})).verdict == BUY


def test_uncompared_attribute_is_check_manually(rated):
    ev = run(rated, make_candidate({"exact_match": {"model": True, "size": True, "color": "n/a",
                                                    "edition": "n/a", "pack_count": True}}))
    assert ev.verdict == CHECK_MANUALLY
    assert "upc" in checks_named(ev, 4, "Exact match")[0].detail


def test_exact_match_states_what_was_compared(rated):
    detail = checks_named(run(rated, make_candidate()), 4, "Exact match")[0].detail
    assert "upc" in detail and "pack_count" in detail and "not applicable: color, edition" in detail


def test_fragile_is_flagged(rated):
    ev = run(rated, make_candidate({"fragile": True}))
    assert ev.verdict == BUY
    assert checks_named(ev, 4, "Fragile")[0].status == FLAG


def test_high_return_category_is_flagged(rated):
    ev = run(rated, make_candidate({"fee_category": "Clothing and Accessories"}))
    assert checks_named(ev, 4, "Returns")[0].status == FLAG


def test_watch_that_fails_gate_4_is_reject(rated):
    ev = run(rated, make_candidate({"purchase_price": 16.00, "amazon_on_listing": True}))
    assert ev.verdict == REJECT and ev.failed_gate == "4"


# --- Stages and source types -------------------------------------------------

def test_source_type_outside_stage_is_rejected(rated):
    ev = run(rated, make_candidate(source_type="liquidation"))
    assert ev.verdict == REJECT and ev.failed_gate == "stage"


def test_source_type_not_built_yet_raises(rated):
    with pytest.raises(SourceNotAvailable, match="phase 2"):
        run(rated, make_candidate(source_type="secondhand"))
