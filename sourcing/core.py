"""Data model shared by every part of the evaluator: money, sourced fields,
candidates, cost breakdowns and gate results."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")

# Check and gate statuses. SOFT_FAIL means "failed only on price or profit",
# which can become a WATCH verdict instead of a REJECT.
PASS = "pass"
FAIL = "fail"
SOFT_FAIL = "soft_fail"
UNVERIFIED = "unverified"
FLAG = "flag"
INFO = "info"

BUY = "BUY"
CHECK_MANUALLY = "CHECK MANUALLY"
WATCH = "WATCH"
REJECT = "REJECT"


def D(x: Any) -> Decimal:
    """Exact decimal from an int, str, float or Decimal (floats go through str)."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def cents(x: Any) -> Decimal:
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def ceil_div(x: Decimal, step: Decimal) -> int:
    return int((x / step).to_integral_value(rounding=ROUND_CEILING))


def money(x: Any) -> str:
    v = cents(x)
    return f"{'-' if v < 0 else ''}${abs(v):,.2f}"


def pct(x: Any, places: int = 1) -> str:
    return f"{D(x) * 100:.{places}f}%"


def as_date(x: Any) -> dt.date | None:
    if x is None or isinstance(x, dt.date):
        return x
    return dt.date.fromisoformat(str(x))


@dataclass(frozen=True)
class Sourced:
    """One input value and where it came from. Only `verified` values may
    support a BUY verdict."""

    name: str
    value: Any = None
    source: str | None = None
    retrieved: str | None = None
    verified: bool = False
    note: str = ""

    @property
    def provenance(self) -> str:
        if self.verified:
            return f"{self.source} ({self.retrieved})"
        return "UNVERIFIED" + (f": {self.note}" if self.note else "")


def parse_field(name: str, raw: Any) -> Sourced:
    """A field is verified only when it has a value, a source, and a
    YYYY-MM-DD retrieval date. Anything less is UNVERIFIED."""
    if raw is None:
        return Sourced(name, note="not provided")
    if not isinstance(raw, dict):
        return Sourced(name, value=raw, note="no source or retrieval date given")
    if raw.get("unverified"):
        return Sourced(name, value=raw.get("value"), note=raw.get("note", ""))
    value, source, retrieved = raw.get("value"), raw.get("source"), raw.get("retrieved")
    missing = [k for k, v in (("value", value), ("source", source), ("retrieved", retrieved)) if v in (None, "")]
    if missing:
        return Sourced(name, value=value, source=source, retrieved=retrieved,
                       note="missing " + ", ".join(missing))
    try:
        dt.date.fromisoformat(str(retrieved))
    except ValueError:
        return Sourced(name, value=value, source=source, retrieved=str(retrieved),
                       note=f"retrieved date {retrieved!r} is not YYYY-MM-DD")
    return Sourced(name, value, str(source), str(retrieved), True, raw.get("note", ""))


@dataclass
class Candidate:
    source_type: str
    store: str
    channel: str
    condition: str
    fields: dict[str, Sourced]
    location: str | None = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Candidate":
        missing = [k for k in ("source_type", "store", "channel") if not data.get(k)]
        if missing:
            raise ValueError(f"candidate is missing {', '.join(missing)}")
        fields = {name: parse_field(name, raw) for name, raw in (data.get("fields") or {}).items()}
        return cls(
            source_type=data["source_type"],
            store=data["store"],
            channel=data["channel"],
            condition=(data.get("condition") or "").lower(),
            fields=fields,
            location=data.get("location"),
            raw=data,
        )

    def get(self, name: str) -> Sourced:
        return self.fields.get(name) or Sourced(name, note="not provided")

    def value(self, name: str, default: Any = None) -> Any:
        f = self.get(name)
        return default if f.value is None else f.value


@dataclass
class EvalContext:
    """Everything an evaluation needs besides the candidate itself."""

    settings: Any                 # config.Settings
    eval_date: dt.date
    brand: dict | None = None     # brand memory row for the candidate's brand, if any
    capital_available: Decimal | None = None

    def sell_window(self) -> tuple[dt.date, dt.date]:
        """Dates the unit could plausibly sell in. Fees use the highest rate in
        effect anywhere in this window, which can only understate profit."""
        days = int(self.settings.assumption("sell_window_days"))
        return self.eval_date, self.eval_date + dt.timedelta(days=days)


@dataclass
class Line:
    """One cost or fee per unit. amount None means UNVERIFIED."""

    label: str
    amount: Decimal | None
    detail: str = ""


@dataclass
class Breakdown:
    lines: list[Line] = field(default_factory=list)

    def add(self, label: str, amount: Decimal | None, detail: str = "") -> Line:
        line = Line(label, None if amount is None else cents(amount), detail)
        self.lines.append(line)
        return line

    @property
    def known_total(self) -> Decimal:
        return sum((l.amount for l in self.lines if l.amount is not None), Decimal("0"))

    @property
    def complete(self) -> bool:
        return all(l.amount is not None for l in self.lines)

    def unknown(self) -> list[Line]:
        return [l for l in self.lines if l.amount is None]


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class GateResult:
    number: int
    title: str
    checks: list[Check] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def add(self, name: str, status: str, detail: str) -> "GateResult":
        self.checks.append(Check(name, status, detail))
        return self

    @property
    def status(self) -> str:
        statuses = {c.status for c in self.checks}
        for s in (FAIL, SOFT_FAIL, UNVERIFIED):
            if s in statuses:
                return s
        return PASS

    def having(self, *statuses: str) -> list[Check]:
        return [c for c in self.checks if c.status in statuses]
