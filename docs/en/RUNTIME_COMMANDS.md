# Multi-Agent Autonomous Development System - Runtime Commands

## Initial Commands

- `/init`: initialize an agent-ready workspace.
- `/plan`: turn a goal into GoalSpec and tasks.
- `/run`: plan, execute, repair, review, compact, and write a final report.
- `/brainstorm`: generate and rank candidate directions.
- `/research`: turn sources into executable hypotheses.
- `/compact`: create a context snapshot.
- `/execute`: consume ready tasks, let CoderAgent produce structured tool calls, execute them, verify results, and update task state.
- `/decide`: create a user decision point.
- `/review`: review code, UX, tests, and risk.
- `/debug`: analyze failure and propose repair.
- `/handoff`: create a continuation package.

## Task Decomposition Principles

Good tasks should be:

- not too large
- not too small
- artifact-oriented
- verifiable
- dependency-aware
- suitable for agent execution and review

Suggested task size:

```text
implementation time: 15-90 minutes
changed files: 1-5
acceptance criteria: 2-6
dependencies: 0-3
artifacts: 1-4
```

## Task Quality Scores

- clarity_score
- testability_score
- size_score
- dependency_score
- artifact_score
- risk_score

PlannerAgent should rewrite tasks below quality thresholds.

## `/execute` State Flow

```text
ready -> in_progress -> testing -> reviewing -> done
```

Tool failures, verification failures, invalid model output, or disallowed tool requests move the task to `blocked`.

The command writes:

- `task_plan.json`
- `.agent/tasks/backlog.json`
- `events.jsonl`
- `tool_calls.jsonl`
- `model_calls.jsonl`
- `cost_report.json`

Execution is constrained by both the task `allowed_tools` field and the runtime tool registry.

## `/run` Closed Loop

`/run` is the user-facing MVP command for a complete local-first execution loop.

```text
init if needed
  -> plan
  -> execute ready tasks
  -> debug blocked tasks when possible
  -> review
  -> compact
  -> final_report.md
```

It writes `final_report.md` under `.agent/runs/<run_id>/` with task completion, blocked-task notes, cost counters, artifact summaries, and recommended next actions.

## `/debug` Repair Flow

`/debug` consumes blocked tasks and repairs them with DebugAgent.

```text
collect tool/model/event evidence
  -> generate minimal repair action
  -> run repair tool calls
  -> rerun verification
  -> mark done or keep blocked
```

Successful repairs move through:

```text
blocked -> ready -> in_progress -> testing -> reviewing -> done
```

The command accumulates `repair_attempts`, model calls, tool calls, and token usage in `cost_report.json`.

## `/review` Evaluation Flow

`/review` evaluates a run using GoalSpec, the task board, event logs, tool/model logs, and cost data.

It writes:

- `eval_report.json`
- `review_report.md`
- updated `cost_report.json`

The report includes goal, artifact, outcome, trajectory, and cost evaluation. `overall.status` drives run state:

- `pass` -> `completed`
- `partial` -> `running`
- `fail` -> `blocked`

## `/decide` Decision Points

`/decide` creates and resolves user-facing decision points.

Supported modes:

- create: `agent decide --question ... --options-json ...`
- list: `agent decide --list-pending`
- resolve: `agent decide --decision-id ... --select-option-id ...`
- default: `agent decide --decision-id ... --use-default`

Decisions are written to `decisions.jsonl`, emit `decision_created` / `decision_resolved` events, and increment `user_decisions` in `cost_report.json`.
