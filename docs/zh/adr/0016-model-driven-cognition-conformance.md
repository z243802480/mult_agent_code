# ADR-0016：认知归模型 / 边界归状态 —— 可执行合规判据（强化 0010 与 0015）

**状态**：Accepted
**日期**：2026-07-04
**关系**：扩展并强化 [ADR-0010](0010-open-agent-loop-and-evaluation-boundaries.md) 与 [ADR-0015](0015-session-loop-is-product-architecture.md)；不 supersede 二者。

## 背景

ADR-0010（开放 Agent Loop + 分层硬边界）与 ADR-0015（连续 Session Agent Loop 是产品架构）
已经把方向拍死：`model → tool → observation → model`，Runtime 只在动作边界执行权限/沙箱/
预算/持久化，**不替模型决定语义下一步**；Plan/Review/Debug/Accept 是显式动作，不是默认自动
恢复流水线。

但这两条 ADR 停在**原则级**，没有留下"什么算把认知写成状态机"的**可执行判据**。缺了这颗牙，
S77–S79 的实现就悄悄漂回了 0010/0015 明令要溶解的那台状态机：

| 漂移点 | 位置 | 违反 |
| --- | --- | --- |
| `repair` / `replan` 被当作独立 next-action，并映射弹射到独立 CLI 命令（`repair→debug`、`replan→replan`） | [agent_loop_decision.py:202](../../../src/asteria_runtime/core/agent_loop_decision.py) `recommended_command_for_next_action` | 0015：模型在同一循环里驱动，而非命令编排 FSM。把"修复"具体化成一个"态"本身就是状态机 |
| `repair_budget_exhausted` / `loop_no_progress` 作为确定性终止，把"撞预算"当认知终点 | [execute_command.py:1646/1671](../../../src/asteria_runtime/commands/execute_command.py) `_handle_auto_repair_round` | 0010 §1/§2/§3：repair 次数是 SLO 不是闸；no-progress 必须是"同类失败 + 零新证据"，不是撞小数字 |
| `_overall` 用代码算 `0.9/0.6/0.2` 标量分来 gate"算不算做完" | [review_agent.py:242/261](../../../src/asteria_runtime/agents/review_agent.py) `_overall` | 0015 §4：Review 是显式动作，完成与否由模型看证据判断；代码算的标量是认知-FSM |

注：`correctness_eval` 的**真实通过率**不是漂移——它是合法的**证据**（喂给模型/人看），错的是
把它接成**自动 gate**。证据与闸门的区别是本 ADR 的核心。

> **合规状态更新（2026-07-09）**：上表点名的三处漂移**已全部消解**——RA7b 删除 FSM 认知脚手架时，
> `agent_loop_decision.py`（含 `recommended_command_for_next_action` 弹射命令）、execute 级 auto-repair/replan
> 环、`review_agent._overall` 的 `0.9/0.6/0.2` 算分 gate 均已删除；立真身脊梁（`model_driven_turn`）为唯一执行
> 路径，`review_agent` 完成判决改由 `CorrectnessEvalCommand.score_signal`（真退出码证据）驱动。落地登记见
> [ADR-0022](0022-model-driven-spine-landed.md)。上表保留为**历史漂移记录**，不再代表现状代码。

### 主流实证（2026-07-04 复核 Claude Code / Cursor / OpenCode / Aider）

ADR-0010 已引 Claude Agent SDK / Codex / OpenCode。本次复核四个产品，主流范式与本 ADR 三分类一致：

- **认知归模型（Claude Code / Cursor / OpenCode）**：
  - Claude Code 官方明说三"阶段"(gather context→take action→verify) 是**概念桶不是编码闸**——
    "These phases blend together… Claude decides what each step requires"；repair 就是模型看 tool 结果
    自己再来一轮；完成"until the model decides the work is complete"，**无 in-code 分数**；Plan Mode 是
    **只读权限模式 + prompt 引导**，`ExitPlanMode` 是模型的一个 tool call；TodoWrite 是便签**不驱动控制流**
    （[how-claude-code-works](https://code.claude.com/docs/en/how-claude-code-works)、[building-effective-agents](https://www.anthropic.com/research/building-effective-agents)）。
  - OpenCode 是单模型 tool 循环（`streamText`+`stopWhen`），LSP/lint 诊断**喂回给模型**决定下一步，
    "no numeric review score; completion is implicit"；Plan/Build 只是**权限档**，Tab 软切换
    （[opencode.ai/docs/agents](https://opencode.ai/docs/agents/)、[…/lsp](https://opencode.ai/docs/lsp/)）。
  - Cursor Agent 同形：失败当 tool 结果喂回、模型决定修，打分只在训练期/多 agent 事后择优
    （[cursor.com/blog/agent-best-practices](https://cursor.com/blog/agent-best-practices)）。
- **边界才显式（全体一致）**：权限/审批档、沙箱、diff 接受-拒绝、checkpoint/回滚、context 压缩+
  防抖硬停、JSONL 持久化/resume、迭代上限**当保险丝**——正是本 ADR §2 的"边界"清单。

### 两条反教条 nuance（本 ADR 据此收敛，避免过度纠偏）

1. **长任务的 definition-of-done 是合法脚手架，凭空算分才是错。** Anthropic 自己的长任务 harness
   **显式加了 200+ 项 pass/fail checklist**，正因为纯模型判断有"后来的实例一看有进展就宣布做完"的
   失败模式（[effective-harnesses-for-long-running-agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)）。
   故本 ADR §3 的红线**不是"禁止一切完成脚手架"**，而是：DoD 必须**由真实验证证据填充**（如 correctness
   真实通过率对着显式验收项），**不得**是 `review._overall` 那种**凭空 `0.9/0.6/0.2` 常量**。前者是证据、
   可为长任务把关；后者是伪造，删。
2. **较弱模型可能需要更多脚手架——但由 eval 决定，不由反射决定。** Aider 是主流里的"更编码"一端：
   刻意用编码 edit-format + `auto-lint`/`auto-test`→喂回→修的**编码循环**，**正因为要支持较弱模型**
   （[aider.chat/docs/usage/lint-test](https://aider.chat/docs/usage/lint-test.html)）。我们路线目标是
   glm/minimax（弱于前沿），故**不照搬 Claude Code 的纯模型驱动**：认知**默认**归模型；仅在 0010 §4
   的 Golden-Task eval **证明弱模型确实需要**处，才保留确定性脚手架（verify→feedback 循环、DoD checklist）——
   **既不反射式加，也不反射式拆**。

即：成熟产品把 plan/execute/verify/repair/done 的**认知默认放进模型**，把确定性脚手架（权限/沙箱/
审批/回滚/迭代上限，以及长任务的**证据型** DoD）留作模型外的显式机器；脚手架的多寡由 eval 而非直觉决定。

## 选项

- **选项 A（本 ADR）**：不重新决策，给 0010/0015 补一套**可执行的三分类判据 + 合规清单**，
  点名现有漂移，钉一刀可回滚的纠偏。代价：需要动 DO_NOT_TOUCH 的 `execute_command.py` /
  `run_command.py`（已由用户 2026-07-04 解冻自主环授权覆盖）。收益：漂移从此是"回归"不是"特性"，
  评审可机械判定。
- **选项 B**：只在 chat 里口头重申 0010/0015。代价：无牙，S80 会再次漂回；风险高。
- **选项 C**：推倒 S78 自主环重写。代价：大、不可控、违背"有界可回滚"；风险高，拒绝。

## 决策

采用选项 A。任何控制流元素，进入实现前必须被归入且仅归入下列**三类之一**：

### 1. 认知（交给模型的涌现，禁止写成 FSM）

"要不要规划 / 要不要修 / 要不要再验 / 算不算做完 / 下一步做什么"——一律由模型在
`model → tool → observation → model` 循环里，基于最新 observation 自行决定。

- **不得**存在把上述判断具体化的**闭包 action 枚举**、**独立弹射命令**或**代码算的完成标量**。
- 失败的 verification/tool 结果**只是一个 observation 喂回同一循环**；模型接着出下一个 tool call。
  "repair" 不是一个需要存在的"态"。

### 2. 边界（显式确定性状态，保留）

只有"模型管不了、也不该管"的东西才配有硬状态（与 0010 §1 一致）：

- 用户权限、protected paths、sandbox、网络、不可逆操作闸。
- 总成本预算、context hard-stop（0.90）、显式 deadline、用户配置的 max turns —— 均为**保险丝**。
- **可证明的无进展**：连续同类失败且没有新 observation/artifact/verification/决策信息。
- 持久化 / resume（JSONL 决策·执行·观察，用于恢复与审计）。
- promotion 人审、candidate/accept finalize。

达到任一边界时：写明停止原因、保留 Session/Run 状态、支持 resume；**不得把"撞边界"伪装成
任务语义完成或失败**（0010 §1 原文）。

### 3. 证据（喂给模型 / 人；只有"证据型"才可把关，"伪造型"一律删）

`correctness` 真实通过率、telemetry、SLO 计数、repair/replan 次数——是**观测与优化指标**，
surface 给模型和用户判断用。红线精确划在**证据来源**，不是"是否把关"：

- **禁止**：凭空/不透明的标量 gate——如 `review._overall` 的 `0.9/0.6/0.2` 常量、按 repair 次数撞小数字
  就判失败。这类"伪造认知"直接删。
- **允许（视作 §2 边界）**：**由真实验证证据填充**的显式 definition-of-done（例：correctness 真实通过率
  对着显式验收项 pass/fail），可为**长任务**把关（见下方 nuance #1）。它必须透明、可查证、可 resume，
  本质属于 §2 的显式边界，而非藏在代码里的认知。

### 合规清单（评审机械判定）

改动触及 loop / gate / 预算 / 停止条件时，PR 必须逐元素标注它属于 §1/§2/§3，并满足：
- §1 元素：无 enum-action、无弹射命令、无算分 gate。
- §2 元素：撞线写原因 + 保状态 + 可 resume，且不冒充语义结论。
- §3 元素：只 surface，不 auto-gate。
- 改自主边界/默认路径/gate/预算/停止条件的，仍须走 0010 §5 证据检查（读计划+ADR、调研≥1 个成熟产品公开机制、标明类别、说明 eval 证明与回滚）。

## 后果

- **第一刀（有界·可回滚）**：溶解 auto_repair 路径里的 `repair`/`replan`-as-command——
  把失败 observation 喂回同一循环、由模型决定下一个 tool call；`repair_cap` 仅保留为
  **可 resume 的保险丝**（写 `exit_reason` + 保状态 + 可续），不再是语义终止态；`_overall` 停止
  用常量算分 gate，改为把 correctness 证据交给模型/显式 Review 动作。全部落在既有 `auto_repair`
  开关后（默认 off、可逆）。
  - **参考形态**（reference-first，AGENTS.md）：codex-rs `session/turn.rs::run_turn` 的单 `loop{}` +
    `needs_follow_up` 布尔——模型出 tool call 则带结果再转、只出消息则 `break`；失败经 `RespondToModel`
    当 tool 输出喂回，**无独立 repair 分支**。我们的循环骨架（`AgentLoopRunner.run`）已同构，第一刀是
    **删掉外层把 repair/replan 弹成命令的那段**，让它退回这个形态。
  - **差异化保留**：Codex/Claude Code 单轮工具不做 in-code 正确性 gate；我们的 `correctness_eval` 真实
    通过率作为**长任务证据型 DoD** 是**有意的差异化**（非照抄），符合 §3-允许 与 nuance #1。
- `execute_command.py` / `run_command.py` 属 DO_NOT_TOUCH：**本 ADR 即为触碰它们做合规纠偏的
  总计划授权**（对应用户 2026-07-04 解冻自主环）。仅限本 ADR 范围内的纠偏，不做无关重构。
- 文档与代码不得再把固定状态机、per-action 命令弹射或算分 gate 描述为认知路径。

## 回滚或替代条件

- 按 0010 §4 用 Golden Tasks 配对对比：若模型驱动 repair 在成功率 / P50-P90 耗时 / 成本 /
  恢复一致性上**可测地更差**，将第一刀退回（`auto_repair` 关闭）并重开 ADR 讨论。
- 若出现无法用"边界/证据"表达、又确需确定性的新场景，进入新 ADR，不得就地在认知路径加分支。
