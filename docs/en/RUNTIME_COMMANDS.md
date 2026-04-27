# Multi-Agent Autonomous Development System - Runtime Commands

## Initial Commands

- `/init`: initialize an agent-ready workspace.
- `/plan`: turn a goal into GoalSpec and tasks.
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
