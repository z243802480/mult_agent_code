# Multi-Agent Autonomous Development System - Task Decomposition Guide

## 1. Purpose

This guide defines how the planner should split goals into executable, reviewable, and verifiable tasks.

Good task decomposition is essential for autonomous agents. A task should be neither too large to verify nor too small to create scheduling overhead.

## 2. Principles

### 2.1 Use Acceptable Artifacts as Boundaries

A task should produce or modify a concrete artifact:

- Source file.
- Test file.
- Report.
- Configuration.
- UI page.
- Data file.
- Evaluation result.

### 2.2 Use User Value or Engineering Closure as the Unit

Each task should represent a useful behavior, a validated engineering slice, or a risk-reducing step.

### 2.3 Recommended Size

A good task can usually be completed in one agent iteration and verified by one to three checks.

### 2.4 Avoid Over-Splitting

Avoid tasks that only rename variables, create empty files, or write a vague placeholder without acceptance criteria.

### 2.5 Avoid Oversized Tasks

Avoid tasks that span many modules, output forms, or independent features without intermediate verification.

## 3. Standard Task Structure

Each task should include:

- `task_id`
- `title`
- `description`
- `status`
- `priority`
- `role`
- `depends_on`
- `acceptance`
- `allowed_tools`
- `expected_artifacts`
- `expected_changed_files`
- `completion_contract`
- `verification_policy`

## 4. Task Types

Research task:

- Produces sources, claims, and implementation hypotheses.

Product task:

- Clarifies expected user value and feature priority.

Architecture task:

- Defines module boundaries and constraints.

Implementation task:

- Changes code or configuration.

UI/Experience task:

- Chooses or implements an output medium and interaction model.

Verification task:

- Adds or runs tests, smoke checks, or acceptance scripts.

Repair task:

- Uses failure evidence to produce a minimal fix.

Documentation task:

- Produces user-facing or developer-facing docs.

## 5. Decomposition Process

1. Read the GoalSpec.
2. Identify must/should/could requirements.
3. Identify expected artifacts.
4. Split by behavior, risk, and verification boundary.
5. Add dependencies.
6. Add acceptance criteria.
7. Assign allowed tools.
8. Define verification policy.
9. Score task quality.

## 6. Capability-Chain Decomposition

For tools and apps, split by capability chain:

```text
input -> processing -> storage -> output -> verification -> documentation
```

## 7. Risk-First Decomposition

For uncertain work, isolate high-risk assumptions into research, experiment, or spike tasks before full implementation.

## 8. Vertical Slice Decomposition

Prefer a small working end-to-end slice over many disconnected horizontal layers.

## 9. Task Quality Scoring

Evaluate:

- Artifact clarity.
- Acceptance observability.
- Dependency correctness.
- Tool permission fit.
- Risk isolation.
- Expected size.

## 10. Anti-Patterns

- Verb-only tasks with no artifact.
- Unverifiable acceptance criteria.
- One task crossing too many layers.
- No risk isolation.
- “Implement everything” tasks.

## 11. PlannerAgent Output Requirements

PlannerAgent must output machine-readable tasks that can be validated by schema and executed by the runtime without guessing missing fields.

## 12. Recommended Task Count

For a small MVP goal, use 2-6 tasks. For a tiny single-file task, one task is acceptable. For broad goals, create an initial slice and follow-up tasks rather than a huge plan.

## 13. Decomposition and Cost Control

Task decomposition should reduce wasted model calls by making each iteration independently verifiable.

## 14. Acceptance of Decomposition

Every must requirement should be covered by at least one task, and every implementation task should have an observable artifact and verification path.
