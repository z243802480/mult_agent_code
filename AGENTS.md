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
执行计划唯一入口：docs/zh/研发总计划.md（当前状态见 §16 / §16.1）
当前 ACTIVE_PHASE：大重塑 Part B（前端拉齐 + 诚实化收敛）（S77 的 P1 主体已闭合，见下）
当前 ACTIVE_SLICE：B10（Part B 前端拉齐剩余：上下文预算快照 / 专家进 worker 树）。已落地 B4–B9（专家集群可见 / 护栏 hook / 模型 todo / 成本归属 / schema 防漂 / 完成闸判据）。权威定义见 研发总计划 §16 + changelog 1.2.30–1.2.47（本处为镜像·单一真源）
当前 Brief / 审计签字：docs/zh/reports/S77-commercial-readiness-audit-20260704.md（实现≈71%、市场化 37→利基 43-45）。⚠️ **该报告的 P1④「自主环未闭合」/ P1⑥「DebugAgent 占位」已过期**——三环+软保险丝第四环已闭合且随权限档默认开（changelog 1.2.31/1.2.33/1.2.38），`agents/debug_agent.py` 已删（RA7b）。读该报告须对照 changelog。
执行顺序：Part B 前端拉齐剩余（上下文预算快照 / 专家进 worker 树）→ P0 沙箱（唯一剩余 P0·按内部发动机定位已降级）→ 利基 Beta
冻结（仍有效）：新编排 Wave、任务批 disjoint-write 调度（task_graph 冻结点·需重建冲突检测）、无真实 friction 证据的 Studio 新功能、北极星/swarm/12-Agent、真 cloud VM background。
**已解冻并落地（勿再当冻结项）**：①B1-a/B1-b 并发专家（含隔离并发写）**全局默认开**·随权限档·merge-gate 保护（2026-07-14·ADR-0023·v1.2.33）；②**自主环四环**（auto_repair / auto_replan / auto_replan_goal / auto_continue 软保险丝）**默认随权限档开**（auto/reviewed_auto → ON·ask_everything → OFF·2026-07-13/14·ADR-0017/0027·v1.2.31/1.2.38）；③**auto-accept 默认开**——`run` 不再为 promotion 停下等人审（2026-07-13 用户知情同意·推翻 2026-07-02 的「run 必停」DecisionPoint·v1.2.15）。高危 shell/deploy/push 仍走常开硬 guard。
```

Any agent must read `docs/zh/研发总计划.md` before code or doc changes. Do not start a new
orchestration wave, enable global parallel writes, or add maintainer commands unless the master
plan todo explicitly allows it.

Reference-first: before each Vibe Slice, read `benchmarks/reference_briefs/Sn.md` (create if missing).
No brief → no coding. Learn from OpenCode / Claude Code / Codex-rs mechanisms; do not reinvent wheels.

## 3. Code Triage Lock (Phase 0–2)

**锁的口径已从「文件名」改为「能力」**（研发总计划 §6 是权威；**禁止用文件名或历史代码量保护重复责任**）。大重塑（ADR-0022）的用户授权**显式覆盖本表**：FSM 认知脚手架已按授权整体删除，`execute_command.py` / `run_command.py` / `gate_status_command.py` 已在授权范围内大改。**下面这张表是能力口径的镜像,不是文件白名单。**

| Tier | Rule |
| --- | --- |
| **KEEP_CORE** | 别删这些**能力**: run/execute/plan/chat/status/review/accept, 立真身脊梁(`model_driven_turn`), user_progress_logger, runtime_progress, candidate/merge/promotion, studio server/Thread/Composer, schemas, core tests。⚠️ 原文写的 `agent_loop_*` **已按 ADR-0022 授权全删**(FSM 认知脚手架)——保护的是"执行循环这个能力"，不是那些文件名 |
| **KEEP_PLACEHOLDER** | 别扩展: sandbox rollout(OS 级沙箱仍是 P0 未做), 已弃用的 Agent 类, legacy event_logger fallback。⚠️ 原文的 `disjoint_write real parallel` **已解冻并默认开**(ADR-0023)，不再是 placeholder |
| **HIDE_NOT_DELETE** | 对用户隐藏、CI 保留: daily/weekly/roadmap, gate/acceptance/validation/real-model-*, evidence-bundle |
| **MERGE_OR_TRIM** | Phase 1b only: delete runs_command.py; merge validation→validation-run; trim CLI aliases; remove Studio fake completion |
| **DO_NOT_TOUCH** | 默认不重构: `execute_command.py`, `run_command.py`, `gate_status_command.py`, acceptance/real_model stack。**例外(已授权)**: ①追加 user_progress 字段/卡片一律允许；②大重塑 Part A/B 的脊梁与自主环改动（2026-07-04 解冻、2026-07-05 gate_status 解锁）。**授权之外仍禁止顺手重构**——不夹带无关格式化/重排 |

Full table: `docs/zh/研发总计划.md` §6。**本表与 §6 冲突时以 §6 为准。**

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
Autonomy: 随权限档绑定。auto / reviewed_auto → 自主环 + auto-accept 默认 ON（失败自修/重规划/续跑，
  promotion 自动 finalize，不再停下等人审）；ask_everything → 全部 OFF。
  ⚠️ 本行原文写「promotion … must interrupt」——那是 2026-07-02 的 DecisionPoint，已于 2026-07-13
  经用户知情同意推翻（set-and-forget 产能观）。**仍然必须打断人的只剩**：高危 shell / deploy / push
  / 不可逆外部副作用（常开硬 guard，不随权限档放松）+ 预算 hard-stop。
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
