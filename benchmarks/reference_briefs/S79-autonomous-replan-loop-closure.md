# S79 · 自主 replan 闭环(第二环)· 执行规格

Slice 类型：解冻后核心增量——闭合自主环的**第二环**。用户 2026-07-05 明确"授权解锁推进"（继 2026-07-04 解冻，见记忆 `freeze-lifted-autonomous-loop` / `work-autonomously-minimal-questions`）。承 S78 repair 环（`S78-autonomous-repair-loop-closure.md`）：让模型在任务循环内出 `replan`（"本任务方法根本错了，需重新构思"）时，在**有界预算内自动让 CoderAgent 换一种方法重试**，而非每次就 block 交还人类；耗尽/无进展才诚实 block。**flag 门控（`agent_loop.auto_replan`）、默认关、可一键回退。**

## 关键边界：两种 replan，只闭 task-level（§2 防 scope 扩张）

| replan 层级 | 语义 | 本环处理 |
|---|---|---|
| **task-level**（`_execute_task` 循环内模型 `replan` 决策） | "我对**这个任务**的方法错了，换个思路" — 同 goal 同任务边界内重新构思 | ✅ 有界自动闭合（本 brief），机制同 repair：重提 CoderAgent |
| **goal-level**（`ReplanCommand` 改写 `task_plan.json` + `_replan_lineage_count`） | **合成新/不同任务** — scope 扩张，越 DecisionPoint 边界 | ⛔ **保持人类门控不动**（`replan_command.py` 不碰）；auto-replan 预算耗尽时 `recommended_command="replan"` 荐人类走此路 |

判据（ADR-0016 §2）：task-level replan = 模型认知（"是否换方法"归模型，§1），不合成 goal-level 新任务、不扩 goal scope、不触不可逆动作 → 可自动。goal-level 新任务合成 = 显式边界，须人审。

## S78 已建的可复用地基（file:symbol:line）
- `_handle_auto_repair_round`（`execute_command.py:1598`）/ `_block_auto_repair`（:1716）：镜像模板。
- `_auto_repair_loop_guard_warns`（:441）：**直接复用**（over tool_results only，no-progress 语义 §3）——replan 与 repair 共享同一"同类失败+零新证据"停止信号。
- `_execute_task` 分派点（:2706 `if auto_repair_enabled and next_action_kind=="repair"`）：紧邻加 replan 分支；:2555 `repair_cap`/`repair_attempts_used`/:2565 `max_rounds` 设置样板。
- `agent_loop` 是宽松 object（`policy_config.schema.json:154 "type":"object"`）→ 加 `auto_replan` **不需改 schema**。
- `replan_result` 观察类型 + `_ACTION_TO_OBSERVATION_TYPE["replan"]`（`agent_loop_observation.py:16/33`）已存在。
- `max_replans_per_task`（`policies.default.json:13` 默认 2）已在 budgets。

## 设计（最小 · 可逆 · 不改 cost_report schema）

| # | 站点 | 分类 | 改动 |
|---|---|---|---|
| R1 | `agent_loop.auto_replan`(bool,**默认 False**) + `_auto_replan_enabled` + `_max_replans_per_task`(读 `budgets.max_replans_per_task`) | 配置/helper（additive） | 关时逐字节同今日 |
| R2 | `_handle_auto_replan_round` + `_block_auto_replan`（镜像 repair 孪生） | 核心路径 | no-progress guard **先判**（复用 `_auto_repair_loop_guard_warns`）→ `loop_no_progress`；否则局部 `replan_attempts_used>=replan_cap` → `_block_auto_replan(exit_reason="replan_budget_exhausted", recommended_command="replan")`；否则写 `replan_result`(pending,`next_recommended_action="tool"`) + 进度事件(`transcript_kind="replan"`)，返回 `(True,obs,None)` |
| R3 | `_execute_task`：`auto_replan_enabled`/`replan_cap`/`replan_attempts_used=0`；`max_rounds` 开时再 `+2*replan_cap`；:2706 后加 `elif auto_replan_enabled and next_action_kind=="replan"` 分支 | 核心路径（config-gated） | 关时 `max_rounds`/分派不变 |
| R4 | `_agent_loop_summary_pressure` budget 快照（:1911）补 `replan_attempts_limit` + `auto_replan_enabled` | additive（前端 parity） | 前端可显有界"已用/上限" |

**有界保险丝**：局部 `replan_attempts_used`（per-task，cap=`max_replans_per_task`）+ no-progress guard。**不新增 budget replan 计数器/不改 cost_report schema**（budget 无 `max_replans_total`，不伪造）。遥测走 run-summary `exit_reason` + 进度事件。

## 终止条件（先触发者胜，全保留）
1. 成功：replan 后轮 `status=="done"` → `exit_reason="completed"`（已工作）。
2. replan 预算耗尽：局部计数 ≥ `max_replans_per_task` → 诚实 block，`exit_reason="replan_budget_exhausted"`，`recommended_command="replan"`（人类 goal-level 重合成=兜底）。
3. 无进展：`_auto_repair_loop_guard_warns` warn → `exit_reason="loop_no_progress"`。
4. 全局 hard-stop：`_should_continue_agent_loop` 已保。

## 单测种子（确定性，无真模型）
- **replan-then-succeed**：Fake client 第 1 轮 tool(fail)→`replan`，第 2 轮 tool(写对，过验证)→`stop`；`auto_replan=on`、`max_replans_per_task≥1` → `completed==1/blocked==0`，`exit_reason="completed"`。
- **replan-budget-exhausted**：Fake 每轮 tool(fail)→`replan`；`max_replans_per_task=1` → 1 次 replan 后 block，`exit_reason="replan_budget_exhausted"`、`recommended_command="replan"`。
- **no-progress**：字节相同失败观察 → `loop_no_progress` 早于数值预算。
- **opt-out 回归**：`auto_replan=off`（默认）→ 现有 replan→block 行为（`exit_reason="replan_dispatch"`）**逐字不变**（可逆性）。

## 边界
- **只闭 task-level replan 环**；`ReplanCommand`（goal-level 新任务合成/lineage）人类门控不动。
- `AgentLoopRunner`/`DebugAgent` 占位不动。
- repair 环（S78）与 replan 环独立预算/exit_reason，互不影响；一个任务循环内两者可先后触发（模型自选 repair vs replan）。
- 落地后前端拉齐（复用 S78 repair 的 Studio 呈现，加 replan 计数）。

## 相关文件
- `src/asteria_runtime/commands/execute_command.py`（`_handle_auto_repair_round` 1598 / `_block_auto_repair` 1716 / `_execute_task` 2706 / `_auto_repair_enabled` 422 / `_agent_loop_summary_pressure` 1911）
- `src/asteria_runtime/templates/policies.default.json`（`agent_loop` 146）
- `src/asteria_runtime/commands/replan_command.py`（goal-level，**不碰**）
- `tests/integration/test_execute_command.py`（种子；opt-out 回归基线）
