"""Local HTML dashboard built from data/sourcing.db, config.yaml and the seller
calendar. It is one self-contained file with no outside requests; it stays on
this machine and is never committed."""
from __future__ import annotations

import copy
import datetime as dt
import html
import json
from decimal import Decimal
from pathlib import Path

from . import db
from .config import Settings
from .core import BUY, CHECK_MANUALLY, REJECT, WATCH, Candidate, D, EvalContext, money, pct
from .evaluator import evaluate
from .report import to_record
from .session import collect_status

DASHBOARD_FILE = "dashboard.html"
DEMO_FILE = "dashboard-demo.html"
TIMELINE_DAYS = 100

VERDICT_TONE = {BUY: ("good", "✓"), CHECK_MANUALLY: ("warning", "?"),
                WATCH: ("serious", "◔"), REJECT: ("critical", "✕")}
CHECK_TONE = {"pass": ("good", "✓", "Pass"), "fail": ("critical", "✕", "Fail"),
              "soft_fail": ("serious", "◔", "Profit too low"), "unverified": ("warning", "?", "Unverified"),
              "flag": ("serious", "!", "Flag"), "info": ("muted", "i", "Info")}
GATE_NAMES = {"1": "Gate 1 · Can I sell it?", "2": "Gate 2 · Will it sell?",
              "3": "Gate 3 · Will I make money?", "4": "Gate 4 · What can go wrong?",
              "stage": "Not allowed in your stage"}
SHIPPING_LABELS = ("Shipping to Amazon", "Prep")


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def badge(tone: str, icon: str, label: str) -> str:
    return (f'<span class="badge"><span class="dot t-{tone}" aria-hidden="true">{icon}</span>'
            f'{esc(label)}</span>')


def verdict_badge(verdict: str) -> str:
    tone, icon = VERDICT_TONE.get(verdict, ("muted", "•"))
    return badge(tone, icon, verdict)


def short_date(d) -> str:
    d = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d))
    return f"{d:%b} {d.day}"


# --- data -------------------------------------------------------------------

def load_evaluations(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute("SELECT * FROM evaluations WHERE active = 1 ORDER BY id DESC LIMIT ?",
                        (limit,)).fetchall()
    out = []
    for r in rows:
        record = json.loads(r["result_json"])
        g3 = next((g for g in record.get("gates", []) if g["number"] == 3), None)
        out.append({**dict(r), "record": record, "money": g3["data"] if g3 else {}})
    return out


def counts(conn, column: str, where: str = "") -> dict:
    sql = f"SELECT {column} AS k, COUNT(*) AS n FROM evaluations WHERE active = 1 {where} GROUP BY {column}"
    return {row["k"]: row["n"] for row in conn.execute(sql)}


def _amount(line: dict) -> Decimal | None:
    return None if line.get("amount") is None else D(line["amount"])


def _group(lines: list[dict]) -> tuple[Decimal, list[str]]:
    known = sum((a for a in map(_amount, lines) if a is not None), Decimal(0))
    return known, [l["label"] for l in lines if _amount(l) is None]


# --- pieces -----------------------------------------------------------------

def render_split(data: dict) -> str:
    """Where the sale price goes: one stacked bar plus a legend with values."""
    if "sale_price" not in data or "net_profit" not in data:
        return '<p class="empty">No money breakdown: the check stopped before profit could be worked out.</p>'
    sale, net = D(data["sale_price"]), D(data["net_profit"])
    costs = data.get("costs") or []
    groups = [("Amazon fees", *_group([l for l in costs if l["label"] not in SHIPPING_LABELS]), "s2"),
              ("Shipping & prep", *_group([l for l in costs if l["label"] in SHIPPING_LABELS]), "s3"),
              ("Your cost", *_group(data.get("landed") or []), "s4")]
    segments = ([("Profit", net, [], "s1")] if net > 0 else []) + groups
    cost_total = sum(g[1] for g in groups)
    scale = max(sale, cost_total) or Decimal(1)

    bar, legend = [], []
    for label, amount, unknown, slot in segments:
        width = amount / scale * 100
        note = f" + unverified: {', '.join(unknown)}" if unknown else ""
        inside = f'<span class="seg-label">{esc(money(amount))}</span>' if width >= 16 else ""
        bar.append(f'<span class="seg {slot}" style="flex-basis:{width:.3f}%" tabindex="0" '
                   f'data-tip="{esc(label)}: {esc(money(amount))}{esc(note)}">{inside}</span>')
        legend.append(f'<li><span class="swatch {slot}"></span>{esc(label)} '
                      f'<b>{esc(money(amount))}</b>{esc(note)}</li>')
    marker = ""
    if cost_total > sale:
        at = sale / scale * 100
        marker = (f'<span class="sale-mark" style="left:{at:.3f}%" tabindex="0" '
                  f'data-tip="Sale price {esc(money(sale))}"></span>')
        caption = f"Costs of {money(cost_total)} are more than the {money(sale)} sale price"
    else:
        caption = f"Where the {money(sale)} sale price goes"
    unknown_all = [u for g in groups for u in g[2]]
    footnote = (f'<p class="note">Profit is before UNVERIFIED costs: {esc(", ".join(unknown_all))}.</p>'
                if unknown_all else "")
    return (f'<figure class="split"><figcaption>{esc(caption)}</figcaption>'
            f'<div class="split-bar">{"".join(bar)}{marker}</div>'
            f'<ul class="legend">{"".join(legend)}</ul>{footnote}</figure>')


def render_money_table(data: dict) -> str:
    if "sale_price" not in data:
        return ""
    rows = [("Sale price", D(data["sale_price"]), "")]
    for line in (data.get("costs") or []) + (data.get("landed") or []):
        amount = _amount(line)
        rows.append((line["label"], None if amount is None else -amount, line.get("detail", "")))
    body = "".join(
        f'<tr><td>{esc(label)}</td><td class="num">{esc(money(v)) if v is not None else "UNVERIFIED"}</td>'
        f'<td class="muted small">{esc(detail)}</td></tr>' for label, v, detail in rows)
    net, roi = D(data["net_profit"]), D(data["roi"])
    body += (f'<tr class="total"><td>Net profit</td><td class="num">{esc(money(net))}</td><td></td></tr>'
             f'<tr class="total"><td>ROI</td><td class="num">{esc(pct(roi))}</td><td></td></tr>')
    return (f'<details class="money-table"><summary>Table view</summary>'
            f'<table><tbody>{body}</tbody></table></details>')


def render_gates(ev: dict) -> str:
    gates = ev["record"].get("gates", [])
    out = []
    for g in gates:
        tone, icon, label = CHECK_TONE.get(g["status"], ("muted", "•", g["status"]))
        items = "".join(
            f'<li><span class="dot sm t-{CHECK_TONE.get(c["status"], ("muted", "•"))[0]}" aria-hidden="true">'
            f'{CHECK_TONE.get(c["status"], ("muted", "•"))[1]}</span><span><b>{esc(c["name"])}</b> '
            f'{esc(c["detail"])}</span></li>' for c in g["checks"])
        out.append(f'<div class="gate"><div class="gate-head"><span>{esc(GATE_NAMES[str(g["number"])])}</span>'
                   f'{badge(tone, icon, label)}</div><ul class="checks">{items}</ul></div>')
    ran = {str(g["number"]) for g in gates}
    if ev["failed_gate"] == "stage":
        out.append(f'<div class="gate"><div class="gate-head"><span>{GATE_NAMES["stage"]}</span>'
                   f'{badge("critical", "✕", "Fail")}</div><p class="small">{esc(ev["reason"])}</p></div>')
    elif ev["failed_gate"]:
        for n in "1234":
            if n not in ran:
                out.append(f'<div class="gate skipped"><div class="gate-head"><span>{GATE_NAMES[n]}</span>'
                           f'<span class="muted small">Not run, stopped at gate {esc(ev["failed_gate"])}</span>'
                           f'</div></div>')
    return "".join(out)


def render_detail(ev: dict) -> str:
    units = ev["record"].get("units") or {}
    plan = ""
    if units:
        plan = (f'<p class="plan">Buy <b>{units["units"]} units</b> at {esc(money(units["per_unit"]))} landed '
                f'= {esc(money(units["total"]))} (cap {esc(money(units["cap"]))})</p>')
    confirm = ev["record"].get("to_confirm") or []
    confirm_html = ("<h3>To confirm before buying</h3><ul class=\"confirm\">"
                    + "".join(f"<li>{esc(c)}</li>" for c in confirm) + "</ul>") if confirm else ""
    return (f'<div class="detail-head"><div><div class="detail-title">{esc(ev["title"] or "(untitled)")}</div>'
            f'<div class="muted small">{esc(ev["store"])} · {esc(ev["source_type"])} · {esc(ev["asin"] or "no ASIN")}'
            f' · checked {esc(short_date(ev["eval_date"]))}</div></div>{verdict_badge(ev["verdict"])}</div>'
            f'<p class="reason">{esc(ev["reason"])}</p>{plan}'
            f'<div class="detail-grid"><div>{render_gates(ev)}</div>'
            f'<div>{render_split(ev["money"])}{render_money_table(ev["money"])}{confirm_html}</div></div>')


def render_timeline(status: dict) -> str:
    today = status["today"]
    end = today + dt.timedelta(days=TIMELINE_DAYS)

    def pos(d: dt.date) -> float:
        return max(0.0, min(100.0, (d - today).days / TIMELINE_DAYS * 100))

    ticks, labels, d = [], [], dt.date(today.year, today.month, 1)
    while d <= end:
        if d > today:
            ticks.append(f'<span class="tick" style="left:{pos(d):.2f}%"></span>')
            if pos(d) >= 12:   # keep clear of the "Today" label
                labels.append(f'<span class="tick-label" style="left:{pos(d):.2f}%">{d:%b} 1</span>')
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    rows = []
    for p in status["periods"]:
        left, right = pos(p["start"]), pos(p["end"])
        when = f"starts in {p['starts_in']} days" if p["starts_in"] > 0 else "in effect now"
        tip = f"{p['name']}: {short_date(p['start'])} to {short_date(p['end'])}, {when}"
        rows.append(f'<div class="tl-row"><div class="tl-label">{esc(p["name"])}<span class="muted small">'
                    f'{esc(short_date(p["start"]))} – {esc(short_date(p["end"]))} · {esc(when)}</span></div>'
                    f'<div class="tl-track">{"".join(ticks)}<span class="tl-band" tabindex="0" '
                    f'style="left:{left:.2f}%;width:{max(right - left, 0.8):.2f}%" data-tip="{esc(tip)}"></span>'
                    f'</div></div>')
    for dl in status["deadlines"]:
        ship = (f"ship by {short_date(dl['ship_by'])}" if dl["ship_by"]
                else "ship-by date needs your carrier transit days")
        tip = f"{dl['event']}: arrive by {short_date(dl['arrive_by'])} ({dl['days_left']} days); {ship}"
        rows.append(f'<div class="tl-row"><div class="tl-label">{esc(dl["event"])}<span class="muted small">'
                    f'Arrive at Amazon by {esc(short_date(dl["arrive_by"]))} · {dl["days_left"]} days · {esc(ship)}'
                    f'</span></div><div class="tl-track">{"".join(ticks)}<span class="tl-dot" tabindex="0" '
                    f'style="left:{pos(dl["arrive_by"]):.2f}%" data-tip="{esc(tip)}"></span></div></div>')
    if not rows:
        return '<p class="empty">No upcoming fee periods or deadlines in the calendar.</p>'
    return (f'<div class="tl"><div class="tl-row tl-head"><div class="tl-label muted small">Next {TIMELINE_DAYS} days</div>'
            f'<div class="tl-track bare"><span class="today">Today {esc(short_date(today))}</span>'
            f'{"".join(labels)}</div></div>'
            f'{"".join(rows)}</div>')


def render_checklist(status: dict) -> str:
    items = []
    for s in status["setup"]:
        tone, icon, label = ("good", "✓", "Done") if s["ok"] else ("warning", "!", "Needed")
        items.append(f'<li><span class="dot t-{tone}" aria-hidden="true">{icon}</span><div>'
                     f'<b>{esc(s["label"])}</b> <span class="muted small">{label}</span>'
                     f'<div class="small muted">{esc(s["detail"])}</div></div></li>')
    return f'<ul class="checklist">{"".join(items)}</ul>'


def render_verdict_mix(verdicts: dict) -> str:
    total = sum(verdicts.values())
    if not total:
        return '<p class="empty">No checks yet. Run <code>/check</code> on a product and it shows up here.</p>'
    bar, legend = [], []
    for v in (BUY, CHECK_MANUALLY, WATCH, REJECT):
        n = verdicts.get(v, 0)
        tone, icon = VERDICT_TONE[v]
        legend.append(f'<li><span class="dot sm t-{tone}" aria-hidden="true">{icon}</span>{esc(v)} <b>{n}</b></li>')
        if n:
            share = n / total * 100
            inside = f'<span class="seg-label">{n}</span>' if share >= 8 else ""
            bar.append(f'<span class="seg t-{tone}" style="flex-basis:{share:.3f}%" tabindex="0" '
                       f'data-tip="{esc(v)}: {n} of {total} ({share:.0f}%)">{inside}</span>')
    return (f'<div class="split-bar status">{"".join(bar)}</div><ul class="legend">{"".join(legend)}</ul>')


def render_rejections(rejects: dict) -> str:
    if not rejects:
        return '<p class="empty">No rejections yet.</p>'
    peak = max(rejects.values())
    rows = []
    for key in ("1", "2", "3", "4", "stage"):
        n = rejects.get(key, 0)
        if key == "stage" and not n:
            continue
        width = n / peak * 100 if peak else 0
        rows.append(f'<div class="hbar"><span class="hbar-label">{esc(GATE_NAMES[key])}</span>'
                    f'<span class="hbar-track"><span class="hbar-fill" style="width:{width:.2f}%" tabindex="0" '
                    f'data-tip="{esc(GATE_NAMES[key])}: {n} rejected"></span><span class="hbar-value">{n}</span>'
                    f'</span></div>')
    return "".join(rows)


def render_checks_table(evs: list[dict]) -> str:
    if not evs:
        return '<p class="empty">Your checks will be listed here, newest first.</p>'
    rows = []
    for i, ev in enumerate(evs):
        m = ev["money"]
        profit = money(D(m["net_profit"])) if "net_profit" in m else "—"
        if "net_profit" in m and not m.get("complete", True):
            profit += "*"
        roi = pct(D(m["roi"]), 0) if "roi" in m else "—"
        rows.append(f'<tr class="pick" data-id="{ev["id"]}" tabindex="0" aria-selected="{str(i == 0).lower()}">'
                    f'<td class="num">{esc(short_date(ev["eval_date"]))}</td>'
                    f'<td><div class="cell-title">{esc(ev["title"] or "(untitled)")}</div>'
                    f'<div class="muted small">{esc(ev["store"])}</div></td>'
                    f'<td>{verdict_badge(ev["verdict"])}</td><td class="num">{esc(profit)}</td>'
                    f'<td class="num">{esc(roi)}</td></tr>')
    return (f'<div class="table-wrap"><table class="checks-table"><thead><tr><th>Date</th><th>Product</th>'
            f'<th>Verdict</th><th class="num">Profit/unit</th><th class="num">ROI</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>'
            f'<p class="note">* before UNVERIFIED costs. Select a row to see its gates and money.</p>')


def render_brands(conn) -> str:
    rows = conn.execute("SELECT * FROM brands WHERE active = 1 ORDER BY updated_at DESC").fetchall()
    if not rows:
        return ('<p class="empty">No brands recorded. When you check a brand in Seller Central, '
                '/check saves it here so you never check it twice.</p>')
    tone = {"open": ("good", "✓"), "ungated": ("good", "✓"), "gated": ("critical", "✕")}
    complaints = ' <span class="muted small">files complaints</span>'
    items = "".join(
        f'<li>{badge(*tone[r["status"]], r["status"])}<b>{esc(r["name"])}</b>'
        f'{complaints if r["complaints"] else ""}'
        f'<span class="muted small right">{esc(short_date(r["updated_at"][:10]))}</span></li>' for r in rows)
    return f'<ul class="brands">{items}</ul>'


# --- page -------------------------------------------------------------------

def build_html(settings: Settings, conn, today: dt.date, demo: bool = False) -> str:
    status = collect_status(settings, conn, today)
    evs = load_evaluations(conn)
    verdicts = counts(conn, "verdict")
    rejects = counts(conn, "failed_gate", "AND verdict = 'REJECT'")
    cap = status["capital"]
    total = sum(verdicts.values())

    fee = status["fees"][0] if status["fees"] else None
    fee_tile = ("Re-verify" if fee and fee["reasons"] else "Current") if fee else "—"
    kpis = [
        ("Per-product cap", money(status["per_product_cap"]), "20% of available capital"),
        ("Checks logged", f"{total:,}", f"{verdicts.get(BUY, 0)} BUY · {verdicts.get(WATCH, 0)} WATCH"),
        ("Fee data", fee_tile, f"checked {short_date(fee['retrieved'])}" if fee else ""),
    ]
    tiles = "".join(f'<div class="tile"><div class="tile-label">{esc(l)}</div><div class="tile-value">{esc(v)}'
                    f'</div><div class="muted small">{esc(s)}</div></div>' for l, v, s in kpis)
    attention = "".join(f"<li>{esc(a)}</li>" for a in status["attention"])
    templates = "".join(f'<template id="ev-{ev["id"]}">{render_detail(ev)}</template>' for ev in evs)
    first_detail = render_detail(evs[0]) if evs else (
        '<p class="empty">Run <code>/check</code> on a product. Its four gates and money breakdown appear here.</p>')
    banner = ('<div class="banner">Demo data: made-up example products, not your history. '
              'Your real dashboard is <code>dashboard.html</code>.</div>') if demo else ""
    generated = dt.datetime.now().strftime("%b %d, %Y %I:%M %p")

    body = f"""
{banner}
<header class="top">
  <div><h1>Sourcing dashboard</h1>
  <div class="muted small">{esc(status["location"])} · {esc(status["plan"].title())} plan · Stage {status["stage"]} · {esc(short_date(today))}, {today.year}</div></div>
</header>
<main class="grid">
  <section class="card span-12 kpis">
    <div class="hero"><div class="tile-label">Available to spend</div>
      <div class="hero-value">{esc(money(cap["available"]))}</div>
      <div class="muted small">{esc(money(cap["starting"]))} starting − {esc(money(cap["reserved"]))} reserved + {esc(money(cap["ledger_net"]))} logged</div></div>
    {tiles}
  </section>
  <section class="card span-8"><h2>Calendar</h2>{render_timeline(status)}</section>
  <section class="card span-4"><h2>To unlock BUY verdicts</h2>{render_checklist(status)}</section>
  <section class="card span-12" aria-live="polite"><h2>Selected check</h2><div id="detail">{first_detail}</div></section>
  <section class="card span-8"><h2>Recent checks</h2>{render_checks_table(evs)}</section>
  <section class="card span-4"><h2>Verdicts so far</h2>{render_verdict_mix(verdicts)}
    <h2 class="gap">Where rejections happen</h2>{render_rejections(rejects)}</section>
  <section class="card span-6"><h2>Brands you've checked</h2>{render_brands(conn)}</section>
  <section class="card span-6"><h2>Needs your attention</h2>{f'<ul class="attention">{attention}</ul>' if attention else '<p class="empty">Nothing right now.</p>'}</section>
</main>
<footer class="muted small">Built from data/sourcing.db on {esc(generated)}. This file stays on your PC.</footer>
{templates}
<div id="tip" role="tooltip" hidden></div>"""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Sourcing dashboard{" (demo)" if demo else ""}</title><style>{CSS}</style></head>'
            f'<body><div class="wrap">{body}</div><script>{JS}</script></body></html>')


def write_dashboard(settings: Settings, conn, today: dt.date, path: Path | None = None,
                    demo: bool = False) -> Path:
    path = Path(path or settings.root / (DEMO_FILE if demo else DASHBOARD_FILE))
    path.write_text(build_html(settings, conn, today, demo), encoding="utf-8")
    return path


def demo_data(settings: Settings, today: dt.date):
    """Example evaluations in a throwaway in-memory database, so the real
    history (which can never be deleted) is untouched."""
    demo = Settings(settings.root, copy.deepcopy(settings.config), settings.sources)
    demo.config["unverified_costs"]["inbound_shipping_per_lb"].update(
        value=0.50, source="demo value", retrieved=str(today))
    conn = db.connect(":memory:")
    db.set_brand(conn, "ExampleBrand", "open", note="demo")
    db.set_brand(conn, "GatedExample", "gated", note="demo")
    base = json.loads((settings.root / "examples" / "candidate.json").read_text(encoding="utf-8"))
    base["fields"]["category_size"] = {"value": 1_000_000, "source": "demo value", "retrieved": str(today)}

    def field(v):
        return {"value": v, "source": "demo value", "retrieved": str(today)}

    variants = [
        ("Example Toy Set", "Example Store", {}),
        ("Example Card Game", "Example Store", {"brand": field("UncheckedBrand")}),
        ("Example Puzzle", "Example Store", {"purchase_price": field(16.00)}),
        ("Example Board Game", "Example Outlet", {"amazon_on_listing": field(True)}),
        ("Example Building Blocks", "Example Outlet", {"sales_rank": field(40_000)}),
        ("Example Kite", "Example Store", {"current_price": field(12.99), "avg_price_90d": field(12.99)}),
        ("Example Doll", "Example Store", {"brand": field("GatedExample")}),
    ]
    for title, store, overrides in reversed(variants):
        data = copy.deepcopy(base)
        data["store"] = store
        data["fields"]["title"] = field(title)
        data["fields"].update(overrides)
        cand = Candidate.from_dict(data)
        ctx = EvalContext(demo, today, brand=db.get_brand(conn, cand.value("brand")),
                          capital_available=db.capital(conn, demo)["available"])
        ev = evaluate(cand, ctx)
        db.save_evaluation(conn, ev, to_record(ev))
    return demo, conn


CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--hover:rgba(11,11,11,.04);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--band:#2a78d6;
--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;--banner:#fff4d6}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--border:rgba(255,255,255,.10);--hover:rgba(255,255,255,.05);--s1:#3987e5;--s2:#d95926;--s3:#199e70;
--s4:#c98500;--band:#3987e5;--banner:#3a2f12}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink-2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--hover:rgba(255,255,255,.05);
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--band:#3987e5;--banner:#3a2f12}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 40px}
h1{font-size:22px;font-weight:650;margin:0 0 2px}
h2{font-size:13px;font-weight:600;color:var(--ink-2);margin:0 0 14px;text-transform:none}
h2.gap{margin-top:26px}
h3{font-size:13px;font-weight:600;margin:18px 0 8px}
code{font:13px ui-monospace,Consolas,monospace;background:var(--hover);padding:1px 5px;border-radius:4px}
.muted{color:var(--muted)}.small{font-size:12.5px}.right{margin-left:auto}
.top{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:16px}
.banner{background:var(--banner);border:1px solid var(--border);border-radius:10px;padding:10px 14px;margin-bottom:16px;font-size:14px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(12,minmax(0,1fr))}
.card{grid-column:span 12;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;min-width:0}
@media (min-width:920px){.span-8{grid-column:span 8}.span-6{grid-column:span 6}.span-4{grid-column:span 4}}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:18px 24px;align-items:end}
.hero{grid-column:span 2;min-width:0}
@media (max-width:520px){.hero{grid-column:1/-1}}
.hero-value{font-size:52px;font-weight:600;line-height:1.05;letter-spacing:-.01em;margin:4px 0}
.tile-label{font-size:13px;color:var(--ink-2)}
.tile-value{font-size:26px;font-weight:600;margin:4px 0 2px}
.empty{color:var(--muted);margin:4px 0}
.note{font-size:12.5px;color:var(--muted);margin:8px 0 0}
.badge{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;white-space:nowrap}
.dot{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;font-size:11px;font-weight:700;color:#0b0b0b;flex:none}
.dot.sm{width:15px;height:15px;font-size:9.5px}
.t-good{background:var(--good)}.t-warning{background:var(--warning)}.t-serious{background:var(--serious)}
.t-critical{background:var(--critical);color:#fff}.t-muted{background:var(--grid);color:var(--ink-2)}
.split{margin:0}.split figcaption{font-size:13px;color:var(--ink-2);margin-bottom:8px}
.split-bar{position:relative;display:flex;gap:2px;height:28px;background:var(--surface)}
.seg{display:flex;align-items:center;justify-content:center;min-width:3px;flex-grow:0;flex-shrink:1;outline-offset:2px}
.seg:first-child{border-radius:4px 0 0 4px}.seg:last-child{border-radius:0 4px 4px 0}.seg:only-child{border-radius:4px}
.seg-label{font-size:12px;font-weight:600;color:#0b0b0b;white-space:nowrap;padding:0 4px}
.s1{background:var(--s1)}.s1 .seg-label{color:#fff}.s2{background:var(--s2)}.s3{background:var(--s3)}.s4{background:var(--s4)}
.split-bar.status .seg.t-critical .seg-label{color:#fff}
.sale-mark{position:absolute;top:-5px;bottom:-5px;width:2px;background:var(--ink);transform:translateX(-1px)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;list-style:none;padding:0;margin:10px 0 0;font-size:13px;color:var(--ink-2)}
.legend li{display:flex;align-items:center;gap:6px}.legend b{color:var(--ink);font-weight:600}
.swatch{width:10px;height:10px;border-radius:3px;flex:none}
.money-table{margin-top:12px;font-size:13px}.money-table summary{cursor:pointer;color:var(--ink-2)}
table{border-collapse:collapse;width:100%}
td,th{padding:7px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{font-size:12.5px;font-weight:600;color:var(--ink-2)}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.total td{font-weight:600}
.table-wrap{overflow-x:auto}
.checks-table tr.pick{cursor:pointer}.checks-table tr.pick:hover{background:var(--hover)}
.checks-table tr.pick[aria-selected="true"]{background:var(--hover);box-shadow:inset 3px 0 0 var(--s1)}
.cell-title{font-weight:600}
.detail-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.detail-title{font-size:17px;font-weight:650}
.reason{margin:10px 0 4px;color:var(--ink-2)}
.plan{margin:4px 0 0}
.detail-grid{display:grid;gap:22px;margin-top:14px}
@media (min-width:920px){.detail-grid{grid-template-columns:1.1fr 1fr}}
.gate{border-top:1px solid var(--grid);padding:10px 0}.gate:first-child{border-top:0;padding-top:0}
.gate.skipped{opacity:.7}
.gate-head{display:flex;justify-content:space-between;gap:10px;font-weight:600;font-size:14px}
.checks{list-style:none;padding:0;margin:8px 0 0;display:grid;gap:6px;font-size:13px;color:var(--ink-2)}
.checks li{display:flex;gap:8px;align-items:flex-start}.checks b{color:var(--ink);font-weight:600}
.confirm{margin:0;padding-left:18px;font-size:13px;color:var(--ink-2);display:grid;gap:4px}
.checklist,.attention,.brands{list-style:none;padding:0;margin:0;display:grid;gap:12px}
.checklist li{display:flex;gap:10px;align-items:flex-start}
.attention{gap:8px;padding-left:18px;list-style:disc;color:var(--ink-2);font-size:14px}
.brands li{display:flex;gap:10px;align-items:center}
.tl{display:grid;gap:14px}
.tl-row{display:grid;grid-template-columns:minmax(150px,34%) 1fr;gap:14px;align-items:center}
@media (max-width:620px){.tl-row{grid-template-columns:1fr;gap:6px}}
.tl-label{font-weight:600;font-size:14px;display:flex;flex-direction:column}
.tl-track{position:relative;height:22px;border-left:1px solid var(--axis);border-bottom:1px solid var(--grid)}
.tl-track.bare{border:0;height:18px}
.tick{position:absolute;top:0;bottom:0;border-left:1px solid var(--grid)}
.tick-label{position:absolute;bottom:0;transform:translateX(-50%);font-size:12px;color:var(--muted);white-space:nowrap}
.today{position:absolute;left:0;bottom:0;font-size:12px;color:var(--muted);white-space:nowrap}
.tl-band{position:absolute;top:6px;height:10px;background:var(--band);border-radius:4px}
.tl-dot{position:absolute;top:50%;width:12px;height:12px;border-radius:50%;background:var(--ink);box-shadow:0 0 0 2px var(--surface);transform:translate(-50%,-50%)}
.tl-dot::before{content:"";position:absolute;inset:-8px}
.hbar{display:grid;grid-template-columns:minmax(120px,48%) 1fr;gap:10px;align-items:center;font-size:13px;margin:6px 0}
.hbar-label{color:var(--ink-2)}
.hbar-track{display:flex;align-items:center;gap:6px;height:16px}
.hbar-fill{height:16px;background:var(--s1);border-radius:0 4px 4px 0;min-width:2px}
.hbar-value{font-variant-numeric:tabular-nums;font-weight:600}
footer{margin-top:18px;text-align:center}
#tip{position:fixed;z-index:10;max-width:280px;background:var(--ink);color:var(--surface);font-size:12.5px;padding:6px 9px;border-radius:6px;pointer-events:none}
[tabindex]:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
"""

JS = """
(() => {
  const tip = document.getElementById('tip');
  const show = (el) => {
    tip.textContent = el.dataset.tip; tip.hidden = false;
    const r = el.getBoundingClientRect(), t = tip.getBoundingClientRect();
    let x = r.left + r.width / 2 - t.width / 2;
    x = Math.max(8, Math.min(x, innerWidth - t.width - 8));
    let y = r.top - t.height - 8; if (y < 8) y = r.bottom + 8;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  };
  const hide = () => { tip.hidden = true; };
  for (const type of ['mouseover', 'focusin']) document.addEventListener(type, (e) => {
    const el = e.target.closest && e.target.closest('[data-tip]'); if (el) show(el);
  });
  for (const type of ['mouseout', 'focusout']) document.addEventListener(type, (e) => {
    if (e.target.closest && e.target.closest('[data-tip]')) hide();
  });
  const detail = document.getElementById('detail');
  const select = (row) => {
    document.querySelectorAll('tr.pick').forEach((r) => r.setAttribute('aria-selected', String(r === row)));
    const tpl = document.getElementById('ev-' + row.dataset.id);
    if (tpl) { detail.replaceChildren(tpl.content.cloneNode(true)); }
  };
  document.querySelectorAll('tr.pick').forEach((row) => {
    row.addEventListener('click', () => select(row));
    row.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(row); } });
  });
})();
"""
