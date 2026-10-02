"""Amazon fee math over data/fees/amazon_us.yaml. Pure functions: every rate,
limit and date comes from the data file, never from code."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from ..core import D, as_date, ceil_div, cents

OZ_PER_LB = Decimal(16)
CUBIC_IN_PER_FT = Decimal(1728)
ZERO = Decimal(0)

TIER_LABELS = {
    "small_standard": "small standard",
    "large_standard": "large standard",
    "small_bulky": "small bulky",
    "large_bulky": "large bulky",
    "extra_large_0_50": "extra-large 0-50 lb",
    "extra_large_50_70": "extra-large 50-70 lb",
    "extra_large_70_150": "extra-large 70-150 lb",
    "extra_large_150_plus": "extra-large 150+ lb",
}
BAND_LABELS = ("under $10", "$10-$50", "over $50")


@dataclass(frozen=True)
class Size:
    tier: str
    standard: bool
    longest: Decimal
    median: Decimal
    shortest: Decimal
    unit_weight_lb: Decimal
    dim_weight_lb: Decimal       # dimensional weight used for this tier
    fee_weight_lb: Decimal       # weight Amazon uses for fees in this tier
    cubic_feet: Decimal

    @property
    def label(self) -> str:
        return TIER_LABELS.get(self.tier, self.tier)


def dimensional_weight(longest: Decimal, median: Decimal, shortest: Decimal,
                       divisor: Decimal, min_side: Decimal | None = None) -> Decimal:
    if min_side is not None:
        median, shortest = max(median, min_side), max(shortest, min_side)
    return longest * median * shortest / divisor


def classify(unit_lb, length, width, height, ful: dict) -> Size:
    """Size tier per Amazon's tier table. Tier weight is the greater of unit
    and dimensional weight; bulky and extra-large tiers assume minimum sides."""
    unit = D(unit_lb)
    longest, median, shortest = sorted((D(length), D(width), D(height)), reverse=True)
    divisor = D(ful["dimensional_weight_divisor"])
    min_side = D(ful["bulky_min_side_in"])
    length_girth = longest + 2 * (median + shortest)
    for spec in ful["size_tiers"]:
        dim = dimensional_weight(longest, median, shortest, divisor,
                                 None if spec["standard"] else min_side)
        weight = max(unit, dim)
        limits = (("max_weight_lb", weight), ("max_longest", longest), ("max_median", median),
                  ("max_shortest", shortest), ("max_length_girth", length_girth))
        if any(key in spec and value > D(spec[key]) for key, value in limits):
            continue
        fee_weight = unit if spec["key"] in ful["unit_weight_tiers"] else weight
        volume = longest * median * shortest / CUBIC_IN_PER_FT
        return Size(spec["key"], bool(spec["standard"]), longest, median, shortest,
                    unit, dim, fee_weight, volume)
    raise ValueError("size tier table has no catch-all tier")


def price_band(price, ful: dict) -> int:
    low, high = (D(x) for x in ful["price_band_limits"])
    p = D(price)
    if p < low:
        return 0
    return 1 if p <= high else 2


def _base_plus_intervals(spec: dict, weight: Decimal, band: int) -> Decimal:
    first = D(spec["first_lb"])
    intervals = ceil_div(weight - first, D(spec["interval_lb"])) if weight > first else 0
    return D(spec["base"][band]) + D(spec["per_interval"]) * intervals


def card_fee(card: dict, cards_by_name: dict, tier: str, weight_lb: Decimal, band: int) -> Decimal | None:
    """Fulfillment fee from one rate card, before surcharges. None if the card
    has no rate for this tier and weight."""
    spec = card["tiers"].get(tier)
    if spec is None and card.get("inherit"):
        spec = cards_by_name[card["inherit"]]["tiers"].get(tier)
    if spec is None:
        return None
    if "bands_oz" in spec:
        w_oz = weight_lb * OZ_PER_LB
        return next((D(row[1 + band]) for row in spec["bands_oz"] if w_oz <= D(row[0])), None)
    if "bands_lb" in spec:
        hit = next((D(row[1 + band]) for row in spec["bands_lb"] if weight_lb <= D(row[0])), None)
        if hit is not None:
            return hit
        spec = spec.get("above")
        if spec is None or weight_lb > D(spec.get("max_lb", weight_lb)):
            return None
    return _base_plus_intervals(spec, weight_lb, band)


def cards_for_window(ful: dict, product_type: str, start: dt.date, end: dt.date) -> tuple[list[dict], bool]:
    """Rate cards in effect at any point in [start, end], and whether published
    cards cover the whole window."""
    hits = sorted((c for c in ful["rate_cards"] if c["product_type"] == product_type
                   and as_date(c["valid_from"]) <= end and as_date(c["valid_to"]) >= start),
                  key=lambda c: as_date(c["valid_from"]))
    covered_to = start - dt.timedelta(days=1)
    for c in hits:
        if as_date(c["valid_from"]) > covered_to + dt.timedelta(days=1):
            break
        covered_to = max(covered_to, as_date(c["valid_to"]))
    return hits, covered_to >= end


def surcharge_rate(ful: dict, start: dt.date, end: dt.date) -> Decimal:
    total = ZERO
    for s in ful.get("surcharges", []):
        valid_to = as_date(s.get("valid_to"))
        if as_date(s["valid_from"]) <= end and (valid_to is None or valid_to >= start):
            total += D(s["rate"])
    return total


def product_types_for(category: str, ful: dict) -> list[str]:
    if category in ful.get("apparel_fee_categories", []):
        return ["apparel"]
    if category in ful.get("ambiguous_fee_categories", []):
        return ["standard", "apparel"]
    return ["standard"]


def fulfillment_fee(ful: dict, category: str, size: Size, price, start: dt.date,
                    end: dt.date) -> tuple[Decimal | None, str]:
    """Highest fulfillment fee in effect during the sell window, with surcharges."""
    band = price_band(price, ful)
    by_name = {c["name"]: c for c in ful["rate_cards"]}
    options: list[tuple[Decimal, str]] = []
    for ptype in product_types_for(category, ful):
        cards, covered = cards_for_window(ful, ptype, start, end)
        if not covered:
            return None, (f"Amazon hasn't published {ptype} rates for the whole sell window "
                          f"{start} to {end}; re-verify fee data")
        for c in cards:
            fee = card_fee(c, by_name, size.tier, size.fee_weight_lb, band)
            if fee is None:
                return None, f"{c['name']} has no rate for {size.label} at {size.fee_weight_lb:.2f} lb"
            options.append((fee, c["name"]))
    fee, card_name = max(options)
    rate = surcharge_rate(ful, start, end)
    detail = (f"{card_name} rate, {size.label}, {size.fee_weight_lb:.2f} lb, "
              f"{BAND_LABELS[band]}: ${fee:.2f}")
    if rate:
        detail += f" + {rate * 100:.1f}% fuel/logistics surcharge"
    return cents(fee * (1 + rate)), detail


def find_category(table: dict, category: str) -> str | None:
    wanted = category.strip().lower()
    return next((name for name in table if name.lower() == wanted), None)


def referral_fee(spec: dict, price) -> Decimal:
    """Referral fee for one category spec: greater of the percentage fee or the
    per-item minimum."""
    p = D(price)
    kind = spec["type"]
    if kind == "flat":
        fee = p * D(spec["rate"])
    elif kind == "whole_price":
        tier = next(t for t in spec["tiers"] if "max_price" not in t or p <= D(t["max_price"]))
        fee = p * D(tier["rate"])
    elif kind == "portion":
        fee, lower = ZERO, ZERO
        for tier in spec["tiers"]:
            upper = D(tier["up_to"]) if "up_to" in tier else None
            top = p if upper is None else min(p, upper)
            if top > lower:
                fee += (top - lower) * D(tier["rate"])
            if upper is None or p <= upper:
                break
            lower = upper
    else:
        raise ValueError(f"unknown referral fee type {kind!r}")
    fee = cents(fee)
    if spec.get("min_fee") is not None:
        fee = max(fee, D(spec["min_fee"]))
    return fee


def months_between(start: dt.date, end: dt.date) -> set[int]:
    months, y, m = set(), start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.add(m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def storage_fee(storage: dict, size: Size, start: dt.date, end: dt.date,
                months_charged: int) -> tuple[Decimal, str]:
    window = months_between(start, end)
    column = "standard" if size.standard else "oversize"
    rate = max(D(r[column]) for r in storage["rates_per_cubic_foot"] if set(r["months"]) & window)
    # Multiply before dividing so 0.065 stays 0.065 instead of 0.0649999...
    cubic_inches = size.longest * size.median * size.shortest
    fee = cents(cubic_inches * rate * months_charged / CUBIC_IN_PER_FT)
    return fee, f"{size.cubic_feet:.3f} cu ft x ${rate:.2f}/cu ft/month x {months_charged}"


def placement_fee(placement: dict, option: str, size: Size, which: str) -> tuple[Decimal | None, str]:
    if size.tier.startswith("extra_large"):
        return ZERO, "extra-large items pay no placement fee"
    if option == "amazon_optimized_splits":
        return ZERO, "Amazon-optimized splits: no fee"
    spec = placement.get(option, {}).get(size.tier)
    if spec is None:
        return None, f"no {option} placement rate for {size.label}"
    col = 2 if which == "high" else 1
    if "bands_oz" in spec:
        w, rows = size.fee_weight_lb * OZ_PER_LB, spec["bands_oz"]
    else:
        w, rows = size.fee_weight_lb, spec["bands_lb"]
    row = next((r for r in rows if w <= D(r[0])), None)
    if row is None:
        return None, f"no {option} placement rate for {size.label} at {size.fee_weight_lb:.2f} lb"
    return D(row[col]), f"{option.replace('_', ' ')}, top of ${D(row[1]):.2f}-${D(row[2]):.2f} range"
