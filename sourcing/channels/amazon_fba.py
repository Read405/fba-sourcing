"""Amazon FBA selling channel."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from ..core import (FAIL, FLAG, PASS, UNVERIFIED, Breakdown, Candidate, Check, D, EvalContext,
                    Line, as_date, cents, money)
from . import amazon_fees as af
from .base import Channel


class AmazonFBA(Channel):
    key = "amazon_fba"

    def __init__(self, settings):
        super().__init__(settings)
        self.data = settings.fee_data(self.key)

    def fee_retrieved(self) -> dt.date:
        return as_date(self.data["retrieved"])

    def size(self, cand: Candidate):
        fields = [cand.get(n) for n in ("unit_weight_lb", "length_in", "width_in", "height_in")]
        missing = [f.name for f in fields if not f.verified]
        if missing:
            return None, f"needs verified {', '.join(missing)}"
        unit, length, width, height = (D(f.value) for f in fields)
        return af.classify(unit, length, width, height, self.data["fulfillment"]), ""

    def fees(self, cand: Candidate, sale_price: Decimal, size, ctx: EvalContext) -> Breakdown:
        b = Breakdown()
        start, end = ctx.sell_window()
        cat = cand.get("fee_category")
        category = af.find_category(self.data["referral"]["categories"], cat.value) if cat.verified else None

        if not cat.verified:
            b.add("Referral fee", None, f"fee category {cat.provenance}")
        elif category is None:
            b.add("Referral fee", None, f"{cat.value!r} is not an Amazon fee category in data/fees")
        else:
            spec = self.data["referral"]["categories"][category]
            b.add(f"Referral fee ({category})", af.referral_fee(spec, sale_price), self.data["referral"]["source"])

        plan = ctx.settings.seller_plan
        per_item = D(self.data["selling_plans"][plan]["per_item_fee"])
        if per_item:
            b.add(f"Per-item fee ({plan} plan)", per_item, self.data["selling_plans"]["source"])

        closing = self.data["closing_fee"]
        if category in closing["fee_categories"]:
            b.add("Closing fee", D(closing["amount"]), closing["source"])

        ful = self.data["fulfillment"]
        hazmat = cand.get("is_hazmat")
        if size is None:
            b.add("FBA fulfillment fee", None, "needs verified weight and dimensions")
        elif hazmat.verified and hazmat.value:
            b.add("FBA fulfillment fee", None, ful["hazmat_note"])
        elif category is None:
            b.add("FBA fulfillment fee", None, "needs a verified fee category (apparel uses different rates)")
        else:
            fee, detail = af.fulfillment_fee(ful, category, size, sale_price, start, end)
            b.add("FBA fulfillment fee", fee, detail)

        if size is None:
            b.add("Storage", None, "needs verified dimensions")
            b.add("Inbound placement fee", None, "needs verified weight and dimensions")
            return b
        months = int(ctx.settings.assumption("storage_months_charged"))
        fee, detail = af.storage_fee(self.data["storage"], size, start, end, months)
        b.add(f"Storage ({months} month)", fee, detail)
        fee, detail = af.placement_fee(self.data["inbound_placement"],
                                       ctx.settings.assumption("inbound_placement_option"),
                                       size, ctx.settings.assumption("inbound_placement_rate"))
        b.add("Inbound placement fee", fee, detail)
        return b

    def inbound_shipping(self, cand: Candidate, size, ctx: EvalContext) -> Line:
        rate = ctx.settings.account_cost("inbound_shipping_per_lb")
        if size is None:
            return Line("Shipping to Amazon", None, "needs verified weight and dimensions")
        if not rate.verified:
            return Line("Shipping to Amazon", None, f"your carrier rate per lb is UNVERIFIED: {rate.note}")
        weight = max(size.unit_weight_lb, size.dim_weight_lb)
        return Line("Shipping to Amazon", cents(weight * rate.value),
                    f"{weight:.2f} lb x {money(rate.value)}/lb ({rate.source}, {rate.retrieved})")

    def eligibility_checks(self, cand: Candidate, ctx: EvalContext) -> list[Check]:
        if cand.condition == "new":
            return [Check("Listing condition", PASS, "listing as New")]
        allowed = cand.get("condition_allowed")
        category = cand.value("fee_category", "this category")
        if not allowed.verified:
            return [Check("Listing condition", UNVERIFIED,
                          f"confirm {category} accepts {cand.condition} items: {allowed.provenance}")]
        if not allowed.value:
            return [Check("Listing condition", FAIL, f"{category} does not accept {cand.condition} items")]
        return [Check("Listing condition", PASS, f"{category} accepts {cand.condition} ({allowed.provenance})")]

    def risk_checks(self, cand: Candidate, ctx: EvalContext) -> list[Check]:
        t = ctx.settings.threshold
        checks = [
            _bool_check(cand.get("amazon_on_listing"), "Amazon on listing",
                        fail="Amazon itself sells on this listing", ok="Amazon is not a seller"),
            _bool_check(cand.get("brand_owner_only_seller"), "Brand owner only",
                        fail="the only seller is the brand owner", ok="other sellers besides the brand owner"),
        ]
        offers, limit, band = cand.get("fba_offers_near_buybox"), int(t("max_fba_offers_near_buybox")), t("buybox_band_pct")
        if not offers.verified:
            checks.append(Check("FBA offers near Buy Box", UNVERIFIED,
                                f"count FBA offers within {band}% of the Buy Box: {offers.provenance}"))
        else:
            n = int(offers.value)
            status = FAIL if n > limit else PASS
            checks.append(Check("FBA offers near Buy Box", status, f"{n} within {band}% (limit {limit})"))

        cat = cand.get("fee_category")
        if cat.verified:
            rp = self.data["returns_processing"]
            category = af.find_category(rp["return_rate_threshold_pct"], cat.value)
            threshold = rp["return_rate_threshold_pct"].get(category) if category else None
            if cat.value in rp["per_return_fee_categories"]:
                checks.append(Check("Returns", FLAG, "HIGH-RETURN: apparel and shoes pay Amazon's returns fee on every return"))
            elif threshold is not None and D(threshold) >= D(ctx.settings.assumption("high_return_threshold_pct")):
                checks.append(Check("Returns", FLAG,
                                    f"HIGH-RETURN category: Amazon expects up to {threshold}% returns in {category}"))
        return checks


def _bool_check(field, name: str, fail: str, ok: str) -> Check:
    if not field.verified:
        return Check(name, UNVERIFIED, field.provenance)
    return Check(name, FAIL, fail) if field.value else Check(name, PASS, ok)
