"""Profit math. The good candidate, worked by hand (evaluated 2026-10-02, so
the 90-day sell window overlaps holiday peak fees):

  sale price      29.99  lower of current 29.99 and 90-day average 31.50
  referral         4.50  15% Toys and Games
  per-item         0.99  Individual plan
  fulfillment      5.53  large standard 1.04 lb (dimensional), $10-$50 peak 5.34 x 1.035
  storage          0.20  8x6x3 in = 144 cu in / 1728 x $2.40 (Q4)
  placement        0.50  minimal splits 12 oz-1.5 lb, top of range
  to Amazon        0.52  1.036 lb x $0.50/lb test rate
  prep             0.15
  landed          10.88  10.00 + 8.75% Norman tax 0.875 -> 0.88
  net profit       6.72  ROI 61.8%
"""
from decimal import Decimal

from conftest import checks_named, make_candidate, run

from sourcing.core import BUY, CHECK_MANUALLY, D, REJECT, WATCH


def test_good_candidate_hand_worked_numbers(rated):
    ev = run(rated, make_candidate())
    g3 = ev.gate(3)
    assert ev.verdict == BUY
    assert g3.data["sale_price"] == D("29.99")
    assert g3.data["landed"].known_total == D("10.88")
    assert {l.label: l.amount for l in g3.data["costs"].lines} == {
        "Referral fee (Toys and Games)": D("4.50"),
        "Per-item fee (individual plan)": D("0.99"),
        "FBA fulfillment fee": D("5.53"),
        "Storage (1 month)": D("0.20"),
        "Inbound placement fee": D("0.50"),
        "Shipping to Amazon": D("0.52"),
        "Prep": D("0.15"),
    }
    assert g3.data["net_profit"] == D("6.72")
    assert round(g3.data["roi"], 4) == D("0.6176")


def test_roi_is_net_profit_over_landed_cost(rated):
    g3 = run(rated, make_candidate()).gate(3)
    assert g3.data["roi"] == g3.data["net_profit"] / g3.data["landed"].known_total


def test_sale_price_is_lower_of_current_and_average(rated):
    g3 = run(rated, make_candidate({"current_price": 33.00})).gate(3)
    assert g3.data["sale_price"] == D("31.50")


def test_price_spike_over_tolerance_rejects(rated):
    ev = run(rated, make_candidate({"current_price": 36.30}))   # 15.2% over 31.50
    assert ev.verdict == REJECT and ev.failed_gate == "3"
    assert checks_named(ev, 3, "Price spike")


def test_price_exactly_at_tolerance_passes(rated):
    ev = run(rated, make_candidate({"current_price": "36.225"}))  # exactly 15% over 31.50
    assert not checks_named(ev, 3, "Price spike")


def test_online_shipping_is_split_across_units(rated):
    cand = make_candidate({"shipping_total": 5.97, "units_in_order": 3, "delivery_days": 3},
                          source_type="retail_online")
    landed = run(rated, cand).gate(3).data["landed"]
    assert [l.amount for l in landed.lines] == [D("10.00"), D("0.88"), D("1.99")]


def test_receipt_tax_overrides_location_rate(rated):
    landed = run(rated, make_candidate({"sales_tax_per_unit": 0.70})).gate(3).data["landed"]
    assert landed.known_total == D("10.70")


def test_low_profit_is_watch_with_target_landed_cost(rated):
    ev = run(rated, make_candidate({"purchase_price": 16.00}))  # landed 17.40, profit 0.20
    g3 = ev.gate(3)
    assert ev.verdict == WATCH
    # 29.99 - 12.39 costs = 17.60 left; target = min(17.60 - 4.00, 17.60 / 1.40) = 12.571...
    assert round(g3.data["target_landed"], 2) == D("12.57")
    assert g3.data["max_purchase_price"] == D("11.56")         # 12.571 / 1.0875
    assert len(ev.gates) == 4                                  # gate 4 still ran


def test_no_purchase_price_can_work_rejects(rated):
    cand = make_candidate({"current_price": 15.00, "avg_price_90d": 15.00, "unit_weight_lb": 1.9,
                           "length_in": 10, "width_in": 8, "height_in": 4})
    ev = run(rated, cand)
    assert ev.verdict == REJECT and ev.failed_gate == "3"
    assert "no purchase price" in ev.reason


def test_unknown_carrier_rate_blocks_buy_and_reports_headroom(settings):
    ev = run(settings, make_candidate())
    g3 = ev.gate(3)
    assert ev.verdict == CHECK_MANUALLY
    assert g3.data["net_profit"] == D("7.24")                  # before shipping to Amazon
    assert g3.data["headroom"] == min(D("7.24") - 4, D("7.24") - D("0.4") * D("10.88"))
    assert any("Shipping to Amazon" in item for item in ev.to_confirm)


def test_failing_before_unknown_costs_is_already_watch(settings):
    ev = run(settings, make_candidate({"purchase_price": 16.00}))
    assert ev.verdict == WATCH


def test_professional_plan_has_no_per_item_fee(rated):
    rated.config["seller"]["plan"] = "professional"
    costs = run(rated, make_candidate()).gate(3).data["costs"]
    assert not any(l.label.startswith("Per-item") for l in costs.lines)


def test_unit_plan_respects_budget_share(rated):
    ev = run(rated, make_candidate())
    assert ev.units["cap"] == D("84.00")                       # 20% of 420.01
    assert ev.units["units"] == 5                              # 84 / 10.88 = 7, capped at 5
    small = run(rated, make_candidate(), capital=Decimal("100"))
    assert small.units["units"] == 1 and not small.units["enough"]
