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
当前 ACTIVE_PHASE：大重塑 Part B（前端拉齐 + 诚实化收敛）。S77 的 P1 主体已闭合。
当前 ACTIVE_SLICE：G17（图片附件·1.2.96/1.2.98 **已收官**）。**2026-07-17 用户拍板后开的新队列**：G8 = **两者都要**（档位默认 + 可覆盖具体模型·分两刀）、G6 刀二 = **编辑框→喂模型重出**（编辑手感·模型语义·ADR-0016 相容）。进度：**1.2.103 warm worker 接通 + 权限档按数据穿透**（做 G8 追接线时撞见的真 bug：暖路从出生起不可达）→ **1.2.104 G8-a 档位选择器**（冷/暖两路真实用户路径均有探针实证）→ **1.2.105/1.2.106 G8-b 两刀**（运行时通道+CLI·Studio UI+BFF·**开工调研推翻了路线图为 G8-b 写的两条路**·见 1.2.105）⇒ **G8 全案收官**（冷/暖两路真实用户路径均有探针实证）→ **1.2.107 G6 刀二**（编辑框→喂模型重出·零后端·不写任何计划文件 ⇒ UI 不说谎由构造保证）⇒ **用户拍板的队列已全部跑完**。同批已收官：自审 8/8（1.2.97/1.2.99/1.2.100）、索引虚构纠正（1.2.101）、§16.1「近期第一批」结清（1.2.102）。已判**不做**并留痕：G18（等证据·8ae2b52）、`model_call_logger` O(N²)（量出 0.02%·1.2.101）、`package-check` 真构建（真闸已在 release.yml·1.2.102）。

**本段是索引，不是记账。细节一律去真源查，勿在此复述**（复述会漂，已犯过：见 1.2.95）：
- 执行计划 + 逐刀 changelog（**唯一真源**）：`docs/zh/研发总计划.md` §16 / §16.1 / changelog 1.2.30–1.2.107
- 前端对标差距与路线（G1–G20 分档 + 现状标记）：`docs/zh/前端对标主流差距与实施路线.md`

**已收官**：Part B 的 B4–B10（专家集群可见 / 护栏 hook / 模型 todo / 成本归属 / schema 防漂 /
完成闸判据 / 上下文预算快照 / 专家进 worker 树）。前端对标 Wave N1 安静可信赖（G1/G2/G3/G9/G20·
1.2.83）、N2 评论即指令（G4/G5·1.2.84）、N3 计划与回滚（G6刀一/G7/G10/G11·1.2.85–1.2.89）。
P2：G15 回放导出（1.2.90）、G14 记忆只读（1.2.91）、**G17 图片附件全案**（CLI 1.2.96 + Studio 粘贴 1.2.98）、自审清理批（1.2.97 修 6 条 + 1.2.99 清 8 条）、**F5 自审 8/8 角度全跑完**（1.2.100 收官·末轮又修 6 条含两条计数不实）。主区渲染/叙事序/即时感/
对比度四轮打磨见 1.2.64–1.2.69、1.2.79–1.2.82。投运侧：单口生产构建（1.2.60）、LICENSE 接线
（1.2.61）、发布绿灯门（1.2.62）、beta_safe 红队（1.2.63）。ADR-0029 两机制默认 ON：mid-run steer
（1.2.76）、warm worker（1.2.75 翻默认，但**探针证其从出生起不可达、零 run 经手**——1.2.103 才真正
接通并让权限档按数据穿透）。

**仍开着**（⚠️ 理由**只写核实过的**；核实不了就写"源里没说"——**别把空槽填满**。这条护栏是有来历的：
本块原先 G6/G8 的理由是 2026-07-16 压缩时**虚构**的、带假行号，1.2.101 用代码核实后重写；那两条已随
1.2.104–1.2.107 收官移除）：
- G12/G13/G16/G19 均 P2。**2026-07-17 用户要卡点清单 ⇒ 四条逐个回代码核实（1.2.108），两条被证伪/大改**：
  G12 属实（但 `TaskGraphScheduler` 是同名不同物）/ **G13 原句只对三分之一**（储存层+执行机器已就位·真缺
  评审层+对账层一对多·且 merge gate「同 scope 必冲突」不变式**方向相反**）/ G16 属实（**真卡点是鉴权不是
  bind**）/ **G19 前提已证伪**（candidate 隔离为「专家并发写」而建·终结于 promote 拷回**共享** source_root
  ⇒ **runtime 也没这能力**，不是「Studio 无表达」）。**四者性质各异，别打包成一句**——逐条见路线表。
- ~~跨 run 无守卫~~ **✅ 已修（1.2.110·S87·用户「按你建议进行」授权）**：核实 G19 时撞出、探针坐实
  （1.2.109·两会话真起两个 run·落在两个不同 OS 进程 ⇒ 进程内 RLock 结构上拦不住）。修=`startRuntimeJob`
  唯一咽喉，同工作区同时只允许一个**能改用户文件**的 run；只读 mode（chat/review/plan/decide）不受影响；
  **未知 mode 当写者**。**残留洞已闭合（1.2.111·S88·用户 2026-07-18 授权动 DO_NOT_TOUCH）**：跨进程
  文件锁（OS 持有·进程死亡自动释放）落在 CLI 三咽喉（continue_run/ExecuteCommand.run/promotions 非 list），
  连 **CLI-vs-Studio**（S87 也护不住的组合）一并覆盖；`decide` 未纳入（只写 .asteria 决策记录·边界记在
  模块 docstring）。详见路线表 §4 G19 条。
- **OS 沙箱 = 唯一剩余 P0**——分阶段方案已出：**ADR-0030（Proposed·2026-07-18·待拍板）**，
  S-A 进程围栏(天级)/S-B AppContainer 断网限写(先 spike)/S-C 云(维持冻结)；主观视觉手感需用户目视。

当前审计签字：docs/zh/reports/completion-reaudit-20260718.md（**实现≈80%**·同框架对照 S77 的 ≈71%·15 子系统逐断言回代码核实·残余债按咬人程度排序在其 §3）。历史基线：docs/zh/reports/S77-commercial-readiness-audit-20260704.md（≈71%、市场化 37→利基 43-45·其 P1④⑥已过期，读须对照 changelog）。两份都是快照，引用前对照 changelog。
执行顺序：Part B 前端拉齐——**用户拍板的队列已跑完**（G8 全案 1.2.104–1.2.106·G6 刀二 1.2.107）。**剩余项全部卡在用户**：①主观视觉手感需目视 ②G12/G13/G16/G19 需真 friction 证据 ③OS 沙箱 P0 → P0 沙箱（唯一剩余 P0·按内部发动机定位已降级）→ 利基 Beta
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

`.git/` 的**唯一例外（2026-07-17 显式 sanction）**：G7 影子快照（`studio/lib/git.mjs`）经
`GIT_INDEX_FILE` 指向临时索引调 `git` 写对象库，并在 `refs/asteria/snapshots/` 下打 ref。
这**不是**该条禁令要防的事——禁令防的是改写用户的版本历史或偷读凭证。快照**只增不改**：
用户的暂存区、HEAD、分支、既有 ref 零扰动，`.asteria/` 双向排除，且全程经 `git` 自己的命令
（不手写 `.git/` 里的文件）。**此例外仅限该文件的三个快照函数**；其余任何对 `.git/` 的读写
仍然禁止，尤其禁止手动改 HEAD/分支/索引或读 `.git/config` 里的凭证。

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
