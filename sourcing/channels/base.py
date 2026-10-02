"""Interface every selling channel implements. A channel owns its fees,
eligibility rules and listing risks; the evaluator never knows which channel
it is talking to."""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from ..core import Breakdown, Candidate, Check, EvalContext, Line


class Channel(ABC):
    key: str = ""

    def __init__(self, settings):
        self.settings = settings

    @abstractmethod
    def fee_retrieved(self) -> dt.date:
        """Date the channel's fee data was last verified."""

    @abstractmethod
    def size(self, cand: Candidate) -> tuple[Any | None, str]:
        """(size info with .tier, .label and .standard, or None plus the reason)."""

    @abstractmethod
    def fees(self, cand: Candidate, sale_price: Decimal, size: Any | None,
             ctx: EvalContext) -> Breakdown:
        """Every per-unit fee the channel charges when the unit sells."""

    @abstractmethod
    def inbound_shipping(self, cand: Candidate, size: Any | None, ctx: EvalContext) -> Line:
        """Per-unit cost to ship the unit to the channel."""

    def eligibility_checks(self, cand: Candidate, ctx: EvalContext) -> list[Check]:
        """Channel rules for gate 1 (can I sell it?)."""
        return []

    def risk_checks(self, cand: Candidate, ctx: EvalContext) -> list[Check]:
        """Channel rules for gate 4 (what can go wrong?)."""
        return []
