# Multi-Agent Autonomous Development System - Delivery Plan

## MVP Focus

The MVP validates the core harness loop:

```text
init project
  -> receive goal
  -> generate GoalSpec
  -> expand basic requirements
  -> decompose tasks
  -> execute implementation
  -> verify
  -> repair
  -> keep/discard
  -> compact context
  -> final report
```

## MVP Must-Haves

- CLI entrypoint
- `/init`
- GoalSpec generation
- Basic requirement expansion
- Task board
- Single controlled workspace
- Tool registry
- Basic auto-repair
- `/compact`
- Final report
- Cost report
- Safety policy

## Deferred, Not Deleted

- Multi-agent concurrency
- Git worktree merge queue
- Full dashboard
- Advanced research and citations
- Vector memory
- PDF generation
- UI screenshot checks
- Plugin marketplace

## Phase Plan

1. Phase 0: documentation and spec freeze.
2. Phase 1: single-agent harness.
3. Phase 2: verification and repair.
4. Phase 3: requirement expansion and decisions.
5. Phase 4: research and UI/Experience.
6. Phase 5: multi-agent and isolated workspaces.

## MVP Done

- `/init` works.
- `/plan` works.
- `agent run` completes a minimal loop.
- `/compact` works.
- At least two benchmarks pass.
- Cost report is generated.
- Dangerous commands are blocked.
- Final report is generated.
