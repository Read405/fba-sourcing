"""retail_store and retail_online source types."""
from __future__ import annotations

from ..core import FAIL, PASS, UNVERIFIED, Breakdown, Candidate, Check, D, EvalContext, money
from .base import SourceType


class RetailStore(SourceType):
    """Any physical retailer. New condition, receipt as proof."""

    key = "retail_store"

    def landed_cost(self, cand: Candidate, ctx: EvalContext) -> Breakdown:
        b = Breakdown()
        self.add_price_and_tax(b, cand, ctx)
        self.add_membership(b, cand)
        return b


class RetailOnline(RetailStore):
    """Any retailer or brand website. Adds shipping to you and delivery time."""

    key = "retail_online"

    def landed_cost(self, cand: Candidate, ctx: EvalContext) -> Breakdown:
        b = super().landed_cost(cand, ctx)
        ship, units = cand.get("shipping_total"), cand.get("units_in_order")
        if ship.verified and units.verified and int(units.value) > 0:
            per_unit = D(ship.value) / int(units.value)
            b.add("Shipping to you", per_unit,
                  f"{money(ship.value)} / {int(units.value)} units, {ship.provenance}")
        else:
            missing = [f.name for f in (ship, units) if not f.verified]
            b.add("Shipping to you", None, f"needs {' and '.join(missing)} from the order")
        return b

    def checks(self, cand: Candidate, ctx: EvalContext) -> list[Check]:
        limit = int(ctx.settings.threshold("max_days_to_my_door"))
        days = cand.get("delivery_days")
        if not days.verified:
            return [Check("Delivery time", UNVERIFIED, f"delivery estimate {days.provenance}")]
        n = int(days.value)
        if n > limit:
            return [Check("Delivery time", FAIL, f"arrives in {n} days; your limit is {limit}")]
        return [Check("Delivery time", PASS, f"arrives in {n} days (limit {limit})")]
