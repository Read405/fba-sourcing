"""Start-of-session status: fee data freshness, seller calendar, stage,
capital, and anything that needs your attention. `collect_status` gathers it;
the text status and the dashboard both render from it."""
from __future__ import annotations

import datetime as dt
import os

from . import db
from .core import D, as_date, cents, money


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


def collect_status(settings, conn, today: dt.date) -> dict:
    fees = []
    for channel in settings.active_channels:
        retrieved, age, reasons = fee_freshness(settings, channel, today)
        fees.append({"channel": channel, "retrieved": retrieved, "age": age, "reasons": reasons})

    transit = settings.account_cost("inbound_transit_days")
    periods, deadlines = [], []
    for channel in settings.active_channels:
        cal = settings.calendar(channel)
        for p in cal.get("fee_periods", []):
            start, end = as_date(p["start"]), as_date(p["end"])
            if end >= today:
                periods.append({"name": p["name"], "start": start, "end": end,
                                "starts_in": (start - today).days, "source": p.get("source")})
        for d in cal.get("inbound_deadlines", []):
            arrive = as_date(d["arrive_by"]["minimal_splits"])
            if arrive < today:
                continue
            ship_by = arrive - dt.timedelta(days=int(transit.value)) if transit.verified else None
            deadlines.append({"event": d["event"], "arrive_by": arrive, "days_left": (arrive - today).days,
                              "ship_by": ship_by, "missed": ship_by is not None and ship_by < today,
                              "source": d.get("source")})

    cap = db.capital(conn, settings)
    share = settings.threshold("max_budget_share_per_product")
    stage_no = settings.current_stage
    nxt = settings.config["stages"]["levels"].get(stage_no + 1)
    brands = db.brand_count(conn)

    setup = []
    for key, label in (("inbound_shipping_per_lb", "Shipping cost to Amazon ($/lb)"),
                       ("inbound_transit_days", "Carrier transit days to Amazon")):
        cost = settings.account_cost(key)
        setup.append({"label": label, "ok": cost.verified,
                      "detail": f"{cost.value} ({cost.source}, {cost.retrieved})" if cost.verified else cost.note})
    setup.append({"label": "Brands checked for your account", "ok": brands > 0,
                  "detail": f"{brands} recorded" if brands else
                  "None yet. Check each brand once in Seller Central; /check records it."})
    setup.append({"label": "Keepa API key", "ok": bool(os.environ.get("KEEPA_API_KEY")),
                  "detail": "set" if os.environ.get("KEEPA_API_KEY") else
                  "Not set. Read 90-day prices and rank history off Keepa's free chart for now."})
    for f in fees:
        setup.append({"label": f"Fee data ({f['channel']})", "ok": not f["reasons"],
                      "detail": f"checked {f['retrieved']}, {f['age']} days ago"
                                + (f". Re-verify: {'; '.join(f['reasons'])}" if f["reasons"] else "")})

    attention = [f"{item['label']}: {item['detail']}" for item in setup[:2] if not item["ok"]]
    reserved_plan = D(settings.config["capital"]["reserved"].get("seller_plan_monthly", 0))
    if settings.seller_plan == "individual" and reserved_plan > 0:
        attention.append(f"You're on the Individual plan (no monthly fee), but {money(reserved_plan)}/month "
                         f"is reserved for a seller plan. Keep it reserved or release it?")
    if not brands:
        attention.append("No brands recorded yet. A product can't be BUY until you confirm its brand "
                         "is open or ungated for your account.")

    return {
        "today": today,
        "fees": fees,
        "periods": periods,
        "deadlines": deadlines,
        "stage": stage_no,
        "source_types": settings.stage()["source_types"],
        "capital": cap,
        "per_product_cap": cents(cap["available"] * share),
        "next_stage_capital_met": bool(nxt and cap["available"] >= D(nxt.get("capital_min", 0))),
        "location": settings.location()["name"],
        "plan": settings.seller_plan,
        "setup": setup,
        "attention": attention,
    }


def session_status(settings, conn, today: dt.date) -> str:
    s = collect_status(settings, conn, today)
    out = [f"Session start: {today.isoformat()}", ""]
    for f in s["fees"]:
        state = "RE-VERIFY: " + "; ".join(f["reasons"]) if f["reasons"] else "current"
        out.append(f"Fee data ({f['channel']}): checked {f['retrieved']}, {f['age']} days ago. {state}")

    out += ["", "Seller calendar:"]
    for p in s["periods"]:
        when = f"starts in {p['starts_in']} days" if p["starts_in"] > 0 else f"in effect until {p['end']}"
        out.append(f"  {p['name']}: {p['start']} to {p['end']}, {when}")
    for d in s["deadlines"]:
        line = f"  {d['event']}: arrive at Amazon by {d['arrive_by']} (minimal splits), {d['days_left']} days left"
        if d["ship_by"]:
            line += f"; ship by {d['ship_by']}"
            if d["missed"]:
                line += ". NOT REALISTIC: the ship-by date has passed"
        else:
            line += "; ship-by date needs your carrier transit time (UNVERIFIED)"
        out.append(line)

    cap = s["capital"]
    out += ["", f"Stage {s['stage']}: buying from {', '.join(s['source_types'])}",
            f"Capital: {money(cap['starting'])} starting - {money(cap['reserved'])} reserved "
            f"+ {money(cap['ledger_net'])} logged = {money(cap['available'])} available; "
            f"per-product cap {money(s['per_product_cap'])}"]
    if s["next_stage_capital_met"]:
        out.append(f"  Your capital meets the Stage {s['stage'] + 1} minimum. Other requirements still apply, "
                   f"and moving up needs your approval.")
    out.append("Inventory and watchlist: tracking starts in phases 3 and 4.")
    if s["attention"]:
        out += ["", "Needs your attention:"] + [f"  - {a}" for a in s["attention"]]
    return "\n".join(out)
