"""Interface every source type implements. A source type knows what buying
from it costs and what extra rules apply; it never knows where you sell."""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from ..core import Breakdown, Candidate, Check, D, EvalContext, Sourced, cents, money, pct


class SourceType(ABC):
    key: str = ""

    def __init__(self, spec: dict):
        self.spec = spec

    @property
    def default_condition(self) -> str:
        return self.spec.get("default_condition", "new")

    @property
    def proof_of_purchase(self) -> str:
        return self.spec.get("proof_of_purchase", "none")

    @abstractmethod
    def landed_cost(self, cand: Candidate, ctx: EvalContext) -> Breakdown:
        """Per-unit cost to get the item to you: price, tax, and every
        source-specific cost."""

    def checks(self, cand: Candidate, ctx: EvalContext) -> list[Check]:
        """Source-specific rules (gate 1)."""
        return []

    # --- helpers shared by source types ---------------------------------
    def tax_rate(self, cand: Candidate, ctx: EvalContext) -> Sourced:
        override = cand.get("sales_tax_rate")
        if override.verified:
            return Sourced("sales_tax_rate", D(override.value), override.source, override.retrieved, True)
        return ctx.settings.sales_tax(cand.location)

    def add_price_and_tax(self, b: Breakdown, cand: Candidate, ctx: EvalContext) -> None:
        price = cand.get("purchase_price")
        if not price.verified:
            b.add("Purchase price", None, price.provenance)
            b.add("Sales tax", None, "needs a verified purchase price")
            return
        p = D(price.value)
        b.add("Purchase price", p, price.provenance)
        per_unit = cand.get("sales_tax_per_unit")
        if per_unit.verified:
            b.add("Sales tax", D(per_unit.value), per_unit.provenance)
            return
        rate = self.tax_rate(cand, ctx)
        if rate.verified:
            b.add(f"Sales tax ({pct(rate.value, 3)})", p * rate.value, rate.provenance)
        else:
            b.add("Sales tax", None, rate.provenance)

    def add_membership(self, b: Breakdown, cand: Candidate) -> None:
        share = cand.get("membership_share_per_unit")
        if share.value is not None or share.note != "not provided":
            b.add("Membership share", D(share.value) if share.verified else None, share.provenance)

    def max_purchase_price(self, target_landed: Decimal, landed: Breakdown,
                           cand: Candidate, ctx: EvalContext) -> Decimal | None:
        """Highest purchase price that keeps landed cost at or under the target."""
        extras = sum((l.amount for l in landed.lines
                      if l.amount is not None and not l.label.startswith(("Purchase price", "Sales tax"))),
                     Decimal("0"))
        rate = self.tax_rate(cand, ctx)
        if not rate.verified:
            return None
        price = (target_landed - extras) / (1 + rate.value)
        return cents(price) if price > 0 else None


def describe_costs(b: Breakdown) -> str:
    return ", ".join(f"{l.label} {money(l.amount) if l.amount is not None else 'UNVERIFIED'}" for l in b.lines)
