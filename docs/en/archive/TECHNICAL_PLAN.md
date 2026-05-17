# Multi-Agent Autonomous Development System - Technical Implementation Plan

## 1. Purpose

This document turns the product goal, requirements, and architecture into the first engineering implementation plan.

Goals:

- Define MVP technology choices.
- Define directory structure.
- Define module boundaries.
- Define implementation order.
- Clarify which capabilities are real implementations first and which remain future interfaces.

## 2. First-Version Technology Choice

The first version should use Python for the runtime.

Reasons:

- Mature ecosystem for orchestration, files, JSON schema, CLI, tests, and automation.
- Easy integration with local scripts, Git, test commands, and document processing.
- Natural path to a future FastAPI dashboard.

Recommended stack:

```text
language: Python 3.11+
configuration: Pydantic / pydantic-settings later
schema validation: jsonschema or Pydantic model
storage: filesystem + JSONL, SQLite later
logging: standard logging or JSONL
tests: pytest
model interface: OpenAI-compatible adapter
async: synchronous first, asyncio later
```

## 3. Project Directory Structure

Recommended:

```text
src/asteria_runtime/
  commands/
  core/
  tools/
  models/
  storage/
  evaluation/
  security/
  agents/
schemas/
tests/
docs/
```

## 4. Module Boundaries

CLI layer:

- Parse user commands.
- Call the command router.
- Print human-readable summaries.

Command layer:

- Map commands to workflows.
- Check permissions and budgets.
- Load context.
- Write command execution records.

Core runtime:

- State machine.
- Task scheduling.
- Budget control.
- Decision escalation.
- Context loading.

Storage layer:

- Read and write `.agent/`.
- JSON and JSONL persistence.
- Schema validation.
- Run directory management.

Tool layer:

- File, search, patch, command, and test tools.
- Tool-call logging.
- Permission enforcement.

Model provider layer:

- Abstract model calls.
- Support OpenAI-compatible APIs.
- Record model calls.
- Support timeout, retry, routing, and cost estimates.

Agents layer:

- Role-specific agents.
- Prompt construction.
- Model and tool interaction under runtime control.

Evaluation layer:

- Run verification commands.
- Compute eval reports.
- Evaluate outcome, trajectory, and cost.

Security layer:

- Path protection.
- Shell command classification.
- High-risk operation interception.
- Secret detection.

## 5. Core Runtime Flow

`/init`:

```text
detect project
  -> create .agent/project.json
  -> create .agent/policies.json
  -> create root snapshot
  -> create task backlog
```

`run "<goal>"`:

```text
goal -> GoalSpec -> TaskPlan -> Execute -> Verify -> Repair -> Review -> Report
```

`/compact`:

```text
load run state -> summarize goal/tasks/decisions/failures -> write ContextSnapshot
```

## 6. MVP Implementation Strategy

Avoid over-engineering in the first version:

- Use filesystem and JSONL first.
- Use a single workspace before concurrent worktrees.
- Start with OpenAI-compatible model adapters.
- Use command-driven execution before background scheduling.
- Write schemas and tests before expanding complex agents.

## 7. Dependency Guidance

Keep dependencies minimal for MVP. Prefer the standard library where reasonable. Add third-party libraries only when they reduce meaningful risk or complexity.

## 8. Configuration Sources

Configuration priority:

```text
CLI arguments
  > environment variables
  > .agent/policies.json
  > defaults
```

Model configuration should use environment variables.

## 9. Implementation Gates

Before moving to the next phase:

- Schema validation passes.
- Unit tests pass.
- At least one end-to-end scenario passes.
- Cost reports are generated.
- `final_report.md` is generated.
- High-risk shell commands are intercepted.

## 10. Future Extension Points

- SQLite storage.
- Git worktrees.
- Multi-agent concurrency.
- ResearchAgent with networked research.
- UI screenshot checks.
- Long-term vector memory.
