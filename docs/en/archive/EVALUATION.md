# Multi-Agent Autonomous Development System - Acceptance Metrics and Evaluation System

## 1. Purpose

This document defines how the system judges whether a task was completed well.

The system must not rely only on model self-evaluation. Evaluation should combine:

- Structured acceptance criteria.
- Automated tests.
- Runtime results.
- Code and artifact review.
- User decisions.
- Cost and trajectory evaluation.

## 2. Evaluation Layers

```text
Goal Eval: whether the goal was understood and expanded correctly
Artifact Eval: whether artifacts exist, run, and are readable
Outcome Eval: whether the final result satisfies the goal
Trajectory Eval: whether the execution process is healthy, economical, and recoverable
```

## 3. Goal Eval

Metrics:

- `goal_clarity_score`
- `requirement_expansion_score`
- `assumption_quality_score`
- `definition_of_done_score`
- `decision_point_quality_score`

Minimum acceptance:

```text
goal_clarity_score >= 0.75
definition_of_done_score >= 0.75
```

## 4. Artifact Eval

Checks:

- Goal specification exists.
- Task plan exists.
- Run logs exist.
- Target artifacts exist.
- Final report exists.
- Tool calls are recorded.
- Cost summary is recorded.

Failure conditions:

- Only chat summaries are produced.
- Files are modified without recorded reasons.
- No final report is generated.

## 5. Outcome Eval

Common metrics:

- `requirement_coverage`
- `verification_pass_rate`
- `usability_score`
- `documentation_score`
- `safety_score`
- `run_success`

Suggested minimum:

```text
requirement_coverage >= 0.80
verification_pass_rate >= 0.90
```

## 6. Trajectory Eval

The runtime should evaluate whether the route to the result was healthy:

- Too many retries.
- Repeated failures without learning.
- Excessive context growth.
- Repeated tool calls without artifacts.
- Skipped verification.
- Unresolved blockers.

## 7. Cost Eval

Cost evaluation should check:

- Model calls.
- Tool calls.
- Token estimates.
- Repair attempts.
- Context compactions.
- User decisions.
- Cost per accepted artifact.

## 8. User Decision Evaluation

Decision quality should measure:

- Whether major branches were detected.
- Whether the question was clear.
- Whether options were concrete.
- Whether tradeoffs were explicit.
- Whether the default was safe.
- Whether accepted decisions were reused as constraints.

## 9. Self-Iteration Evaluation

The system should measure whether it improved beyond literal one-step execution:

- Did it infer reasonable missing requirements?
- Did it research or use local evidence when useful?
- Did it produce follow-up tasks from review?
- Did it stop at a useful baseline instead of looping endlessly?

## 10. Evaluation Report Format

The evaluation report should include:

- Goal evaluation.
- Artifact evaluation.
- Outcome evaluation.
- Trajectory evaluation.
- Cost evaluation.
- Overall status.
- Follow-up tasks or decision points.

## 11. Acceptance Levels

Pass:

- Core requirements are satisfied.
- Verification passes.
- No unresolved high-risk blockers.

Partial:

- The result is useful but incomplete.
- Follow-up tasks are clear.
- Risks are documented.

Fail:

- Core requirements are missing.
- Verification fails.
- The system cannot recover without user or developer intervention.

## 12. MVP Acceptance Cases

The MVP should cover:

- Initializing a planning workspace.
- Expanding a vague goal.
- Repairing a failed task.
- Continuing after context compaction.
- Creating and resolving a major decision point.
