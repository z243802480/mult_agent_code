# Slice B1(真栈复验)— 并发专家 readonly-fanout + disjoint-write(真 glm/minimax)

大重塑 Part B。承 ADR-0023(B1-a 并发只读扇出 / B1-b 并发隔离写)——两者此前**只由
`Barrier(2)` 确定性 fake 证过**(证 ThreadPool 真并发),从未在真弱模型栈跑通。计划验证矩阵
(研发总计划 §115-116)明确要求"真 glm+minimax spawn_subagent(fanout+disjoint)"。本刀补齐。

## observed_pattern(行业已验证)
- **Anthropic《Building Effective Agents》orchestrator-workers**:lead 把可并行的独立子任务
  分派给 worker 并发跑,汇总结果。真价值在**真模型会不会自发这么做**,fake 证不了。
- **Claude Code Task 工具**:子代理独立上下文、只回摘要;并发只读扇出无写冲突。
- 真栈验证是本项目发现真 bug 的一贯手段(见 [[ring-realstack-validation-A]])。

## asteria_mapping(我们怎么做)
- 文件:新增 `scripts/concurrent_experts_smoke.py`(**零 src 改动**·纯验证脚本)。
- 忠实驱动**完整 `ExecuteCommand` 生产路径**(经 `_SubagentAwareToolRunner` + 并发批派发
  `_spawn_batch`(line 1101-1122)+ `CandidateExecutionGateway.preview_and_promote_batch` +
  `MergeGateDryRunner`),**不绕网关**(区别于 `model_driven_turn_smoke.py` 的 RegistryToolRunner)。
- planning 用确定性桩 `SeedGoalClient`(只搭 goal_spec 脚手架),**execution 用真 `create_model_client`**;
  覆盖 planner 的 `task_plan.json` 播种单个明确指示并行委派的 lead 任务(受验的是执行层并发机制)。
- 真栈无法塞 Barrier → 并发信号 = 两条 dispatch 卡都先于两条 result 卡(`card_order`
  `[dispatch,dispatch,result,...]` = ThreadPool 并发批;交错 = 串行回退)。
- 模式:`--mode readonly`(reviewer×2 扇出)/ `--mode disjoint`(coder×2 隔离写+merge_gate)。

## 结果(真栈)
| 模式 | glm(strong) | minimax(medium) | 证据 |
| --- | --- | --- | --- |
| readonly 扇出 | ✅ PASS | ✅ PASS | 2 dispatch+2 result·concurrent_batch=True·role=reviewer·2 distinct child·event_id 无撞·合并摘要已写 |
| disjoint 写 | ✅ PASS | —(strong 足证) | concurrent_batch=True·role=coder·**merge_gate_runs=1**·**alpha.py+beta.py 均并入共享工作区**(disjoint→全晋升)·event_id 无撞 |

**真弱模型(含 minimax)会自发在一批里发 ≥2 个 spawn_subagent 并发扇出**——重塑头号新能力在真栈成立。

## 诚实发现(记为观察·未改代码)
- **FSM 时代 `worker_recorder.delegation_gate` 仍在进脊梁前跑**(`execute_command:568`)。它对
  "写类任务(risk=write/high)brief 缺 `allowed_writes`"整任务 blocked。**disjoint 首跑被误挡**:
  模型驱动委派模式下 lead 自己不直接写(写委派给 coder 子专家)、天真地 `write_scope=[]` →
  brief 缺 allowed_writes → blocked,**根本没进脊梁/没到 spawn**。well-formed 任务(lead 声明委派写
  并集 `write_scope`)即通过。**判定=合法 brief-quality 边界非脊梁 bug**,但对模型驱动委派模式偏严;
  暂不改(收敛·gate 是合法证据边界),记为张力观察待真实 friction 再定。

## do_not_copy(禁止照搬)
- 不为让 smoke 过而放宽 delegation_gate 或 merge_gate(安全/证据边界不减配)。
- 不把并发写 flag(`isolated_parallel_write_production_path`)翻默认开(仍独立自主性 DecisionPoint·冻结)。

## 实现记录
- date: 2026-07-13
- notes: 见 §16 v1.2.25 + ADR-0023 真栈复验注 + 记忆 `ring-realstack-validation-A` / `reshape-model-driven-cluster`。
