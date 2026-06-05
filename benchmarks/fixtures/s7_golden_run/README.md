# S7 golden run fixture

`user_progress.jsonl` models a complete harness progress contract for run-scoped
`studio-benchmark --run-id s7-golden-run`.

Use in CI via `tests/integration/test_s7_golden_benchmark.py`; do not treat dirty
workspace-wide benchmark scores as S7 pass/fail.
