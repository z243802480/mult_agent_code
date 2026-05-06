# Real Model Acceptance

This document records the manual and scheduled acceptance workflow for real model providers.
It is intentionally separate from offline verification because it consumes paid provider calls.

## Suites

- `smoke`: one minimal file-creation loop.
- `core`: `file_smoke`, `password_cli`, and `markdown_kb`.
- `advanced`: failing-test repair plus decision-point handling.
- `nightly`: all real acceptance scenarios that are safe to run without user data.
- `offline`: fake-provider runner coverage only.

## Recommended Commands

Run a cheap provider health check first:

```powershell
python -m agent_runtime /model-check --root .
```

Run the minimum real-model loop:

```powershell
python scripts/real_model_smoke.py --summary-json .agent/verification/real_model_smoke.json
```

Run the current real-task acceptance set:

```powershell
python scripts/real_model_acceptance.py --suite core --summary-json .agent/verification/real_model_acceptance_core.json
```

Run the broader nightly set when budget allows:

```powershell
python scripts/real_model_acceptance.py --suite nightly --summary-json .agent/verification/real_model_acceptance_nightly.json
```

Persist a comparable history:

```powershell
python scripts/real_model_acceptance.py --suite core --summary-json .agent/verification/real_model_acceptance_core.json --history-jsonl .agent/verification/real_model_acceptance_history.jsonl
```

## Summary Metrics

`real_model_smoke.py` writes:

- `duration_seconds`
- `diagnostics.run_status`
- `diagnostics.review_status`
- `diagnostics.review_score`
- `diagnostics.task_status_counts`
- `diagnostics.model_calls`
- `diagnostics.tool_calls`
- `diagnostics.estimated_input_tokens`
- `diagnostics.estimated_output_tokens`
- `diagnostics.repair_attempts`
- `diagnostics.context_compactions`

`real_model_acceptance.py` aggregates the same cost and stability counters across scenarios.
When `--history-jsonl` is provided, the script appends each summary to a JSONL history and adds
`trend.previous` plus numeric deltas for pass/fail counts, duration, model/tool calls, token estimates,
repair attempts, and context compactions. Runtime `agent /acceptance` writes this history by default
to `.agent/acceptance/history.jsonl`.

Inspect runtime workspace history:

```powershell
python -m agent_runtime /acceptance-history --root . --limit 5
```

Inspect a custom script-level history file:

```powershell
python -m agent_runtime /acceptance-history --root . --history-jsonl .agent/verification/real_model_acceptance_history.jsonl
```

Use trend warnings as a local gate:

```powershell
python -m agent_runtime /acceptance-history --root . --suite nightly --fail-on-warning
```

Run acceptance and fail the same command on trend warnings:

```powershell
python -m agent_runtime /acceptance --root . --suite core --fail-on-trend-warning
```

The warning thresholds are configurable:

```powershell
python -m agent_runtime /acceptance-history --root . --warn-model-call-delta 5 --warn-duration-delta 120 --warn-repair-delta 1 --fail-on-warning
python -m agent_runtime /acceptance --root . --suite core --warn-model-call-delta 5 --warn-duration-delta 120 --warn-repair-delta 1 --fail-on-trend-warning
```

## Pass Criteria

A scenario should pass only when:

- `/model-check` succeeds.
- the expected artifact exists and contains the expected text.
- required run artifacts are present and non-empty.
- `run.json` status is `completed`.
- `eval_report.json` overall status is `pass`.
- active tasks are done; discarded tasks are allowed only as superseded repair history.
- cost counters match JSONL logs.

Failures should be promoted through `agent /acceptance --promote-failures` rather than ignored.
