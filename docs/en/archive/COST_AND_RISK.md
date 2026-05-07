# Multi-Agent Autonomous Development System - Cost Control and Risk Governance

## 1. Purpose

This document defines how the system controls API cost, tool cost, time cost, cognitive cost, and engineering risk.

Cost control is not only about saving money. It ensures that tokens, tool calls, and agent iterations turn into useful artifacts.

## 2. Cost Goals

The system should pursue:

```text
moderate calls
high artifact yield
low idle looping
explainable cost
configurable budgets
degrade or stop before overspending
```

Even with generous subscription quotas, the runtime must not allow explosive uncontrolled usage.

## 3. Cost Types

Model cost includes:

- Model call count.
- Input tokens.
- Output tokens.
- Long-context usage.
- Ratio of strong-model calls.

Tool cost includes:

- Shell command execution.
- Test runs.
- Build runs.
- Browser screenshots.
- Web research.
- File scanning.

Time cost includes:

- Per-task execution duration.
- Repair rounds.
- Waiting for user decisions.
- Total long-task duration.

Cognitive cost includes:

- Number of user interruptions.
- Number of decision packages the user must read.
- Complexity of the final report.

## 4. Default Budget Strategy

The MVP should use explicit goal budgets:

```yaml
goal_budget:
  max_model_calls: 60
  max_tool_calls: 120
  max_total_minutes: 30
  max_iterations: 8
  max_repair_attempts_total: 5
  max_repair_attempts_per_task: 2
  max_research_calls: 5
  max_user_decisions: 5

context:
  compaction_threshold: 0.75
  hard_stop_threshold: 0.90
```

## 5. Degradation Strategy

When approaching budget limits, the runtime should:

1. Compact context.
2. Reduce brainstorm candidate count.
3. Stop low-value branches.
4. Downgrade non-critical model calls.
5. Merge similar tasks.
6. Reduce repair attempts.
7. Ask the user for approval.
8. Produce an interim report and pause.

## 6. Cost Anomaly Detection

Danger signs:

- Many model calls with no file artifacts.
- Repeated reads of the same large file.
- Repeated failed tests without any repair.
- Multiple agents doing duplicate research.
- Brainstorming without convergence.
- Context near limit without compaction.

When triggered, the runtime must record an event, summarize the cause, attempt compaction or convergence, and create a decision point when needed.

## 7. Risk Categories

Goal drift:

- Agents may expand requirements away from the user's real intent.
- Control with GoalSpec, explicit assumptions, decision points, and scope-drift evaluation.

Cost explosion:

- Long context, multiple agents, and repeated repairs can cause uncontrolled calls.
- Control with budgets, compaction, model routing limits, and hard-stop decisions.

Research hallucination:

- ResearchAgent may produce plausible but unsupported conclusions.
- Control with sources, claim/evidence separation, inference labels, and validation tasks.

Codebase damage:

- Automated changes may make the project unrecoverable.
- Control with workspace isolation, diff review, backups, protected paths, and pre-merge validation.

User interruption overload:

- The system may ask too many small questions.
- Control with configurable decision granularity and automatic defaults for minor choices.

Missing major decision:

- The system may silently choose product direction, stack, privacy, or output medium.
- Control with decision-point detection for scope, budget, privacy, architecture, and irreversible operations.

Repair loop runaway:

- The system may keep repairing without progress.
- Control with repair limits, before/after metrics, rollback, and blocked reports.

Multi-agent conflicts:

- Agents may edit the same files or create conflicting designs.
- Control with single-agent MVP, later Git worktrees, ownership, and merge queues.

Security and privacy:

- Agents may read sensitive files or send local data to external services.
- Control with protected paths, network policy, external-service decision points, local-first defaults, and secret scanning.

## 8. Risk State

Each risk should be marked as:

- `designed`
- `mitigated`
- `accepted`
- `blocked`
- `needs_research`

Risks must have handling status and ownership. A bare “there is risk” note is not enough.

## 9. Runtime Cost Report

Every run must output model calls, tool calls, token estimates, repair attempts, context compactions, user decisions, budget status, and warnings.

## 10. Default Security Policy

The MVP should block protected path reads, destructive shell, global installs, remote pushes, production deployments, and external sensitive-data transfer unless a policy-approved decision explicitly allows it.
