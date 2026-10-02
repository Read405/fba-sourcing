# CLAUDE.md

Sourcing system for reselling, Amazon FBA first. The full spec is
[docs/brief.md](docs/brief.md); this file holds the standing rules for every session.

## The most important job

Find products that are genuinely correct buys. Accuracy beats volume: the owner
starts with small capital, so a bad pick costs real money and a missed good pick
costs nothing. When unsure, reject or flag. Never lower a threshold to pad a
list. If only three products pass, report three and say so.

## Hard rules

- Every number needs a source URL (or `user: <what they looked at>`) and a
  retrieval date. Never fill a value from memory or by estimating.
- If a value can't be verified, record it as UNVERIFIED. Any UNVERIFIED required
  field rules out BUY. The code enforces this; don't work around it.
- Verdicts come from `python -m sourcing check`, never from your own judgment.
  Report the verdict the tool printed, unchanged.
- Thresholds, `assumptions` and the current stage in config.yaml change only with
  the owner's approval. Propose changes with evidence; never edit them yourself.
- No dates, seasons or events in code. They live in `data/` and are looked up
  each session.
- History is permanent: never delete rows from `data/sourcing.db` (triggers block
  it); set `active = 0` instead.
- Use web search and single public page fetches. No scrapers that hit a
  marketplace at volume, nothing that gets around bot detection. When a value
  can't be had, put it on the to-confirm list for the owner.
- If `KEEPA_API_KEY` is set, use the Keepa API for price history, rank history and
  offer counts. (Not built yet; the owner plans to subscribe.)
- Never ask for or handle the owner's logins. The owner downloads reports and
  drops CSV files in `imports/`.
- When a stage or source needs something the owner may not have (resale
  certificate, business entity), flag it and tell the owner to confirm the
  requirements themselves. Never move the owner to a new stage without approval.
- Private label is out of scope.

## Session routine (`/start`)

1. Read config.yaml and sources.yaml; take today's date from the system.
2. If `python -m sourcing start` says the fee data needs re-verifying (over 30
   days old, a new year, or a peak period started), re-check every number in
   `data/fees/amazon_us.yaml` against the official pages listed there and update
   values, sources and `retrieved` dates. Seller Central help pages load in the
   built-in browser without signing in.
3. Look up the seller calendar for each active channel (inbound deadlines, peak
   fee windows, storage rates), save it with sources in `data/calendar/`, and
   work back to buy-by and ship-by dates. Say so if a deadline can't
   realistically be met.
4. Show a short status: stage, available capital, inventory, watchlist, and
   anything that needs attention.

## Owner facts (as of 2026-10-02)

- Individual selling plan: $0.99 per item sold, no monthly fee. Since September
  2026 every seller is eligible for the Featured Offer (Buy Box).
- Active location: Norman, Oklahoma, 8.75% sales tax (sourced in config.yaml).
- Stage 1. No Keepa key yet.
- `inbound_shipping_per_lb` and `inbound_transit_days` stay UNVERIFIED until the
  owner reads them off a Send to Amazon shipment. Until then nothing can be BUY.

## Code layout

- `sourcing/gates.py`: the four gates. `evaluator.py`: gate order and verdicts.
- `sourcing/sources/`: where you buy (plug-ins). `sourcing/channels/`: where you
  sell (fees, eligibility, listing risks). Gates only talk to these interfaces.
- `sourcing/db.py`: SQLite history. `report.py`: text output. `session.py`: `/start` status.
- New source type: a class in `sourcing/sources/`, registered in
  `sources/__init__.py`, plus an entry in sources.yaml. New channel: a class in
  `sourcing/channels/`, its fee data file, and a `paths` entry in config.yaml.
  The evaluator and gates don't change for either.
- Run: `.venv/Scripts/python -m sourcing check|template|brand|start` on Windows
  (`.venv/bin/python` elsewhere). Setup: `python -m venv .venv`, then
  `pip install -r requirements.txt`.
- Tests: `.venv/Scripts/python -m pytest`. Fee tests use Amazon's own worked
  examples; when fee data changes, update expectations only from Amazon's new
  examples.

## Build status

Phase 1 is done: config, fee data, evaluator with source and channel interfaces,
tests, and `/check` for retail_store, retail_online and Amazon FBA.

Later phases, started only when the owner asks, stopping after each to show the work:
2. source, recheck, add-source, secondhand
3. buy, ship, import, status
4. review, replen, scout, watchlist, tax export
5. lot evaluation, liquidation, marketplace_flip
6. more selling channels, wholesale
