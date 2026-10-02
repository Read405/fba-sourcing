# fba-sourcing

A reusable sourcing system for reselling products, starting with Amazon FBA.
It evaluates a product from any source through four gates (can I sell it, will
it sell, will I make money, what can go wrong) and returns BUY, CHECK
MANUALLY, WATCH or REJECT, with every number tied to a source and a date.

The full specification is [docs/brief.md](docs/brief.md). Standing rules for
Claude are in [CLAUDE.md](CLAUDE.md).

## Status

Phase 1 is done: config, Amazon US fee data (verified 2026-10-02 from Amazon's
official pages), the evaluator with source and channel plug-ins, tests, and
`/check` for retail stores and retail websites.

## Use it

In Claude Code, from this folder:

- `/start` runs the start-of-session routine: fee freshness, seller calendar, stage and capital.
- `/check` evaluates a product you're looking at.

Or directly:

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m sourcing start
.venv/Scripts/python -m sourcing check examples/candidate.json --no-save
.venv/Scripts/python -m pytest
```

## Layout

| Path | What it holds |
|---|---|
| `config.yaml` | Your thresholds, stages, locations, and costs still to verify |
| `sources.yaml` | Source types and stores |
| `data/fees/amazon_us.yaml` | Amazon fees with source URLs and dates |
| `data/calendar/amazon_us.yaml` | Peak fee windows and inbound deadlines |
| `sourcing/` | The evaluator: gates, source plug-ins, channel plug-ins, SQLite history |
| `tests/` | Profit math, every gate, verdict rules, and Amazon's own fee examples |

Your evaluation history, purchases and sales stay in `data/sourcing.db` on your
machine; it is never committed.
