"""Load config.yaml, sources.yaml, and each channel's fee data and calendar."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from .core import D, Sourced, as_date

ROOT = Path(__file__).resolve().parent.parent


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Settings:
    root: Path
    config: dict
    sources: dict
    _cache: dict = field(default_factory=dict)

    # --- thresholds and policy -------------------------------------------
    def threshold(self, key: str) -> Decimal:
        return D(self.config["thresholds"][key])

    def flag(self, key: str) -> bool:
        return bool(self.config["thresholds"][key])

    def assumption(self, key: str):
        return self.config["assumptions"][key]

    @property
    def seller_plan(self) -> str:
        return self.config["seller"]["plan"]

    # --- location ----------------------------------------------------------
    def location(self, key: str | None = None) -> dict:
        locs = self.config["locations"]
        key = key or locs["active"]
        if key not in locs["saved"]:
            raise KeyError(f"location {key!r} is not saved in config.yaml")
        return {"key": key, **locs["saved"][key]}

    def sales_tax(self, key: str | None = None) -> Sourced:
        loc = self.location(key)
        rate = loc.get("sales_tax_rate")
        if rate is None or not loc.get("sales_tax_source"):
            return Sourced("sales_tax_rate", note=f"no sourced sales tax rate saved for {loc['name']}")
        return Sourced("sales_tax_rate", D(rate), loc["sales_tax_source"],
                       str(loc.get("sales_tax_retrieved")), True, loc["name"])

    # --- costs only the seller's account can confirm ------------------------
    def account_cost(self, key: str) -> Sourced:
        entry = self.config.get("unverified_costs", {}).get(key) or {}
        if entry.get("value") is None or not entry.get("source") or not entry.get("retrieved"):
            return Sourced(key, note=entry.get("how_to_get", "not set in config.yaml"))
        return Sourced(key, D(entry["value"]), entry["source"], str(entry["retrieved"]), True)

    # --- stages and capital ------------------------------------------------
    @property
    def current_stage(self) -> int:
        return int(self.config["stages"]["current"])

    def stage(self, number: int | None = None) -> dict:
        return self.config["stages"]["levels"][number or self.current_stage]

    @property
    def reserved_total(self) -> Decimal:
        return sum((D(v) for v in self.config["capital"]["reserved"].values()), Decimal("0"))

    # --- data files --------------------------------------------------------
    def fee_data(self, channel: str) -> dict:
        return self._data("fees", channel)

    def calendar(self, channel: str) -> dict:
        return self._data("calendar", channel)

    def _data(self, kind: str, channel: str) -> dict:
        key = (kind, channel)
        if key not in self._cache:
            rel = self.config["paths"][kind].get(channel)
            if not rel:
                raise KeyError(f"no {kind} file configured for channel {channel!r}")
            self._cache[key] = _read_yaml(self.root / rel)
        return self._cache[key]

    @property
    def db_path(self) -> Path:
        return self.root / self.config["paths"]["database"]

    @property
    def active_channels(self) -> list[str]:
        return list(self.config["channels"]["active"])


def load(root: Path | None = None) -> Settings:
    root = Path(root or ROOT)
    settings = Settings(root, _read_yaml(root / "config.yaml"), _read_yaml(root / "sources.yaml"))
    for loc in settings.config["locations"]["saved"].values():
        as_date(loc.get("sales_tax_retrieved"))  # fail fast on a malformed date
    return settings
