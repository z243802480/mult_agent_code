# Multi-Agent Autonomous Development System - Cost, Security, and Risk

## Cost Goal

The system should use model and tool calls moderately, convert calls into artifacts, avoid loops, and stop or degrade before budget explosion.

## Default MVP Budget

```yaml
max_model_calls: 60
max_tool_calls: 120
max_total_minutes: 30
max_iterations: 8
max_repair_attempts_total: 5
max_repair_attempts_per_task: 2
max_research_calls: 5
max_user_decisions: 5
context_compaction_threshold: 0.75
```

## Degradation Strategy

1. Compact context.
2. Reduce brainstorm candidates.
3. Stop low-value branches.
4. Downgrade non-critical model calls.
5. Merge similar tasks.
6. Reduce repair attempts.
7. Ask the user before continuing.
8. Pause with a phase report.

## Default Security Policy

```yaml
allow_network: false
allow_shell: true
allow_destructive_shell: false
allow_global_package_install: false
allow_secret_file_read: false
allow_remote_push: false
allow_deploy: false
```

## Risk Controls

- Goal drift: GoalSpec, assumptions, DecisionPoint, scope drift eval.
- Cost explosion: budgets, model routing, compaction, stop conditions.
- Research hallucination: source tracking, claim/evidence split.
- Codebase damage: workspace isolation, diff review, rollback.
- User interruption: configurable decision granularity.
- Missed major decision: Decision Manager.
- Repair loops: retry limits and metric comparison.
- Multi-agent conflict: file ownership, worktrees, merge queue.
