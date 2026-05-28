# Runtime Validation Matrix and Recovery Pressure Notes

Updated: 2026-05-28

This note records the current implementation boundary for real-task validation and recovery pressure evidence.

## Fixed Real-Task Validation Matrix

The fixed real-task validation catalog lives at `benchmarks/runtime_validation_matrix.json` and is consumed by:

- `gate-status` through `runtime_validation_matrix`
- `validation-run` through `evidence.runtime_validation_matrix`

The catalog currently gates the following evidence:

- ModelToolSurface contract validation.
- Skill adapter invocation with capability decision reason.
- MCP adapter invocation with capability decision reason.
- Research, Brainstorm, and Multi-agent profile coverage.
- Permission reason coverage.
- Runtime-native `user_progress.jsonl` coverage.
- Agent-facing tool surface evidence from the Plan/Run/Worker loop.

The catalog deliberately ignores untracked local `.codex/`, `.claude/`, `validation_*`, transcript, and probe folders. Those remain local scratch evidence unless promoted into structured runtime artifacts.

## Progress Timeline Boundary

CLI and Studio should default to `user_progress.jsonl` for the user-facing progress timeline. Raw evidence such as legacy `events.jsonl`, `tool_observations.jsonl`, `mcp_invocations.jsonl`, `skill_invocations.jsonl`, provider routes, and schema refs remain Inspector/debug evidence.

The validation catalog keeps this boundary visible by requiring runtime-native progress coverage before a workspace is considered covered by real-task evidence.

## Recovery Pressure Report

`recovery_pressure_report()` scans durable runtime evidence and summarizes whether these recovery chains have been exercised:

- resume
- replan
- repair
- damaged memory recovery
- multi-run conflict
- permission block recovery

The report is consumed by:

- `gate-status` through `recovery_pressure`
- `validation-run` through `evidence.recovery_pressure`

The report is intentionally evidence-based: it scans run-local `user_progress.jsonl`, `decisions.jsonl`, `runtime_requests.jsonl`, `task_failures.jsonl`, `task_plan.json`, plus `.asteria/memory/active_goal.json` for damaged memory and cross-run conflict recovery.

## Next Engineering Use

Before adding new real-task cases, maintainers should inspect:

- `gate-status --json` fields `runtime_validation_matrix`, `runtime_progress_metrics`, and `recovery_pressure`.
- `.asteria/validation_runs/<id>/summary.json` fields under `evidence`.
- Studio Inspector raw evidence only when a user-facing progress item needs deeper debugging.

The next engineering plan is not to create another matrix or deployment taxonomy. It is to feed this catalog with fresh real-provider runs, then make gate output distinguish implementation gaps, evidence gaps, and route-health gaps.
