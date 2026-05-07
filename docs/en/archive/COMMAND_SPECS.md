# Multi-Agent Autonomous Development System - Command Specifications

## 1. Purpose

This document defines the initial runtime commands: their inputs, outputs, permissions, state transitions, artifacts, budgets, and failure handling.

Commands are not prompt shortcuts. They are reusable, observable, and auditable workflows.

## 2. General Command Structure

Each command should define:

- Name.
- Purpose.
- Input arguments.
- Context read.
- Allowed tools.
- Participating agents.
- State transitions.
- Output artifacts.
- Cost budget.
- Failure handling.
- Whether agents may invoke it autonomously.

General execution flow:

```text
parse command
  -> load root guidance
  -> load relevant memory
  -> check permissions and budget
  -> run command workflow
  -> write artifacts
  -> update event log
  -> update task state
  -> summarize result
```

## 3. `/init`

Initializes a directory as an agent-ready workspace.

Inputs:

```text
/init
/init --force
/init --profile planning|codebase|empty
```

Reads current directory structure, Git state, README files, package/config files, and existing `AGENTS.md` or `.agent/` state.

Outputs:

- `AGENTS.md`
- `.agent/project.json`
- `.agent/policies.json`
- `.agent/context/root_snapshot.json`
- `.agent/tasks/backlog.json`

Failure handling:

- Do not overwrite user-authored guidance.
- If generated content conflicts with existing content, create a proposed patch or warning.
- If the project type is ambiguous, create a decision point.

## 4. `/plan`

Turns a user goal into a `GoalSpec` and task plan.

Inputs:

```text
/plan "goal"
/plan --from file.md
```

Participating agents:

- GoalSpecAgent
- PlannerAgent
- optional ResearchAgent
- optional UIExperienceAgent

Outputs:

- `.agent/runs/<run_id>/goal_spec.json`
- `.agent/runs/<run_id>/task_plan.json`
- `.agent/tasks/backlog.json`

Acceptance:

- Goal assumptions are explicit.
- The task plan is executable.
- Each task has artifacts and acceptance criteria.
- Major uncertain branches become decision points.

## 5. `/brainstorm`

Generates and ranks product or implementation directions.

Inputs:

```text
/brainstorm "topic"
/brainstorm --goal goal_spec.json --max-candidates 8
```

Outputs:

- `brainstorm_report.md`
- `idea_candidates.json`
- optional tasks
- optional decision points

Flow:

1. Restate the goal and constraints.
2. Generate diverse candidates.
3. Cluster similar candidates.
4. Score value, feasibility, cost, risk, novelty, and fit.
5. Recommend a small set.
6. Convert the selected candidates into tasks or decisions.

## 6. `/research`

Runs structured research and converts findings into executable hypotheses.

Inputs:

```text
/research "question"
/research --goal goal_spec.json
```

Outputs:

- `research_report.md`
- source list
- claim/evidence table
- implementation hypotheses
- experiment plans

Quality requirements:

- Claims must cite sources.
- Unsupported statements must be marked as inference.
- Research should produce executable tasks when useful.

## 7. `/compact`

Compresses context while preserving critical state.

Inputs:

```text
/compact
/compact --focus "API design and changed files"
```

Outputs:

- `.agent/context/snapshots/<timestamp>.json`

Must preserve:

- Goal and definition of done.
- Accepted decisions.
- Active tasks and state.
- Modified files and reasons.
- Verification commands and results.
- Failures and repair attempts.
- Open risks and next actions.

## 8. `/decide`

Creates or resolves user-facing decision points.

Each decision must include:

- Concise question.
- Recommended option.
- Concrete options.
- Tradeoffs.
- Default option.
- Impact on budget, scope, risk, and quality.

Agents may create decision points when policy requires user steering.

## 9. `/review`

Reviews code, UX, tests, architecture, or trajectory before trusting results.

Review dimensions:

- Correctness.
- Requirement coverage.
- Regression risk.
- Security.
- Scope drift.
- Test coverage.
- Maintainability.
- UX quality when applicable.

Outputs:

- `review_report.md`
- `eval_report.json`
- follow-up tasks or decision points

## 10. `/debug`

Analyzes failure evidence and proposes or executes repairs.

Inputs:

```text
/debug --from failure.json
/debug --task task-0003
```

Flow:

1. Load failure evidence.
2. Summarize logs.
3. Form root-cause hypotheses.
4. Propose a minimal repair.
5. Run verification.
6. Keep successful repair or mark blocked.

## 11. `/handoff`

Creates a machine-readable continuation package for another agent or future run.

Outputs:

- Handoff package.
- Referenced context snapshot.
- Current task board.
- Accepted decisions.
- Verification history.
- Failure evidence.
- Recommended next command.

## 12. Command Budget Guidance

Commands should declare model-call, tool-call, repair, and time budgets. When a command approaches hard limits, it must compact context, reduce low-value branches, or create a budget decision point.
