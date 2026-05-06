# Multi-Agent Autonomous Development System - Runtime Commands

## Initial Commands

- `/init`: initialize an agent-ready workspace.
- `/new`: start a new isolated goal context and make it the current session.
- `/plan`: turn a goal into GoalSpec and tasks.
- `/sessions`: list, show, or switch user-facing session contexts.
- `/run`: with a goal, create and execute a new session; without a goal, continue the current session.
- `/resume`: continue a paused run after user decisions are resolved.
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

## `/new` And `/sessions` Context Isolation

`Session` is the user-facing unit: one goal, one recoverable context, and one current pointer.
The runtime still stores the execution record as a run under `.agent/runs/<run_id>/`.

`/new` creates a fresh planning run for a new goal and writes `.agent/current_session.json`.

`/sessions` helps recover or switch context:

- `agent sessions`: list recent sessions and mark the current session.
- `agent sessions --session-id <id>`: show one session.
- `agent sessions --session-id <id> --set-current`: make a session current.

`/runs`, `/history`, and `--run-id` remain compatibility aliases. New documentation and user
flows should use `/sessions` and `--session-id`.
`agent acceptance-history` / `agent acceptance-trend` shows persisted acceptance history and trend
deltas from `.agent/acceptance/history.jsonl`.
Use `--fail-on-warning` to turn trend warnings into a non-zero exit code for local gates.

Commands such as `/run`, `/execute`, `/review`, `/debug`, `/decide`, `/resume`, and `/compact`
prefer the current session when `--session-id` is omitted. This prevents unrelated goals from
accidentally sharing context.

## `/run` Closed Loop

`/run` is the user-facing MVP command for a complete local-first execution loop.

- `agent run "goal"` or `agent /run "goal"` creates a new session and runs it.
- `agent run` or `agent /run` continues the current session.
- `agent run --session-id <id>` continues the selected historical session.

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

When review creates a high-impact decision point, `/run` pauses the run instead of silently expanding scope. The final report lists `Pending Decisions`.

## `/resume` Decision Continuation

`/resume` continues the same paused run after `/decide` resolves user decisions.

```text
load paused run
  -> refuse if decisions are still pending
  -> apply resolved/defaulted decisions
  -> map selected option actions to constraints or tasks
  -> continue execute/review/compact/final report loop
```

It writes `decision_applied` events. Decision options may include an `action`:

- `create_task`: create follow-up implementation work.
- `require_replan`: create a planning follow-up task.
- `record_constraint`: record the decision without creating work.
- `cancel_scope`: record that the proposed scope should not proceed.

Older decisions without `action` are still supported through option id/label inference.

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

New decisions should include option actions so `/resume` does not need to infer intent from labels.

After resolving decisions, use `agent resume --session-id ...` to continue the session.

## `/research` Source-Grounded Research

`/research` collects evidence and writes `research_report.json` plus `research_report.md`.

The implementation uses pluggable source adapters:

- local project documents
- explicit URLs when network is allowed
- Serper search when `SERPER_API_KEY` is configured and network is allowed

MCP servers and skills should be added as future source adapters rather than hard-coded into the research core.
