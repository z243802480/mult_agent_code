# ADR-0027 · 软保险丝续跑环 = max_rounds 是软预算不是必须打断的硬门

- 状态：Proposed（2026-07-14）——**设计立场 Proposed，代码已落地于 `agent_loop.auto_continue` flag 后（默认按权限模式绑定：auto/reviewed_auto 开、ask_everything 关·可逐字节回退）。**
- 关联：[[0016]] 认知归模型/边界归状态 · [[0017]] goal-level replan 环（同族第三环）· S78 repair 环 · S79 task-level replan 环 · 记忆 `freeze-lifted-autonomous-loop`
- 授权：用户 2026-07-14「全自动越过 max-iterations 自动续跑，去接自主环」（承 2026-07-04 解冻）

## 背景

真栈复杂任务观察发现（S77 收尾）：`--permission-level auto`（全自动 autopilot）下，agent loop 跑满单任务软轮次预算 `max_rounds`（`model_driven_turn` 的 `for iteration in range(1, max_iterations+1)`）就停下——`model_driven_turn` 产 `budget_exhausted` → `execute_command` 翻成 `exit_reason="max_rounds"` + `status="blocked"` → `run_command` 在 resumable boundary 弹 `continue` 门，**每次续跑都要人确认**。这与「设权限→自动连跑、只在计划/高危打断」的低负担产能观（记忆 `low-burden-set-and-forget-ux`）直接冲突。

## 关键发现：max_rounds 不在「必须打断」的硬门清单里

研发总计划 §16（line 70 / 325）明确「必须打断」的硬闸门只有：**权限 / sandbox / 不可逆动作 / 预算 hard-stop（`max_model_calls_per_goal × hard_stop_threshold=0.9`）/ context hard-stop / 可证明的无进展循环**。

`max_rounds`（=`max_rounds_per_task+4`）是**软成本保险丝**，不在此列。撞它的任务通常**有进展**（改了文件）只是没在本批轮次内满足完成契约——它需要的是**再给一批轮次**，不是停下问人，也不是当失败去 replan（重分解一个正在推进的任务是错的恢复动作）。

## 决策（ADR-0016 三分类映射）

| 元素 | 分类 | 处置 |
|---|---|---|
| 「要不要继续推进」 | §1 认知 | 模型停手（`done`）才是完成；软轮次用尽只是批次边界 |
| **max_rounds-blocked 任务续跑**（reset ready 再喂一批轮次，goal/plan 不变） | §1 认知（goal scope 内） | **可自动闭合**（auto/reviewed_auto 默认开） |
| 预算 hard-stop（model_calls ≥ 0.9） | §2 边界（保险丝→人审） | **必须打断，不变**（`_auto_continue_soft_fuse` 显式检查，撞顶即 fall-through 交 `_budget_guard`/DecisionPoint） |
| 每任务续跑上限 `max_soft_fuse_continues_per_task`（默认 6） | §2 保险丝 | 达顶升 resumable boundary 交人审（防原地空转无限续跑） |
| 恢复循环计数 `max_inner_cycles` | §2 保险丝 | 既有外层护栏，续跑共享，不变 |
| tool_failed / policy / permission / provider 失败 | §2 边界 | **非软保险丝**——续跑环显式只认 `exit_reason=="max_rounds"`，其余一律 fall-through 交 replan 环/今日路径 |

**落地判据**：软保险丝续跑环 = 在 `run_command._execute_until_no_ready` 的 block 边界（provider 检查之后、**replan 环之前**）flag 门控地读 `agent_loop_run_summary.json` 的 `exit_reason`；仅当 `=="max_rounds"` 且预算未撞 hard-stop 且未达每任务续跑上限 → 用 `TaskBoard.update_status(blocked→ready)` 重置该任务、`continue` 重入 inner 循环重驱动；否则 `"stop"` 落到 replan 环/今日 boundary。**flag 默认按权限模式绑定、可逐字节回退。**

**合规清单（触此环的改动必须逐条过）**：
1. 只认 `exit_reason=="max_rounds"`——tool_failed/policy/permission/provider 一律不碰（正交于 replan 环）。
2. 预算 hard-stop 检查一字不删——撞顶必 fall-through 交人，从不静默越过。
3. 每任务续跑上限 + `max_inner_cycles` 双重有界，无新增无界循环。
4. 续跑计数用 `_execute_until_no_ready` 内存 dict，**不落 task_plan**（避开 schema 双份陷阱，记忆 `schema-dir-runtime-vs-packaged`）。
5. flag 默认关（ask_everything）时行为逐字节同今日（停在 resumable boundary 荐 continue）。
6. `supervised_goal_loop` 的 break-on-blocked 不改——max_rounds 在 run 层就被拦下，只有触顶/真失败才冒泡成 slice-blocked，那时该 break。
7. Studio 侧 `continue` 的 `requiresPermission:true` 不改——真 resumable boundary（触顶/真失败/ask_everything）仍该人确认。

## 后果

- 正面：全自动/监督式自主下，max_rounds 从「每迭代弹门」变为「最多 N 次自动续跑，仅在任务真的收不了尾时升一次门」。低负担产能观落地；自主环补齐软预算维度。
- 负面/风险：一个原地空转（每批 0 净进展）的任务会浪费最多 `cap × max_iterations` 次模型调用才触顶——由每任务上限（默认 6）+ 预算 hard-stop 双重兜住，且模型调用预算（默认 200×0.9）是终极天花板。未来可加「进展 delta 检测」提前熔断。
- 冻结不变：北极星/swarm/parallel_writes 全局默认、goal_spec 改写、新增目标——继续冻结。

## 回滚

`agent_loop.auto_continue=false` 即天然回滚（关 = 今日行为，停在 resumable boundary 荐 continue）。若开启后 Golden-Task eval 显示自动续跑使可测正确性下降 / 空转浪费失控，关 flag 退回人类门控 `continue`。
