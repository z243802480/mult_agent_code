# Multi-Agent Autonomous Development System - Quality and Evaluation

## Evaluation Layers

```text
Goal Eval
Artifact Eval
Outcome Eval
Trajectory Eval
Cost Eval
```

## Goal Eval

Checks whether the goal was understood, expanded, and made verifiable.

Core metrics:

- goal_clarity_score
- requirement_expansion_score
- assumption_quality_score
- definition_of_done_score
- decision_point_quality_score

## Outcome Eval

Core metrics:

- requirement_coverage
- verification_pass_rate
- usability_score
- documentation_score
- safety_score
- run_success

## Trajectory Eval

Detects unhealthy behavior:

- repeated edits without improvement
- bypassed tests
- scope drift
- model calls without artifacts
- excessive minor user questions
- high-risk operations without decisions

## Task Plan Eval

`/plan` writes `task_plan_eval.json` before execution. The deterministic evaluator checks:

- task granularity
- ready entry points
- dependency validity
- observable acceptance criteria
- concrete expected artifacts
- write and verification tool coverage

Recommended gate:

```text
pass: execute directly
warn: execute, but review warnings
fail: replan or create a DecisionPoint before execution
```

## Test Strategy

```text
Unit Tests
  -> Schema Tests
  -> Tool Tests
  -> Command Workflow Tests
  -> Agent Loop Tests
  -> End-to-End Scenario Tests
  -> Regression Benchmarks
```

## MVP Scenarios

- Password testing tool
- Markdown knowledge base
- Batch file renamer
- Existing project repair
- Long-context compaction and handoff
