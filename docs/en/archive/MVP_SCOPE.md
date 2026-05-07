# Multi-Agent Autonomous Development System - MVP Scope and Roadmap

## 1. Purpose

This document defines the MVP scope, phased roadmap, deferred capabilities, and default runtime policy.

## 2. MVP Positioning

The MVP should validate the most critical agent harness loop:

```text
initialize project
  -> receive goal
  -> generate goal spec
  -> expand basic requirements
  -> decompose tasks
  -> implement
  -> verify
  -> repair
  -> keep or discard
  -> compact context
  -> produce final report
```

The MVP is not intended to finish the whole multi-agent platform at once.

## 3. Required MVP Capabilities

The MVP must include:

- CLI entrypoint.
- `/init`.
- Goal specification.
- Basic requirement expansion.
- Task board.
- Single-workspace execution.
- Tool registry.
- Basic auto-correction.
- Context compression.
- Final report.
- Cost report.
- Safety policy.

## 4. Deferred Capabilities

The MVP may defer:

- Multi-agent concurrency.
- Git worktree merge queue.
- Full web dashboard.
- Full paper research and citation system.
- Advanced vector memory.
- PDF generation.
- UI screenshot automation.
- Plugin marketplace.
- Distributed experiment execution.

## 5. Phase Roadmap

Phase 0: documentation and specification freeze.

Phase 1: single-agent harness.

Phase 2: validation and automatic repair.

Phase 3: requirement expansion and decision management.

Phase 4: research and UI/Experience.

Phase 5: multi-agent and workspace isolation.

## 6. Requirement Retention Strategy

Each requirement should be marked as:

- `mvp`
- `v1`
- `v2`
- `v3`
- `research`
- `blocked`

Do not delete meaningful requirements simply because the MVP is narrower. High-risk requirements should be transformed into controls such as permissions, budgets, user decision points, sandbox isolation, validation gates, or staged rollout.

## 7. Default MVP Policy

```yaml
decision_granularity: balanced
max_iterations_per_goal: 8
max_repair_attempts_per_task: 2
max_total_tool_calls: 120
max_total_model_calls: 60
context_compaction_threshold: 0.75
allow_network_research: false
allow_shell: true
allow_destructive_shell: false
allow_global_install: false
```
