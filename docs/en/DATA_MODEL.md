# Multi-Agent Autonomous Development System - Data Model

The Chinese `docs/zh/DATA_MODEL.md` is the detailed source of truth. This file is the English summary for review.

## Core Objects

- `ProjectConfig`: project metadata in `.agent/project.json`.
- `PolicyConfig`: budget, security, model routing, and decision policy in `.agent/policies.json`.
- `Session`: the user-facing recoverable context for one goal. It currently maps to one
  internal `Run` id.
- `Run`: one internal execution record in `.agent/runs/<run_id>/run.json`.
- `GoalSpec`: structured user goal.
- `Task`: schedulable work item.
- `TaskPlanEval`: deterministic task-plan quality report for granularity, dependencies,
  acceptance, artifacts, and tooling.
- `DecisionPoint`: user-facing major branch decision. Options may include an `action`
  (`create_task`, `record_constraint`, `cancel_scope`, or `require_replan`) so the runtime
  can resume without guessing from labels.
- `ContextSnapshot`: compact state for long-task continuation.
- `CommandRun`: one command workflow execution.
- `ToolCall`: structured tool execution log.
- `ModelCall`: model usage and cost log.
- `Artifact`: durable output record.
- `Experiment`: keep/discard attempt.
- `EvalReport`: quality and outcome report.
- `AcceptanceReport`: runtime acceptance result with scenario details, aggregate trend data, and
  optional trend warnings.
- `CostReport`: budget and usage report.
- `MemoryEntry`: reusable memory.
- `Event`: runtime event log.
- `HandoffPackage`: continuation package.

## Storage Layout

```text
AGENTS.md
.agent/
  project.json
  policies.json
  current_session.json
  context/
    root_snapshot.json
    snapshots/
    handoffs/
  tasks/
    backlog.json
  runs/
    run-*/
      run.json
      goal_spec.json
      task_plan.json
      task_plan_eval.json
      events.jsonl
      tool_calls.jsonl
      model_calls.jsonl
      artifacts.jsonl
      cost_report.json
      eval_report.json
      final_report.md
  memory/
```

`agent acceptance` also writes `.agent/acceptance/acceptance_report.json`,
`.agent/acceptance/latest_summary.json`, `.agent/acceptance/history.jsonl`, and optional
`.agent/acceptance/failures/*.json` evidence records.

## Implementation Rule

All persisted JSON must include:

```json
{
  "schema_version": "0.1.0"
}
```

All persisted JSON should be validated at read/write boundaries.

`current_run.json` is treated as a legacy compatibility pointer if present. New writes use
`current_session.json`.
