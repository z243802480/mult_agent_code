# Product-path dogfood inputs

`ledger_long_task/` is an intentionally defective seed project, not runtime implementation.
Copy it to an isolated workspace before invoking the ordinary goal workflow. Its original
31 tests should fail before the repair. Keep tests and requirements unchanged while the
model works; do not run this seed suite as a product regression check.

`followup_test.py.txt` is held out of the initial task. Copy it to `tests/test_followup.py`
only when issuing the separate merge/export request. The actual S106 follow-up requirement
and the independent monthly-aggregation counterexample are recorded in the S106 report.
Provider credentials, generated solutions and runtime ledgers are never part of these inputs.

`boardkit_goal/` is the S107 complete-product seed with 53 frozen acceptance cases.
`boardkit_oracle.py.txt` is its independent requirement oracle, stored outside the seed;
do not copy it into the model workspace. Run it from the finished workspace with that
workspace on PYTHONPATH. It is an evaluation fixture, not a runtime/maintainer command.

`tool_batch_oracle.py.txt` freezes S108 behavioral checks against the real repository.
Keep it outside autonomous repair workspaces; normal CI reuses it through a unit-test wrapper.

`tool_batch_runtime_oracle.py.txt` is the S109 extension of the frozen batch oracle,
including the actual runtime wrapper and persisted adapter/alias evidence. It also stays
outside the model workspace; it is an evaluation fixture, not a new runtime command.
