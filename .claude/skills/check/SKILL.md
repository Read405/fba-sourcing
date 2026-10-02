---
name: check
description: Evaluate one product the owner is looking at (in a store, at a sale, or online) and return BUY, CHECK MANUALLY, WATCH or REJECT with the full breakdown. Use when the owner gives a product and a price to check.
---

# /check

Fast manual entry. The owner gives the source type and numbers; you gather the
listing data; the code decides.

1. **Get from the owner** (ask only for what's missing):
   - source type (`retail_store` or `retail_online`; others aren't built yet) and the store
   - purchase price per unit; for online, also shipping total, units in the order, and delivery days
   - the product: ASIN, UPC or exact title, plus anything printed on the package
     (UPC, model, size, count) for the exact-match check
   - optional: tax from the receipt, a store membership share

   If the store isn't in `sources.yaml` under `stores`, add it under the right type.

2. **Fill every field** from `python -m sourcing template --source-type <type>`
   (meanings are in `FIELD_GUIDE` in `sourcing/gates.py`):
   - Use web search and single public page fetches. Record each value as
     `{"value": ..., "source": "<URL>", "retrieved": "<today>"}`.
   - Values the owner reads off their own screen or package (Amazon Seller app,
     Keepa chart, box) use `"source": "user: <what they looked at>"`.
   - If you can't verify a value, write `{"unverified": true, "note": "<why, and what to check>"}`.
     Never guess. Never fill from memory.
   - `fee_category` must match a category name in `data/fees/amazon_us.yaml` exactly.
   - `avg_price_90d` and `seasonality` usually need Keepa. Without `KEEPA_API_KEY`,
     ask the owner to read them off Keepa's free chart, or leave them UNVERIFIED.
   - `exact_match`: compare UPC, model, size, color, edition and pack count with
     the listing. Use `"n/a"` only when the attribute doesn't exist for the
     product, and say what you compared in `note`.

3. **Save** the candidate as `work/<YYYY-MM-DD>-<short-name>.json`.

4. **Run** `.venv/Scripts/python -m sourcing check work/<file>.json`
   (`.venv/bin/python` on macOS or Linux).

5. **Report** the output. Lead with the verdict and its reason, then the money
   lines, then "To confirm before buying". Never change or soften the verdict.

6. When the owner confirms a brand's status in Seller Central, record it with
   `python -m sourcing brand set "<Brand>" open|ungated|gated` (add
   `--complaints yes` for brands that file complaints), then re-run the check.
