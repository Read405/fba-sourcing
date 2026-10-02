# Goal

Build me a reusable sourcing system for reselling products, starting with
Amazon FBA. It must work for any place I can buy inventory and keep working as
my capital, experience, and selling channels grow. In every session your most
important job is finding products that are genuinely correct buys. The rest of
the system exists so that job gets more accurate over time.

# Why accuracy matters more than volume

I'm starting with small capital, so one bad pick is a meaningful share of my
money. Passing on a good product costs nothing; approving a bad one costs cash.
When you're unsure, reject or flag. Never lower a threshold to pad a list. If
only three products pass, give me three and say so.

# Design principles

- Source-agnostic: where I buy is a plug-in. The evaluator never assumes a
  particular store or site.
- Channel-agnostic: where I sell is also a plug-in. Build Amazon FBA first, but
  keep fees and eligibility rules behind an interface so other channels can be
  added without rewriting the evaluator.
- Date-agnostic: no dates, seasons, or events in code. Look them up each
  session.
- Config over code: my situation, thresholds, and limits live in config files.
- History is permanent: store everything in SQLite and never delete records;
  mark them inactive instead.

# Persistence

- Write the standing rules in this prompt into CLAUDE.md so future sessions
  follow them without me pasting this again.
- Create reusable custom commands for the workflows below, using whatever
  mechanism your current version supports.

# Source types

Keep a sources registry (sources.yaml). No store, site, or category is excluded
by default. If I mention a place that isn't in the registry, add it under the
right type instead of refusing. Each type defines its default item condition,
what proof of purchase it provides, its extra costs, its typical lead time, and
any extra checks.

1. retail_store: any physical retailer. Big box, grocery, pharmacy, hardware,
   dollar stores, warehouse clubs, outlets, clearance and closing sales.
   Condition new, receipt as proof.
2. retail_online: any retailer or brand website and deal sites. Condition new,
   order confirmation as proof. Add shipping cost and delivery time.
3. secondhand: thrift stores, garage and estate sales, library sales, local
   marketplace listings. Condition used unless factory sealed, usually no proof
   of purchase. Requires a condition grade.
4. liquidation: pallets, auction lots, customer returns, shelf pulls,
   closeouts. Evaluated at the lot level (see below). Add buyer's premium and
   freight.
5. marketplace_flip: buying on one marketplace to sell on another. Add the
   seller's shipping and note the return policy.
6. wholesale: distributors and brands. Invoices as proof, minimum order
   quantities, usually requires a resale certificate.

# Configuration

Put these in config.yaml with these starting values, and ask me to confirm them
on first run:

- capital_total: 500
- reserved costs: seller plan 39.99 per month, shipping and supplies 40
- locations: Norman, Oklahoma (active). Let me save more than one and switch
  the active one. Look up each sales tax rate and store it with its source.
- max_days_to_my_door: 5
- min_profit_per_unit: 4.00
- min_roi: 0.40
- sale_price_range: 15 to 50
- max_weight_lb: 2
- allow_oversize: false
- allow_hazmat: false
- max_rank_percentile: 2
- max_fba_offers_near_buybox: 20, within a 2% price band
- price_spike_tolerance: 15% above the 90-day average
- min_expiry_months: 6
- units_per_product: 3 to 5
- max_budget_share_per_product: 20%
- prep_cost_per_unit: 0.15
- lot_unsellable_haircut: 30%

Thresholds only change when I approve it. You can propose changes with
evidence, but never adjust them on your own.

# Growth stages

Keep a stages section in config. Each stage sets which source types are
enabled and the purchase limits. Starting values:

- Stage 1, capital under 1,000: retail_store, retail_online, secondhand.
- Stage 2, capital 1,000 to 3,000 and at least two profitable review cycles:
  adds liquidation and marketplace_flip.
- Stage 3, capital over 3,000 with consistent profit: adds wholesale.

Compute my current capital from logged purchases and payouts, not from the
number I typed in on day one. Tell me when my results qualify me for the next
stage, but never move me up without my approval. When a stage or source needs
something I may not have, such as a resale certificate or a business entity,
flag it and tell me to confirm the requirements myself. Private label is out of
scope; don't build for it.

# Session routine

At the start of every session:
1. Read the config files and get today's date from the system.
2. Check the age of the fee data. If it's over 30 days old, or a new year or
   peak period has started, re-verify it against official fee pages.
3. Look up the current seller calendar for each active channel: upcoming
   inbound deadlines, peak fee windows, storage rates. Save it with sources and
   work backward to a buy-by date and a ship-by date. If a deadline can't
   realistically be met, say so.
4. Show a short status: stage, available capital, inventory, watchlist, and
   anything that needs my attention.

# Data rules

- Every number needs a source URL and retrieval date. Never fill in a value
  from memory or by estimating.
- If you can't verify a value, record it as UNVERIFIED. A product with any
  UNVERIFIED required field can't be rated BUY.
- Use web search and fetching of public pages. If a KEEPA_API_KEY environment
  variable exists, use the Keepa API for price history, rank history, and offer
  counts.
- Don't build scrapers that hit any marketplace at volume or try to get around
  bot detection. When you can't get a value, add it to a list for me to check.
- Never ask for or handle my logins. I'll download reports myself and drop the
  CSV files in an imports/ folder.

# The four gates

Evaluate every candidate in this order and stop at the first failure.

## Gate 1: Can I sell it?
- Check brand memory first. Skip brands I've confirmed I can't sell.
- For unknown brands, flag ones commonly restricted for new sellers as LIKELY
  GATED. Final eligibility is always my manual check.
- Condition: confirm the category allows the condition I'd list it in. Many
  categories don't allow used items.
- Proof of purchase: if the source gives none, flag brands known for
  authenticity complaints as high risk.
- Apply allow_hazmat and min_expiry_months.

## Gate 2: Will it sell?
- Sales rank within max_rank_percentile of its top-level category. Report rank,
  category, and percentile.
- Record the "bought in past month" figure when shown.
- For used items, also record how many used offers exist and at what prices.
- Label each product YEAR-ROUND or SEASONAL, naming the season and the date
  demand drops off.

## Gate 3: Will I make money?
- Landed cost per unit = purchase price + sales tax + every source-specific
  cost (shipping to me, buyer's premium, freight, membership share).
- Sale price used = the lower of the current price and the 90-day average, for
  the condition I'd list in. A used item is priced against used offers, never
  the new Buy Box. Reject if the current price exceeds the 90-day average by
  more than price_spike_tolerance.
- Net profit per unit = sale price - channel fees (including any peak
  surcharge in effect when it would sell) - inbound shipping - prep cost
  - landed cost.
- ROI = net profit / landed cost.
- Must meet the profit, ROI, price range, weight, and size settings in config.

## Gate 4: What can go wrong?
- Reject if Amazon itself is a seller on the listing.
- Reject if the only seller is the brand owner.
- Reject if FBA offers near the Buy Box exceed the configured limit.
- Exact match: UPC, model number, size, color, edition, and pack count must
  match the listing. State what you compared.
- Flag high-return categories and anything fragile.

# Lot evaluation

For liquidation lots and any bundle purchase:
- Require a manifest. Reject unmanifested lots.
- Run each manifest line through the gates. Only items that pass count toward
  the lot's value.
- Reduce the expected value by lot_unsellable_haircut for damaged and missing
  units.
- Include buyer's premium, freight, and my time to sort and prep.
- Give one verdict for the whole lot, with best-case, expected, and worst-case
  profit.

# Verdicts

- BUY: passed all four gates with every required field verified.
- CHECK MANUALLY: passed everything you could verify; list exactly what I need
  to confirm.
- WATCH: failed only on price or profit. Record the landed cost at which it
  becomes a BUY.
- REJECT: failed a gate. Record which one and why.

# Workflows

1. source: find candidates from enabled source types, run the gates, and write
   a ranked shortlist plus a purchase plan that fits available capital.
2. check: fast manual entry for when I'm standing in any store, sale, or
   looking at any listing. I give the source type and numbers; you return a
   verdict with the full breakdown.
3. lot: evaluate a manifest.
4. recheck: re-verify shortlist items right before I spend money, and re-test
   the watchlist for price drops.
5. buy, ship, import: log purchases, shipments, and sales reports.
6. status: stage, capital available and tied up, inventory, realized profit,
   aging stock.
7. review: compare predictions to reality (below).
8. replen: products that sold through quickly at or above predicted profit,
   rechecked at today's prices.
9. scout: based on past hit rates, tell me which source types, stores, and
   categories are worth my time near my active location.
10. add-source: register a new store, site, or source type.

# Things the system should remember

- Brand memory: for each brand I check, whether it's open, gated, or ungated
  for my account, and any brand that sends complaints to resellers.
- Evaluation snapshots: every evaluation with its date, source, and channel.
- Hit rates: pass and rejection counts by source type, store, category, and
  gate, so effort goes where results are best.

# The review loop

For each product I've sold, compare predicted versus actual sale price, fees,
net profit, ROI, and days to sell. Then tell me:
- Where predictions were consistently off, and by how much.
- Which source types, stores, and categories actually made money.
- Any threshold or stage change you'd propose, with the evidence.
- Stale inventory, with the break-even price for each item.

Keep an export of purchases, costs, fees, and sales I can hand to whoever does
my taxes.

# Build order

Work in phases. Stop after each one, show me what you built, and don't start
the next until I ask:
1. Config, fee data, CLAUDE.md, the evaluator with source and channel
   interfaces, unit tests on the profit math and each gate, and check.
   Implement retail_store, retail_online, and Amazon FBA.
2. source, recheck, add-source, and the secondhand source type.
3. buy, ship, import, and status.
4. review, replen, scout, watchlist, and the tax export.
5. Lot evaluation, liquidation, and marketplace_flip.
6. Additional selling channels and wholesale. When a product fails only on
   Amazon eligibility, check whether another channel would pass.

Before writing any code, ask me whatever you need and show me your plan.
