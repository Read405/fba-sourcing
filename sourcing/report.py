"""Plain-text report for an evaluation, readable on a phone, plus a
JSON-safe record for the database."""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal

from .core import FAIL, FLAG, INFO, PASS, SOFT_FAIL, UNVERIFIED, Breakdown, Line, money, pct
from .evaluator import Evaluation

MARK = {PASS: "PASS", FAIL: "FAIL", SOFT_FAIL: "FAIL", UNVERIFIED: "UNVERIFIED", FLAG: "FLAG", INFO: "info"}
GATE_STATUS = {PASS: "PASS", FAIL: "FAIL", SOFT_FAIL: "FAIL (price/profit)", UNVERIFIED: "UNVERIFIED"}


def _line(l: Line) -> str:
    amount = money(l.amount) if l.amount is not None else "UNVERIFIED"
    return f"    {l.label:<38} {amount:>11}   {l.detail}"


def format_evaluation(ev: Evaluation) -> str:
    c = ev.candidate
    title = c.value("title", "(no title)")
    asin = c.value("asin", "no ASIN")
    out = [
        f"VERDICT: {ev.verdict}",
        f"{title} ({asin})",
        f"Bought at {c.store} ({c.source_type}), listed {c.condition}, sold via {c.channel}. Evaluated {ev.eval_date}.",
        f"Why: {ev.reason}",
        "",
    ]
    for g in ev.gates:
        out.append(f"Gate {g.number}  {g.title}  {GATE_STATUS[g.status]}")
        for check in g.checks:
            out.append(f"  [{MARK[check.status]}] {check.name}: {check.detail}")
    ran = {g.number for g in ev.gates}
    for number in range(1, 5):
        if number not in ran and ev.failed_gate not in (None, "stage"):
            out.append(f"Gate {number}  not run (stopped at gate {ev.failed_gate})")

    g3 = ev.gate(3)
    if g3 and "sale_price" in g3.data:
        out += ["", "Money per unit:", f"    {'Sale price':<38} {money(g3.data['sale_price']):>11}"]
        out += [_line(Line(l.label, -l.amount if l.amount is not None else None, l.detail))
                for l in g3.data["costs"].lines]
        out += [_line(Line(l.label, -l.amount if l.amount is not None else None, l.detail))
                for l in g3.data["landed"].lines]
        net, roi = g3.data["net_profit"], g3.data["roi"]
        suffix = "" if g3.data.get("complete") else "  (before UNVERIFIED costs)"
        out.append(f"    {'Net profit':<38} {money(net):>11}{suffix}")
        out.append(f"    {'ROI':<38} {pct(roi):>11}")
        if ev.verdict == "WATCH":
            out.append(f"    {'Max landed cost for BUY':<38} {money(g3.data['target_landed']):>11}")

    if ev.units:
        u = ev.units
        lead = "Units" if ev.verdict == "BUY" else "Units, if everything checks out"
        out += ["", f"{lead}: {u['units']} at {money(u['per_unit'])} landed = {money(u['total'])} "
                    f"(cap {money(u['cap'])} = budget share of {money(u['available'])} available)"]
        if not u["enough"]:
            out.append(f"  Note: the cap allows {u['units']}, below your minimum of {u['min']} units.")

    if ev.to_confirm:
        out += ["", "To confirm before buying:"] + [f"  - {item}" for item in ev.to_confirm]
    return "\n".join(out)


def to_record(ev: Evaluation) -> dict:
    """JSON-safe snapshot of the evaluation result."""
    gates = []
    for g in ev.gates:
        data = {k: _jsonable(v) for k, v in g.data.items()}
        gates.append({"number": g.number, "title": g.title, "status": g.status,
                      "checks": [dataclasses.asdict(c) for c in g.checks], "data": data})
    return {"verdict": ev.verdict, "failed_gate": ev.failed_gate, "reason": ev.reason,
            "eval_date": str(ev.eval_date), "gates": gates, "to_confirm": ev.to_confirm,
            "units": _jsonable(ev.units)}


def _jsonable(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, Breakdown):
        return [_jsonable(l) for l in v.lines]
    if dataclasses.is_dataclass(v):
        return {k: _jsonable(x) for k, x in dataclasses.asdict(v).items()}
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return str(v)
