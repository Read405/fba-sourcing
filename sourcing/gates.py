"""The four gates. Gates are source- and channel-agnostic: anything that
depends on where you buy or sell comes from the source or channel plug-in."""
from __future__ import annotations

from decimal import Decimal

from .core import (FAIL, FLAG, INFO, PASS, SOFT_FAIL, UNVERIFIED, Breakdown, Candidate,
                   EvalContext, GateResult, Line, D, as_date, money, pct)

EXACT_MATCH_ATTRS = ("upc", "model", "size", "color", "edition", "pack_count")

# Every field /check fills in. Values are {value, source, retrieved} or
# {unverified: true, note}. "online" fields apply to retail_online only.
FIELD_GUIDE = {
    "purchase_price": "price per unit you'd pay, before tax",
    "shipping_total": "online only: shipping charged on the order",
    "units_in_order": "online only: units in the order (shipping is split across them)",
    "delivery_days": "online only: days until it reaches you",
    "sales_tax_per_unit": "optional: tax per unit from a receipt or order (overrides the location rate)",
    "membership_share_per_unit": "optional: share of a store membership fee per unit",
    "asin": "Amazon ASIN",
    "title": "listing title",
    "brand": "brand on the listing",
    "fee_category": "Amazon fee category exactly as named in data/fees (e.g. Toys and Games)",
    "rank_category": "top-level category the sales rank is in",
    "sales_rank": "current sales rank in rank_category",
    "category_size": "number of products in rank_category (for the rank percentile)",
    "bought_past_month": "optional: the 'bought in past month' figure shown on the listing",
    "seasonality": '{"label": "YEAR-ROUND"} or {"label": "SEASONAL", "season": "...", "demand_drops": "YYYY-MM-DD"}',
    "current_price": "current Buy Box price for the condition you'd list in",
    "avg_price_90d": "90-day average price for the condition you'd list in",
    "unit_weight_lb": "packaged unit weight in pounds",
    "length_in": "packaged length in inches",
    "width_in": "packaged width in inches",
    "height_in": "packaged height in inches",
    "is_hazmat": "true if dangerous goods (hazmat)",
    "has_expiry": "true if the product has an expiration date",
    "months_to_expiry": "months until expiry (when has_expiry is true)",
    "likely_gated": "optional: true if the brand is commonly restricted for new sellers",
    "authenticity_complaints": "optional: true if the brand is known to file complaints against resellers",
    "amazon_on_listing": "true if Amazon itself sells on the listing",
    "brand_owner_only_seller": "true if the brand owner is the only seller",
    "fba_offers_near_buybox": "FBA offers priced within the configured band of the Buy Box",
    "exact_match": '{"upc": true, "model": true, "size": "n/a", "color": "n/a", "edition": "n/a", "pack_count": true}',
    "fragile": "true if the item is fragile",
}
ONLINE_FIELDS = {"shipping_total", "units_in_order", "delivery_days"}
OPTIONAL_FIELDS = {"sales_tax_per_unit", "membership_share_per_unit", "bought_past_month",
                   "likely_gated", "authenticity_complaints", "months_to_expiry"}


def gate1_can_i_sell(cand: Candidate, ctx: EvalContext, source, channel) -> GateResult:
    g = GateResult(1, "Can I sell it?")
    brand, memory = cand.get("brand"), ctx.brand
    if not brand.verified:
        g.add("Brand eligibility", UNVERIFIED, f"brand {brand.provenance}")
    elif memory and memory["status"] == "gated":
        g.add("Brand eligibility", FAIL,
              f"you recorded {brand.value} as gated for your account ({memory['updated_at'][:10]})")
    elif memory and memory["status"] in ("open", "ungated"):
        g.add("Brand eligibility", PASS,
              f"{brand.value} is {memory['status']} for your account (recorded {memory['updated_at'][:10]})")
    else:
        likely = cand.get("likely_gated")
        hint = f" LIKELY GATED for new sellers ({likely.provenance})." if likely.verified and likely.value else ""
        g.add("Brand eligibility", UNVERIFIED,
              f"{brand.value} isn't checked for your account yet.{hint} In Seller Central, search the ASIN "
              f"under Add a Product: 'Apply to sell' or listing limitations means gated. Then record it "
              f"with: brand set \"{brand.value}\" open|ungated|gated")

    complaints = bool(memory and memory.get("complaints"))
    known = cand.get("authenticity_complaints")
    complaints = complaints or bool(known.verified and known.value)
    if complaints:
        if source.proof_of_purchase == "none":
            g.add("Authenticity risk", FLAG,
                  "HIGH RISK: this brand files complaints and this source gives no proof of purchase")
        else:
            g.add("Authenticity risk", FLAG,
                  f"this brand files complaints against resellers; keep your {source.proof_of_purchase}")

    hazmat = cand.get("is_hazmat")
    if not hazmat.verified:
        g.add("Hazmat", UNVERIFIED, f"hazmat status {hazmat.provenance}")
    elif hazmat.value and not ctx.settings.flag("allow_hazmat"):
        g.add("Hazmat", FAIL, "dangerous goods (hazmat); allow_hazmat is false")
    else:
        g.add("Hazmat", PASS, "hazmat allowed" if hazmat.value else "not hazmat")

    expiry = cand.get("has_expiry")
    minimum = ctx.settings.threshold("min_expiry_months")
    if not expiry.verified:
        g.add("Expiration", UNVERIFIED, f"whether it has an expiration date: {expiry.provenance}")
    elif expiry.value:
        months = cand.get("months_to_expiry")
        if not months.verified:
            g.add("Expiration", UNVERIFIED, f"months until expiry {months.provenance}")
        elif D(months.value) < minimum:
            g.add("Expiration", FAIL, f"expires in {months.value} months; your minimum is {minimum}")
        else:
            g.add("Expiration", PASS, f"expires in {months.value} months (minimum {minimum})")
    else:
        g.add("Expiration", PASS, "no expiration date")

    g.checks += channel.eligibility_checks(cand, ctx)
    g.checks += source.checks(cand, ctx)
    return g


def gate2_will_it_sell(cand: Candidate, ctx: EvalContext, source, channel) -> GateResult:
    g = GateResult(2, "Will it sell?")
    rank, size, category = cand.get("sales_rank"), cand.get("category_size"), cand.get("rank_category")
    limit = ctx.settings.threshold("max_rank_percentile")
    if rank.verified and size.verified and D(size.value) > 0:
        percentile = D(rank.value) / D(size.value) * 100
        g.data["rank_percentile"] = percentile
        where = category.value if category.verified else "its category (category UNVERIFIED)"
        detail = (f"rank {int(rank.value):,} of {int(size.value):,} in {where} "
                  f"= top {percentile:.2f}% (limit {limit}%)")
        if percentile > limit:
            g.add("Sales rank", FAIL, detail)
        else:
            g.add("Sales rank", PASS if category.verified else UNVERIFIED, detail)
    else:
        missing = [f.name for f in (rank, size, category) if not f.verified]
        g.add("Sales rank", UNVERIFIED, f"needs verified {', '.join(missing)}")

    bought = cand.get("bought_past_month")
    if bought.verified:
        g.add("Bought in past month", INFO, str(bought.value))

    if cand.condition != "new":
        offers = cand.get("used_offers")
        if offers.verified:
            g.add("Used offers", INFO, str(offers.value))
        else:
            g.add("Used offers", UNVERIFIED, f"count and prices of used offers {offers.provenance}")

    season = cand.get("seasonality")
    if not season.verified:
        g.add("Seasonality", UNVERIFIED, f"label YEAR-ROUND or SEASONAL from rank history: {season.provenance}")
    else:
        v = season.value if isinstance(season.value, dict) else {"label": str(season.value)}
        label = str(v.get("label", "")).upper()
        if label == "YEAR-ROUND":
            g.add("Seasonality", PASS, "YEAR-ROUND")
        elif label == "SEASONAL" and v.get("season") and v.get("demand_drops"):
            try:
                drop = as_date(v["demand_drops"])
            except ValueError:
                g.add("Seasonality", UNVERIFIED, f"demand_drops {v['demand_drops']!r} is not YYYY-MM-DD")
            else:
                days = (drop - ctx.eval_date).days
                g.add("Seasonality", FLAG,
                      f"SEASONAL ({v['season']}): demand drops {drop} ({days} days from now)")
        else:
            g.add("Seasonality", UNVERIFIED, "SEASONAL needs the season and the date demand drops")
    return g


def gate3_will_i_make_money(cand: Candidate, ctx: EvalContext, source, channel) -> GateResult:
    g = GateResult(3, "Will I make money?")
    t = ctx.settings.threshold
    landed = source.landed_cost(cand, ctx)
    g.data["landed"] = landed

    current, average = cand.get("current_price"), cand.get("avg_price_90d")
    sale = None
    if current.verified and average.verified:
        cur, avg = D(current.value), D(average.value)
        sale = min(cur, avg)
        tolerance = t("price_spike_tolerance_pct")
        spike = (cur - avg) / avg * 100 if avg > 0 else Decimal(0)
        if spike > tolerance:
            g.add("Price spike", FAIL, f"current {money(cur)} is {spike:.1f}% above the 90-day average "
                                       f"{money(avg)} (limit {tolerance}%)")
        else:
            g.add("Sale price", PASS, f"using {money(sale)}: lower of current {money(cur)} "
                                      f"and 90-day average {money(avg)}")
    else:
        missing = [f.name for f in (current, average) if not f.verified]
        g.add("Sale price", UNVERIFIED, f"needs verified {', '.join(missing)} for the listing condition")

    if sale is not None:
        low, high = t("sale_price_min"), t("sale_price_max")
        if low <= sale <= high:
            g.add("Price range", PASS, f"{money(sale)} is within {money(low)}-{money(high)}")
        else:
            g.add("Price range", FAIL, f"{money(sale)} is outside your {money(low)}-{money(high)} range")

    weight, max_weight = cand.get("unit_weight_lb"), t("max_weight_lb")
    if not weight.verified:
        g.add("Weight", UNVERIFIED, f"unit weight {weight.provenance}")
    elif D(weight.value) > max_weight:
        g.add("Weight", FAIL, f"{weight.value} lb is over your {max_weight} lb limit")
    else:
        g.add("Weight", PASS, f"{weight.value} lb (limit {max_weight} lb)")

    size, why = channel.size(cand)
    g.data["size"] = size
    if size is None:
        g.add("Size tier", UNVERIFIED, why)
    elif not size.standard and not ctx.settings.flag("allow_oversize"):
        g.add("Size tier", FAIL, f"{size.label} is oversize; allow_oversize is false")
    else:
        g.add("Size tier", PASS, size.label)

    if sale is None:
        return g
    if landed.lines[0].amount is None:
        g.add("Profit", UNVERIFIED, "needs a verified purchase price")
        return g

    fees = channel.fees(cand, sale, size, ctx)
    inbound = channel.inbound_shipping(cand, size, ctx)
    prep = t("prep_cost_per_unit")
    costs = Breakdown(fees.lines + [inbound, Line("Prep", prep, "config.yaml prep_cost_per_unit")])
    g.data.update(sale_price=sale, fees=fees, costs=costs)

    landed_known = landed.known_total
    net = sale - costs.known_total - landed_known
    roi = net / landed_known
    unknown = [l.label for l in costs.unknown() + landed.unknown()]
    min_profit, min_roi = t("min_profit_per_unit"), t("min_roi")
    before_landed = sale - costs.known_total
    target = min(before_landed - min_profit, before_landed / (1 + min_roi))
    g.data.update(net_profit=net, roi=roi, target_landed=target, complete=not unknown)
    summary = f"profit {money(net)}/unit, ROI {pct(roi)} (minimums {money(min_profit)}, {pct(min_roi, 0)})"

    if net >= min_profit and roi >= min_roi:
        if not unknown:
            g.add("Profit", PASS, summary)
        else:
            headroom = min(net - min_profit, net - min_roi * landed_known)
            g.data["headroom"] = headroom
            g.add("Profit", UNVERIFIED,
                  f"{summary} before {', '.join(unknown)}; still passes if those total "
                  f"{money(headroom)} or less per unit")
        return g

    # Unknown costs can only lower profit, so a failure here is definite.
    if target <= 0:
        g.add("Profit", FAIL, f"{summary}: no purchase price makes this work")
        return g
    max_price = source.max_purchase_price(target, landed, cand, ctx)
    g.data["max_purchase_price"] = max_price
    detail = f"{summary}. Becomes a BUY at a landed cost of {money(target)} or less"
    if max_price is not None:
        detail += f" (purchase price {money(max_price)} before tax)"
    if unknown:
        detail += f", plus whatever {', '.join(unknown)} turns out to be"
    g.add("Profit", SOFT_FAIL, detail)
    return g


def gate4_what_can_go_wrong(cand: Candidate, ctx: EvalContext, source, channel) -> GateResult:
    g = GateResult(4, "What can go wrong?")
    g.checks += channel.risk_checks(cand, ctx)

    match = cand.get("exact_match")
    if not match.verified or not isinstance(match.value, dict):
        g.add("Exact match", UNVERIFIED,
              f"compare {', '.join(EXACT_MATCH_ATTRS)} to the listing: {match.provenance}")
    else:
        v = match.value
        matched = [a for a in EXACT_MATCH_ATTRS if v.get(a) is True]
        not_applicable = [a for a in EXACT_MATCH_ATTRS if str(v.get(a)).lower() == "n/a"]
        mismatched = [a for a in EXACT_MATCH_ATTRS if v.get(a) is False]
        unknown = [a for a in EXACT_MATCH_ATTRS if a not in matched + not_applicable + mismatched]
        compared = f"matched: {', '.join(matched) or 'none'}"
        if not_applicable:
            compared += f"; not applicable: {', '.join(not_applicable)}"
        if match.note:
            compared += f"; {match.note}"
        if mismatched:
            g.add("Exact match", FAIL, f"differs from the listing on {', '.join(mismatched)} ({compared})")
        elif unknown:
            g.add("Exact match", UNVERIFIED, f"not compared yet: {', '.join(unknown)} ({compared})")
        else:
            g.add("Exact match", PASS, compared)

    fragile = cand.get("fragile")
    if not fragile.verified:
        g.add("Fragile", UNVERIFIED, f"whether it's fragile: {fragile.provenance}")
    elif fragile.value:
        g.add("Fragile", FLAG, "FRAGILE: pack carefully; damage hurts profit")
    else:
        g.add("Fragile", PASS, "not fragile")
    return g


GATES = (gate1_can_i_sell, gate2_will_it_sell, gate3_will_i_make_money, gate4_what_can_go_wrong)
