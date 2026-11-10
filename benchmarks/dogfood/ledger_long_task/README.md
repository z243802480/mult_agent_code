# LedgerKit repair exercise

An existing dependency-free CSV ledger needs repairs, followed by a separate feature request.
Run `python -m pytest tests/test_ledger.py -q` from this directory. The tests are immutable.

Repair requirements:
1. CSV import accepts a UTF-8 BOM, trims header names and surrounding field whitespace, preserves quoted commas, and requires id/account/kind/amount/currency/date.
2. An id and account must be nonempty. kind is income or expense. Amount is a finite positive Decimal with at most two fractional digits; no float rounding. Currency is a three-letter uppercase ASCII code. Dates are real ISO YYYY-MM-DD dates. Reject duplicate ids with a ValueError that identifies the duplicate.
3. Account/currency totals add income and subtract expense, quantize to two decimal places, and sort deterministically. Never mix currencies or mutate entries.
4. Date filtering is inclusive, supports either bound, and rejects inverted ranges. Category filtering uses the kind field.
5. Monthly totals group by YYYY-MM and currency, keep accounts together within a currency, and sort by month then currency.
6. CLI `python -m ledgerkit INPUT --start DATE --end DATE --kind income|expense --format json|csv` defaults to JSON account totals. JSON amounts are decimal strings. CSV has exactly account,currency,total columns. Invalid input exits 2 with a useful stderr diagnostic and no traceback. `--monthly` selects month,currency,total output.
7. Modify existing ledgerkit/*.py only, retain public function signatures and do not alter tests. Do not add dependencies or unrelated APIs. Verify the complete original suite after related changes.

The separate follow-up is not part of this repair goal and will be provided only after the first run.
