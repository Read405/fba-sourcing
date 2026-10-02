"""Command line: python -m sourcing <command>."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import webbrowser
from pathlib import Path

from . import db
from .channels import ChannelNotAvailable
from .config import load
from .core import Candidate, EvalContext
from .dashboard import demo_data, write_dashboard
from .evaluator import evaluate
from .gates import FIELD_GUIDE, ONLINE_FIELDS, OPTIONAL_FIELDS
from .report import format_evaluation, to_record
from .session import session_status
from .sources import SourceNotAvailable


def _date(value: str | None) -> dt.date:
    return dt.date.fromisoformat(value) if value else dt.date.today()


def cmd_check(args, settings) -> int:
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    cand = Candidate.from_dict(data)
    conn = db.connect(":memory:" if args.no_save else settings.db_path)
    ctx = EvalContext(settings, _date(args.date), brand=db.get_brand(conn, cand.value("brand")),
                      capital_available=db.capital(conn, settings)["available"])
    try:
        ev = evaluate(cand, ctx)
    except (SourceNotAvailable, ChannelNotAvailable) as e:
        print(f"Can't evaluate: {e}")
        return 2
    record = to_record(ev)
    if args.json:
        print(json.dumps(record, indent=2, default=str))
    else:
        print(format_evaluation(ev))
    if not args.no_save:
        print(f"\nSaved as evaluation #{db.save_evaluation(conn, ev, record)}.")
        _refresh(settings, conn, ctx.eval_date)
    return 0


def _refresh(settings, conn, today: dt.date) -> None:
    """Keep dashboard.html current after anything that changes the history."""
    path = write_dashboard(settings, conn, today)
    print(f"Dashboard updated: {path.name}")


def cmd_dashboard(args, settings) -> int:
    today = _date(args.date)
    if args.demo:
        settings, conn = demo_data(settings, today)
        path = write_dashboard(settings, conn, today, demo=True)
    else:
        path = write_dashboard(settings, db.connect(settings.db_path), today)
    print(f"Dashboard written: {path}")
    if args.open:
        webbrowser.open(path.resolve().as_uri())
    return 0


def cmd_template(args, settings) -> int:
    online = args.source_type == "retail_online"
    fields = {}
    for name, hint in FIELD_GUIDE.items():
        if name in ONLINE_FIELDS and not online:
            continue
        fields[name] = {"unverified": True, "note": ("optional: " if name in OPTIONAL_FIELDS else "") + hint}
    template = {"source_type": args.source_type, "store": "", "channel": "amazon_fba",
                "condition": "new", "fields": fields}
    print(json.dumps(template, indent=2))
    return 0


def cmd_brand(args, settings) -> int:
    conn = db.connect(settings.db_path)
    if args.brand_cmd == "set":
        complaints = None if args.complaints is None else args.complaints == "yes"
        row = db.set_brand(conn, args.name, args.status, complaints, args.note, args.source)
    else:
        row = db.get_brand(conn, args.name)
        if row is None:
            print(f"{args.name}: not recorded. Check it in Seller Central, then run: brand set \"{args.name}\" <status>")
            return 0
    complaints = "files complaints" if row["complaints"] else "no complaints recorded"
    print(f"{row['name']}: {row['status']} ({complaints}), updated {row['updated_at'][:10]}"
          + (f". Note: {row['note']}" if row["note"] else ""))
    if args.brand_cmd == "set":
        _refresh(settings, conn, dt.date.today())
    return 0


def cmd_start(args, settings) -> int:
    conn, today = db.connect(settings.db_path), _date(args.date)
    print(session_status(settings, conn, today))
    _refresh(settings, conn, today)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(prog="python -m sourcing")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="evaluate one candidate JSON file")
    check.add_argument("file")
    check.add_argument("--date", help="evaluation date YYYY-MM-DD (default: today)")
    check.add_argument("--no-save", action="store_true", help="don't record the evaluation")
    check.add_argument("--json", action="store_true", help="print the result as JSON")

    template = sub.add_parser("template", help="print a blank candidate file")
    template.add_argument("--source-type", default="retail_store")

    brand = sub.add_parser("brand", help="brand memory")
    brand_sub = brand.add_subparsers(dest="brand_cmd", required=True)
    brand_set = brand_sub.add_parser("set")
    brand_set.add_argument("name")
    brand_set.add_argument("status", choices=db.BRAND_STATUSES)
    brand_set.add_argument("--complaints", choices=["yes", "no"])
    brand_set.add_argument("--note")
    brand_set.add_argument("--source", default="user")
    brand_show = brand_sub.add_parser("show")
    brand_show.add_argument("name")

    start = sub.add_parser("start", help="start-of-session status")
    start.add_argument("--date", help="today's date YYYY-MM-DD (default: system date)")

    dash = sub.add_parser("dashboard", help="write dashboard.html from your history")
    dash.add_argument("--date", help="today's date YYYY-MM-DD (default: system date)")
    dash.add_argument("--open", action="store_true", help="open it in your browser")
    dash.add_argument("--demo", action="store_true",
                      help="write dashboard-demo.html from made-up examples (your history is untouched)")

    args = parser.parse_args(argv)
    settings = load()
    handler = {"check": cmd_check, "template": cmd_template, "brand": cmd_brand, "start": cmd_start,
               "dashboard": cmd_dashboard}[args.cmd]
    return handler(args, settings)
