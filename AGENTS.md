# Agent Project Guidance

## 1. Project Purpose

This project is an agent-ready workspace. Agents must use this file as high-priority project context before planning, editing, reviewing, or reporting.

Project purpose:

```text
Build a local-first harness for general long-task agents: turn compact goals into verified
artifacts through goal specification, on-demand planning, controlled tool/MCP/skill use,
validation, repair, context compression, cost control, and final reporting—with a friendly
CLI and Studio surface (not command-only UX).
```

## 2. Execution Plan (mandatory)

```text
执行计划唯一入口：docs/zh/研发总计划.md
当前 ACTIVE_PHASE：Phase 5（蜂群 · 主链集成）
当前 ACTIVE_SLICE：S31（统一场景闸门 + holistic 脉搏）
稳态节奏：docs/zh/稳态迭代节奏.md
事实快照：docs/zh/当前状态与路线.md
设计索引：docs/zh/文档导航.md
```

Any agent must read `docs/zh/研发总计划.md` before code or doc changes. Do not start North Star,
swarm parallel write, or new maintainer commands unless the master plan todo explicitly allows it.

Reference-first: before each Vibe Slice, read `benchmarks/reference_briefs/Sn.md` (create if missing).
No brief → no coding. Learn from OpenCode / Claude Code / Codex-rs mechanisms; do not reinvent wheels.

## 3. Code Triage Lock (Phase 0–2)

| Tier | Rule |
| --- | --- |
| **KEEP_CORE** | Do not delete: run/execute/plan/chat/status/review/accept/debug, agent_loop_*, user_progress_logger, runtime_progress, candidate/merge/promotion, studio server/Thread/Composer, schemas, core tests |
| **KEEP_PLACEHOLDER** | Do not expand: disjoint_write real parallel, sandbox rollout, deferred Agent classes, legacy event_logger fallback |
| **HIDE_NOT_DELETE** | Hide from user help, keep for CI: daily/weekly/roadmap, gate/acceptance/validation/real-model-*, evidence-bundle |
| **MERGE_OR_TRIM** | Phase 1b only: delete runs_command.py; merge validation→validation-run; trim CLI aliases; remove Studio fake completion |
| **DO_NOT_TOUCH** | No refactor: execute_command.py, run_command.py, gate_status_command.py, acceptance/real_model stack (append user_progress only) |

Full table: `docs/zh/研发总计划.md` §6.

## 4. Non-Goals

Agents must not silently expand the project beyond these boundaries:

```text
Do not build an unrestricted agent chatroom.
Do not allow destructive shell actions without policy approval.
Do not depend on a single model provider.
Do not skip schema validation for persisted runtime objects.
Do not prioritize a gate dashboard before harness + user_progress work.
Do not copy proprietary implementations from reference products.
```

## 5. Current Assumptions

```text
MVP proof: coding harness first (Goal→Plan→Execute→Verify→resume); doc/creative tasks reuse the same loop.
Autonomy: supervised_auto (reviewed_auto); hard-stop, promotion, release, irreversible actions must interrupt.
Backend first + Studio in parallel on user_progress / runtime_progress contract.
MVP endpoint: studio-benchmark task small_code_change score >= 0.8 with real provider (Slice S7).
North Star and swarm parallel write: only after S7 gate (Phase 3+).
MVP uses filesystem + JSON/JSONL before SQLite.
User-facing CLI: goal, plan, ask/chat (run remains compatibility alias).
```

## 6. Architecture Notes

```text
Runtime layers: CLI, command router, harness (Run/Execute/AgentLoop), context layer, agent layer,
tool layer, evaluation layer, persistence layer.
Root runtime state lives in .asteria/.
Primary user workflow: init -> goal -> status -> resume/decide -> review -> accept.
Maintainer/CI: gate, validation-run, acceptance, evidence-bundle (hidden from default help).
```

## 7. Commands

Use these commands when available:

```yaml
install: None
run: None
test: pytest
lint: ruff check .
typecheck: mypy src
build: None
format: ruff format .
```

Phase 0 verification:

```yaml
doc_contracts: pytest tests/unit/test_documentation_contracts.py -q
```

If a command is unknown, do not invent it. Detect it from project files or create a DecisionPoint when the choice matters.

## 8. Coding Conventions

- Follow existing project style before introducing new style.
- Prefer small, verifiable Vibe Slices (see benchmarks/vibe_slices.json).
- Add tests when behavior changes.
- Avoid unrelated refactors and DO_NOT_TOUCH files.
- Keep generated code readable and maintainable.

## 9. UI and Experience Conventions

- Studio is a first-class client of runtime evidence (not a second runtime).
- Default UX: Goal / Plan / Ask + session narrative; Inspector for raw evidence.
- Do not expose maintainer gate vocabulary on the main thread.

## 10. Safety Boundaries

Protected paths:

```text
.env
.env.*
secrets/
.git/
*.pem
*.key
id_rsa
id_ed25519
```

Agents must not:

- Read secrets without explicit approval.
- Run destructive shell commands.
- Install global packages.
- Push secrets, credentials, protected files, local route/key files, `.env*`, private keys, or other sensitive local data to remote repositories.
- Push code or documentation only when the user explicitly asks for it, after checking the staged diff does not include protected paths or real secrets.
- Deploy to production.
- Send sensitive local data to network services.

## 11. Decision Policy

Default decision granularity:

```text
balanced
```

Create a DecisionPoint for major product direction, stack tradeoffs, privacy/security/network, scope expansion, high cost, irreversible changes, and budget hard-stop (0.90).

## 12. Cost Policy

Default budgets:

```yaml
max_model_calls_per_goal: 200
max_tool_calls_per_goal: 1000
max_iterations_per_goal: 32
max_repair_attempts_per_task: 4
max_replans_per_task: 2
context_compaction_threshold: 0.75
hard_stop_threshold: 0.90
```

See full policy in prior AGENTS sections; long-task autonomy is governed by goal progress, context pressure, repair/replan limits, permission risk, provider health, and loop detection.

## 13. Agent Operating Rules

All agents must:

- Read AGENTS.md + 研发总计划 + ACTIVE_SLICE before acting.
- Produce durable artifacts, not only chat text.
- Respect triage lock and reference briefs.
- Verify changes before reporting success (pytest/smoke for the slice).
- Update ACTIVE_SLICE handoff when pausing.

## 14. Handoff Requirements

Before long pauses, preserve: goal, definition of done, ACTIVE_SLICE, modified files, verification results, failures, open risks, next actions.
