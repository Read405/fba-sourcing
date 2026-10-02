"""Runs the four gates in order and turns the results into a verdict.

Gates stop at the first definite failure. A gate that is only missing data is
UNVERIFIED and evaluation continues, so every definite failure is still found.
A gate-3 failure on profit alone is soft: gate 4 still runs, and if nothing
else fails the verdict is WATCH."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .channels import get_channel
from .core import (BUY, CHECK_MANUALLY, FAIL, REJECT, SOFT_FAIL, UNVERIFIED, WATCH, Candidate,
                   EvalContext, GateResult, cents)
from .gates import GATES
from .sources import get_source


@dataclass
class Evaluation:
    candidate: Candidate
    eval_date: object
    verdict: str
    failed_gate: str | None
    reason: str
    gates: list[GateResult] = field(default_factory=list)
    to_confirm: list[str] = field(default_factory=list)
    units: dict | None = None

    def gate(self, number: int) -> GateResult | None:
        return next((g for g in self.gates if g.number == number), None)


def evaluate(cand: Candidate, ctx: EvalContext) -> Evaluation:
    settings = ctx.settings
    stage = settings.stage()
    if cand.source_type not in stage["source_types"]:
        return Evaluation(cand, ctx.eval_date, REJECT, "stage",
                          f"{cand.source_type} is not enabled in Stage {settings.current_stage}")

    source = get_source(cand.source_type, settings)
    channel = get_channel(cand.channel, settings)
    if not cand.condition:
        cand.condition = source.default_condition

    gates: list[GateResult] = []
    for run_gate in GATES:
        result = run_gate(cand, ctx, source, channel)
        gates.append(result)
        if result.status == FAIL:
            break

    verdict, failed_gate, reason = decide(gates)
    to_confirm = [f"Gate {g.number} {c.name}: {c.detail}" for g in gates for c in g.having(UNVERIFIED)]
    units = plan_units(gates, ctx) if verdict in (BUY, CHECK_MANUALLY) else None
    return Evaluation(cand, ctx.eval_date, verdict, failed_gate, reason, gates, to_confirm, units)


def decide(gates: list[GateResult]) -> tuple[str, str | None, str]:
    for g in gates:
        if g.status == FAIL:
            check = g.having(FAIL)[0]
            return REJECT, str(g.number), f"Gate {g.number} ({g.title}) {check.name}: {check.detail}"
    soft = [(g, c) for g in gates for c in g.having(SOFT_FAIL)]
    if soft:
        g, check = soft[0]
        return WATCH, str(g.number), check.detail
    if any(g.status == UNVERIFIED for g in gates):
        return CHECK_MANUALLY, None, "passed everything that could be verified"
    return BUY, None, "passed all four gates with every required field verified"


def plan_units(gates: list[GateResult], ctx: EvalContext) -> dict | None:
    """Units to buy within the per-product budget share of available capital."""
    g3 = next((g for g in gates if g.number == 3), None)
    landed = g3.data.get("landed") if g3 else None
    if landed is None or not landed.complete or ctx.capital_available is None:
        return None
    t = ctx.settings.threshold
    per_unit = landed.known_total
    cap = cents(ctx.capital_available * t("max_budget_share_per_product"))
    low, high = int(t("units_per_product_min")), int(t("units_per_product_max"))
    units = min(high, int(cap // per_unit)) if per_unit > 0 else 0
    return {
        "available": ctx.capital_available,
        "cap": cap,
        "per_unit": per_unit,
        "units": units,
        "min": low,
        "max": high,
        "total": cents(per_unit * units),
        "enough": units >= low,
    }
