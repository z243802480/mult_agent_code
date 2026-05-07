# Multi-Agent Autonomous Development System - MVP Implementation Tasks

## 1. Purpose

This document decomposes the MVP into executable engineering tasks. Each task should have a goal, artifacts, acceptance criteria, and dependencies.

## 2. Phase 0: Engineering Setup

### T-0001 Initialize Python Project Skeleton

Goal: create the base Python project.

Artifacts:

- `pyproject.toml`
- `src/agent_runtime/__init__.py`
- `tests/`

Acceptance:

- `pytest` can run.
- The package can be imported.
- README explains basic usage.

### T-0002 Create Base Directory Structure

Artifacts:

- `src/agent_runtime/commands/`
- `src/agent_runtime/core/`
- `src/agent_runtime/tools/`
- `src/agent_runtime/models/`
- `src/agent_runtime/storage/`
- `src/agent_runtime/evaluation/`
- `src/agent_runtime/security/`

Acceptance:

- Each package directory has `__init__.py`.
- The structure matches `TECHNICAL_PLAN.md`.

## 3. Phase 1: Schema and Storage

### T-0101 Create Core JSON Schemas

Artifacts:

- `schemas/project.schema.json`
- `schemas/policy.schema.json`
- `schemas/run.schema.json`
- `schemas/goal_spec.schema.json`
- `schemas/task.schema.json`
- `schemas/context_snapshot.schema.json`
- `schemas/tool_call.schema.json`
- `schemas/model_call.schema.json`
- `schemas/eval_report.schema.json`
- `schemas/cost_report.schema.json`

Acceptance:

- Every schema loads.
- Example data validates.
- Missing required fields fail validation.

### T-0102 Implement SchemaValidator

Acceptance:

- JSON can be validated by object type.
- Validation failures return clear errors.

### T-0103 Implement JSON and JSONL Storage

Acceptance:

- JSON can be written and read.
- JSONL can be appended and listed.
- Optional schema validation runs before writes.

## 4. Phase 2: Initialization and Configuration

Tasks:

- T-0201 Implement ProjectStore.
- T-0202 Implement `/init`.
- T-0203 Implement the CLI entrypoint.

Acceptance:

- `.agent/` can be created.
- `project.json` and `policies.json` can be read and written.
- Re-running initialization is safe.
- Existing user-written `AGENTS.md` is not overwritten.

## 5. Phase 3: Events, Cost, and Task Board

Tasks:

- T-0301 Implement RunStore.
- T-0302 Implement EventLogger.
- T-0303 Implement BudgetController.
- T-0304 Implement TaskBoard.

Acceptance:

- Run directories can be created.
- Events are appended to JSONL.
- Budget overruns stop progress.
- Task state transitions are controlled.

## 6. Phase 4: Model Adapter and GoalSpec

Tasks:

- T-0401 Implement ModelClient abstraction.
- T-0402 Implement GoalSpecAgent.
- T-0403 Implement `/plan`.

Acceptance:

- OpenAI-compatible chat calls work.
- A vague password-tool goal produces structured GoalSpec.
- A task plan is generated.

## 7. Phase 5: Tool Layer and Controlled Execution

Tasks:

- T-0501 Implement file and search tools.
- T-0502 Implement patch tools.
- T-0503 Implement command and test tools.

Acceptance:

- Allowed paths can be read.
- Protected paths are blocked.
- Safe shell commands can run.
- Dangerous shell commands are rejected.

## 8. Phase 6: Execution Loop

Tasks:

- T-0601 Implement CoderAgent.
- T-0602 Implement EvalRunner.
- T-0603 Implement AutoCorrectionAgent.
- T-0604 Implement ReviewerAgent.

Acceptance:

- Tasks can modify files.
- Verification commands can run.
- Failures trigger repair attempts.
- Review occurs before keep/discard.

## 9. Phase 7: Context and Reporting

Tasks:

- T-0701 Implement `/compact`.
- T-0702 Implement ReporterAgent.
- T-0703 Implement `agent run`.

Acceptance:

- ContextSnapshot is generated.
- Final report is generated.
- A minimal closed loop runs from a user goal.

## 10. Phase 8: MVP Acceptance Scenarios

Tasks:

- T-0801 Create password-tool benchmark.
- T-0802 Create failing-tests benchmark.
- T-0803 Create compact-handoff benchmark.

## 11. MVP Done Definition

MVP is complete when:

- `/init` works.
- `/plan` works.
- `agent run` completes a minimal loop.
- `/compact` works.
- At least two benchmarks pass.
- Cost reports are generated.
- Dangerous commands are blocked.
- Final reports are generated.

## 12. V1 Task Pool

After MVP:

- Full `/brainstorm`.
- Networked `/research`.
- Full DecisionManager.
- Multi-agent concurrency.
- Git worktrees.
- SQLite storage.
- PDF reports.
