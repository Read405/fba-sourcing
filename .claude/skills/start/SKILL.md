---
name: start
description: Start-of-session routine for the sourcing system. Checks fee data freshness, refreshes the seller calendar, and shows stage, capital and anything that needs attention. Run at the beginning of every session.
---

# /start

1. Run `.venv/Scripts/python -m sourcing start` (`.venv/bin/python` on macOS or
   Linux). It uses the system date.

2. If the fee data says **RE-VERIFY**, open each `source` URL in
   `data/fees/amazon_us.yaml`. Seller Central help pages render in the built-in
   browser without signing in. Compare every number, then update values and
   `retrieved` dates. Also check the fee change summary page for new rate cards,
   such as next year's rates or a new peak period. Run the tests afterward:
   Amazon's worked examples in `tests/test_amazon_fees.py` must still pass, or
   be updated from Amazon's new examples.

3. Refresh `data/calendar/amazon_us.yaml`: search Seller Central announcements
   for upcoming inbound deadlines, peak fee windows and storage-rate changes,
   and record each one with its source URL.

4. Re-run `start` and show the owner the status. Call out any deadline that
   can't realistically be met.
