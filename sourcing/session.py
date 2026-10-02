"""Start-of-session status: fee data freshness, seller calendar, stage,
capital, and anything that needs your attention."""
from __future__ import annotations

import datetime as dt

from . import db
from .core import D, as_date, money


def fee_freshness(settings, channel: str, today: dt.date) -> tuple[dt.date, int, list[str]]:
    """When the fee data was checked, its age, and every reason to re-verify it."""
    retrieved = as_date(settings.fee_data(channel)["retrieved"])
    age = (today - retrieved).days
    max_age = int(settings.config["paths"]["fee_max_age_days"])
    reasons = []
    if age > max_age:
        reasons.append(f"{age} days old (limit {max_age})")
    if today.year > retrieved.year:
        reasons.append("a new year started since it was checked")
    for period in settings.calendar(channel).get("fee_periods", []):
        if retrieved < as_date(period["start"]) <= today:
            reasons.append(f"{period['name']} started {period['start']}")
    return retrieved, age, reasons


def session_status(settings, conn, today: dt.date) -> str:
    out = [f"Session start: {today.isoformat()}", ""]

    for channel in settings.active_channels:
        retrieved, age, reasons = fee_freshness(settings, channel, today)
        state = "RE-VERIFY: " + "; ".join(reasons) if reasons else "current"
        out.append(f"Fee data ({channel}): checked {retrieved}, {age} days ago. {state}")

    transit = settings.account_cost("inbound_transit_days")
    out += ["", "Seller calendar:"]
    for channel in settings.active_channels:
        cal = settings.calendar(channel)
        for p in cal.get("fee_periods", []):
            start, end = as_date(p["start"]), as_date(p["end"])
            if end < today:
                continue
            when = (f"starts in {(start - today).days} days" if start > today
                    else f"in effect until {end}")
            out.append(f"  {p['name']}: {start} to {end}, {when}")
        for d in cal.get("inbound_deadlines", []):
            arrive = as_date(d["arrive_by"]["minimal_splits"])
            if arrive < today:
                continue
            days_left = (arrive - today).days
            line = f"  {d['event']}: arrive at Amazon by {arrive} (minimal splits), {days_left} days left"
            if transit.verified:
                ship_by = arrive - dt.timedelta(days=int(transit.value))
                line += f"; ship by {ship_by}"
                if ship_by < today:
                    line += ". NOT REALISTIC: the ship-by date has passed"
            else:
                line += "; ship-by date needs your carrier transit time (UNVERIFIED)"
            out.append(line)

    cap = db.capital(conn, settings)
    t = settings.threshold
    stage_no = settings.current_stage
    stage = settings.stage()
    out += ["", f"Stage {stage_no}: buying from {', '.join(stage['source_types'])}",
            f"Capital: {money(cap['starting'])} starting - {money(cap['reserved'])} reserved "
            f"+ {money(cap['ledger_net'])} logged = {money(cap['available'])} available; "
            f"per-product cap {money(cap['available'] * t('max_budget_share_per_product'))}"]
    nxt = settings.config["stages"]["levels"].get(stage_no + 1)
    if nxt and cap["available"] >= D(nxt.get("capital_min", 0)):
        out.append(f"  Your capital meets the Stage {stage_no + 1} minimum. Other requirements still apply, "
                   f"and moving up needs your approval.")
    out.append("Inventory and watchlist: tracking starts in phases 3 and 4.")

    attention = []
    for key in ("inbound_shipping_per_lb", "inbound_transit_days"):
        cost = settings.account_cost(key)
        if not cost.verified:
            attention.append(f"{key} is UNVERIFIED. {cost.note}")
    reserved_plan = D(settings.config["capital"]["reserved"].get("seller_plan_monthly", 0))
    if settings.seller_plan == "individual" and reserved_plan > 0:
        attention.append(f"You're on the Individual plan (no monthly fee), but {money(reserved_plan)}/month "
                         f"is reserved for a seller plan. Keep it reserved or release it?")
    if db.brand_count(conn) == 0:
        attention.append("No brands recorded yet. A product can't be BUY until you confirm its brand "
                         "is open or ungated for your account.")
    if attention:
        out += ["", "Needs your attention:"] + [f"  - {a}" for a in attention]
    return "\n".join(out)
