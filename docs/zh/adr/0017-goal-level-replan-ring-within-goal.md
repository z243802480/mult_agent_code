# ADR-0017 · Goal 级 replan 环闭合 = 目标内重分解，非 scope 扩张

- 状态：Proposed（2026-07-05）
- 关联：[[0010]] 开放 Agent Loop · [[0015]] 连续 Session 是产品架构 · [[0016]] 认知归模型/边界归状态 · S78 repair 环 · S79 task-level replan 环
- 授权：用户 2026-07-05「授权你解锁推进」+「继续吧」（承 2026-07-04 解冻，记忆 `freeze-lifted-autonomous-loop`）

## 背景

自主环三环里，S78 闭 repair 环、S79 闭 **task-level** replan 环（模型在任务循环内换方法重试）。第三环 **goal-level replan**——当一个任务 `blocked` 后，重规划**任务分解**（supersede 失败任务、合成修复任务、重连依赖）——此前判为「涉新任务合成/DecisionPoint，须先界定边界」而人类门控（今天：run 停在 resumable boundary，荐人类敲 `asteria replan`）。

本 ADR 的触发点是一次亲验 `ReplanCommand`（`commands/replan_command.py`）的关键发现，它**推翻了「goal-level replan = scope 扩张」的默认假设**。

## 关键发现：§2 人审边界已编码在 ReplanCommand 内部

`ReplanCommand` 不是无界的新目标合成器，它由构造即自限：

1. **目标不可变**：只读 `task_execution_evidence` / `task_failures` 造修复任务，**从不读写 `goal_spec.json`**。它在**同一 goal 内**重分解，不新增/改写目标 → 本质不是 Non-Goals 里的「silently expand the project」。
2. **只碰 blocked 任务**：`_candidate_failures` 仅收 `status=="blocked"` 且证据未被处理过的任务（`replan_command.py:223`）。不动 done/running/ready。
3. **lineage 有界 → 自动升 DecisionPoint**：`_replan_lineage_count(root) >= max_replans_per_task`（默认 2）→ 不再造任务，改**建 DecisionPoint 交人审**（`:102-122`）。同一失败血脉不会无限重规划。
4. **风险失败类型 → 自动升 DecisionPoint**：`_needs_decision`（policy_decision / tool_permission / repair_exception / exception）→ **建 DecisionPoint 交人审**（`:124-141`）。策略/权限/异常从不被自动吞掉。
5. **修复任务是收敛的**：`_task_from_failure` 造 `task_kind="implementation"` 的修复任务、superseded 原任务、`_rewire_dependents` 重连依赖，`verification_policy.required=True`。是朝**同目标**的收敛重试，非发散扩张。

**结论**：`ReplanCommand` 已经把「哪些自动、哪些必须人审」编码进自身。所谓「goal-level replan 环闭合」**不是造新能力、不是放开边界**，而是把 run 级「停下让人类敲 `replan`」这一步，替换成「自动调用 `ReplanCommand`（在其既有边界内）」——risky 情形它自己弹 DecisionPoint 暂停 run。

## 决策（ADR-0016 三分类映射）

| 元素 | 分类 | 处置 |
|---|---|---|
| 「要不要 replan / 怎么重分解」 | §1 认知 | 归模型 + ReplanCommand 的证据启发式；不是新的 FSM |
| **目标内重分解**（supersede blocked→修复任务，goal_spec 不变） | §1 认知（在 goal scope 内） | **可自动闭合** |
| lineage 达 `max_replans_per_task` | §2 边界（保险丝→人审） | **DecisionPoint，不变** |
| policy/permission/exception 失败 | §2 边界（人审） | **DecisionPoint，不变** |
| provider transient 故障 | §2 边界 | run 层已单列停机荐 `model-check`，**不变** |
| goal_spec 改写 / 新增目标 / 扩 scope | §2 边界（Non-Goal） | **ReplanCommand 结构上就不做；若未来要做须另立 ADR + DecisionPoint** |
| run 迭代次数 | §2 保险丝 | `max_iterations_per_goal` 外层已保 |

**落地判据**：goal-level replan 环 = 在 run 级 block 边界（provider 检查之后）flag 门控地自动调 `ReplanCommand`；创建了修复任务（ready>0）则继续 run 循环，创建了 DecisionPoint（run 转 paused）则停下交人，无可行证据则如今日停。**flag 默认关、可逐字节回退。**

**合规清单（触此环的改动必须逐条过）**：
1. 不读写 `goal_spec.json`（目标不可变）——由复用 ReplanCommand 保证。
2. DecisionPoint 升级路径（lineage cap / 风险失败）一字不改。
3. 外层保险丝：run `max_iterations_per_goal` + ReplanCommand lineage cap 双重有界，无新增无界循环。
4. flag 默认关；关时行为逐字节同今日（停在 resumable boundary 荐 resume）。
5. provider transient 停机路径不变（先于 replan）。

## 后果

- 正面：自主环第三环闭合，run 遇可自动修复的 blocked 任务不再每次交还人类；飞轮/经验积累闭环。风险低于预期——边界早已编码。
- 负面/风险：run 级编排（`run_command._execute_until_no_ready`，freeze-lift 已解锁）新增一条自动 replan 分支；错误实现可能在 DecisionPoint 情形误续跑。→ 由「创建 DecisionPoint 即停」的判定 + 单测覆盖（decision→pause / repair-task→continue / no-evidence→stop / opt-out→今日行为）守住。
- 冻结不变：北极星/swarm/parallel_writes 全局默认、goal_spec 改写、新增目标——继续冻结。

## 回滚

flag 默认关即天然回滚（关 = 今日行为）。若开启后 Golden-Task eval（0010 §4）显示自动 goal-replan 使可测正确性下降 / DecisionPoint 误跨，关 flag 退回人类门控 `replan`。
