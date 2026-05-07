# Multi-Agent Autonomous Development System - Test Strategy

## 1. Purpose

The goal of testing is not to prove that a single model answer looks good. It is to prove that the agent runtime can reliably complete long-running tasks.

## 2. Test Pyramid

The system should use:

- Unit tests for pure logic and schema validation.
- Integration tests for command workflows.
- End-to-end scenarios for runtime behavior.
- Real-model acceptance for provider and prompt stability.
- Regression benchmarks for representative goals.

## 3. Unit Tests

Unit tests should cover:

- Schema loading and validation.
- Budget controller.
- Task state transitions.
- Path and shell guards.
- JSON/JSONL storage.
- Context compression helpers.
- Model response parsing.

## 4. Schema Tests

Every persisted object schema should have:

- Valid example data.
- Missing-required-field failure.
- Type mismatch failure.
- Backward compatibility checks when schema changes.

## 5. Tool Tests

Tool tests must verify:

- Allowed file reads.
- Protected path denial.
- Controlled file writes.
- Patch application.
- Command execution.
- Dangerous shell rejection.
- Tool-call logging.

## 6. Command Workflow Tests

Test `/init`, `/plan`, `/brainstorm`, `/compact`, `/debug`, `/review`, `/handoff`, and `/acceptance` as command-level workflows.

Each command test should verify:

- Expected artifacts.
- Expected run state.
- Event logs.
- Clear failure behavior.

## 7. Agent Loop Tests

Agent-loop tests should cover:

- Goal to plan.
- Plan to execution.
- Execution to verification.
- Verification failure to repair.
- Review follow-up generation.
- Context compaction and resumption.

## 8. End-to-End Scenarios

Representative scenarios:

- Password testing tool.
- Markdown knowledge base.
- Batch file renamer.
- Fixing an existing failing project.
- Long-task context continuation.

## 9. Regression Benchmark Set

Benchmarks should be deterministic where possible and should record:

- Workspace path.
- Run id.
- Expected artifacts.
- Checks.
- Failures.
- Cost summary.

## 10. Model Instability Strategy

Real models are unstable. Tests should:

- Separate deterministic runtime tests from real-model acceptance.
- Retry transient provider failures.
- Record stdout/stderr tails.
- Persist summary JSON.
- Track trends over time.

## 11. Cost Tests

Must test:

- Budget stop.
- Near-budget degradation.
- Context compaction threshold.
- Repair attempt limits.
- Warning when many calls produce no artifacts.

## 12. Security Tests

Must test:

- `.env` reads are blocked.
- Large destructive deletes are blocked.
- Global installs are blocked.
- Remote pushes are blocked.
- Deployments are blocked.
- Research degrades correctly when network is disabled.

## 13. Test Report

Each verification run should produce:

- Status.
- Platform.
- Timestamp.
- Checks.
- Artifacts.
- Failure details.

## 14. MVP Test Done Definition

MVP testing is minimally complete when:

- `/init` tests pass.
- `/plan` tests pass.
- `/compact` tests pass.
- At least two end-to-end scenarios pass.
- Cost threshold tests pass.
- Security permission tests pass.
- At least one failure repair test passes.
