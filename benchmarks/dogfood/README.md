# Product-path dogfood inputs

`ledger_long_task/` is an intentionally defective seed project, not runtime implementation.
Copy it to an isolated workspace before invoking the ordinary goal workflow. Its original
31 tests should fail before the repair. Keep tests and requirements unchanged while the
model works; do not run this seed suite as a product regression check.

`followup_test.py.txt` is held out of the initial task. Copy it to `tests/test_followup.py`
only when issuing the separate merge/export request. The actual S106 follow-up requirement
and the independent monthly-aggregation counterexample are recorded in the S106 report.
Provider credentials, generated solutions and runtime ledgers are never part of these inputs.
