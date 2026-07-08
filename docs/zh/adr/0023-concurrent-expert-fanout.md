# ADR-0023：并发专家扇出 —— 模型驱动的 spawn_subagent 真并发（Part B1）

**状态**：Accepted（B1-a readonly 已落地；B1-b 隔离写为后续切片）
**日期**：2026-07-08
**关系**：落地 [ADR-0022](0022-model-driven-spine-landed.md) 五层架构的 ③专家集群「真并发」；受 [ADR-0016](0016-model-driven-cognition-conformance.md) 支配（并发是模型决策空间，不是 harness 强编排）。取代 2026-06-28 已删的 swarm 中央 FSM 编排（不恢复）。

## 背景

RA3/RA4 把 `spawn_subagent` 专家委派立起来了，但当前是**串行、共享工作区骨架**（`execute_command.py:_spawn_subagent`）：即便 lead 在一个 tool_calls 批里发 N 个 `spawn_subagent`，`_SubagentAwareToolRunner.run_tool_calls` 也是 `for call in calls` 一个一个跑。2026-07-08 用户解冻并发专家研发（"可以启动并发专家那块的研发了·该解冻解冻"）。

调研确认底盘**全是真的、只是未接到 subagent 层**：`ExecutionCoordinator._execute_parallel_batch` 是真 ThreadPool（现只在 task-board 层跑 readonly）；`CandidateExecutionGateway`/`CandidateWorkspace`/`SandboxBackendSelector` 隔离栈真实可用但**休眠**（构造了从不调用）；`MergeGateDryRunner` 真做 per-task scope + cross-task 文件冲突检测，唯 `_disjoint_write_gate_result` 硬跳过。`UserProgressLogger.record` 与 `JsonlStore.append` 均已被模块级 RLock 守护 → **所有证据 append 已线程安全**。

## 决策

**并发 = 模型决策空间（ADR-0016 §1）**：并发在**模型把多个 `spawn_subagent` 放进同一个 tool_calls 批**时发生——lead 自己决定扇出，harness 不排编排拓扑、不强制并行。单发则天然串行。harness 只焊边界：并发上限（保险丝）、隔离写的 candidate/merge_gate、线程安全的证据持久。

**分两档，按风险切片**：

### B1-a 并发只读扇出（本 ADR 已落地）

lead 在一批里发 ≥2 个 `spawn_subagent` 且**全部命中只读专家**（`expert.read_only`，如 reviewer/researcher/diagnostic）时，在 ThreadPool 上并发跑。只读专家不写文件 → **无冲突、无需隔离/merge**，其证据 append 走既有 RLock → 线程安全。

- flag `agent_loop.concurrent_subagents`（默认 `false`·逐字节可回退）门控；关闭时逐字节等同今日串行。
- 并发上限 = `agent_loop.max_parallel_workers_per_run`（默认 16）。
- 复用 `ExecutionCoordinator._execute_parallel_batch` 的 ThreadPool 形态（`ThreadPoolExecutor(max_workers=min(n,cap))` + `as_completed`），结果按输入顺序回填。
- **两处并发正确性修**（既有 append 锁不覆盖的窗口）：① `UserProgressLogger` 的 `event_id`/`sequence` 计数器此前每实例从文件长度 seed（锁外）→ 并发子线程可撞同一 `upe-NNNN`；改为**模块级 per-path 单调计数器**（在既有 `_USER_PROGRESS_LOCK` 内自增，跨实例/线程唯一）。② `_spawn_subagent` 的 `subagent_counter["n"] += 1` 非原子 → `child_task_id` 可撞；加锁守护子代理编号分配。
- 混批（spawn + 非 spawn 工具同批）：非 spawn 工具仍串行经冻结 gateway（权限/沙箱/证据不变），spawn 批并发，结果按原始位置重组。

### B1-b 并发隔离写扇出（后续切片）

lead 发多个**写**专家时：每个 child 在**独立 candidate 工作区**（`CandidateExecutionGateway.create_workspace` → `candidate_context`）里跑 → 写各自隔离根、零共享写竞争（同 Claude Code 子代理独立 context 模型）；join 后 `preview_promotion` → `MergeGateDryRunner` 查 disjoint/冲突 → `promote_changes`（`_PROMOTION_APPLY_LOCK` 下）把非冲突写并回共享根。需**重启用** `_disjoint_write_gate_result`（现硬跳过）+ `real_disjoint_write_workers` flag。额外 flag `agent_loop.isolated_parallel_write_production_path`（现存·默认关）门控。

### 前端：子 agent 状态面板 + 下钻（后续切片，学 Claude Code）

Studio 右侧两层面板：折叠态显徽章计数（"2 运行·1 待输入"）→ 展开态按状态分组（Working/Needs-input/Done/Failed）每专家一行（色点 + role + 模型生成的一句状态线 + 时间）；点行下钻到该专家的完整过程（其工具调用/叙述，从按 `child_task_id`/`subagent_role` 标记的 Inspector 证据取），主线程只留 dispatch/result 摘要卡（Part B4 已落地的 subagent_summary）。**peek→attach→drill** 形态照搬 CC。

## 边界与非目标

- **不翻 `parallel_writes` 全局默认开**：解冻的是并发专家能力的研发（flag opt-in），把出厂默认自主并发行为翻开仍是独立的自主性/安全 DecisionPoint，须用户另行确认。
- **不恢复 swarm 中央 FSM 编排**（2026-06-28 已删）：并发经模型 tool-call 扇出 + harness 护栏，不是中央调度器。
- **CloudSessionExecutor 真远程**、高级 scheduler（角色依赖/成本延迟/跨机）、北极星 flesh 仍冻结（B3·须另 DecisionPoint）。

## 后果

- B1-a：`_SubagentAwareToolRunner` 认并发批、`_spawn_batch` closure 决策串行/并发、两处计数器线程安全修；deterministic 并发证明测试（`threading.Barrier` 迫使两 child 必须并发到达否则超时）。默认关 → 全量回归零影响。
- 逐字节可回退（flag）；每切片独立提交。
- 弱模型是否真扇出、扇出多少由 eval/模型决定，不反射式强制（ADR-0016 nuance）。

## 回滚或替代条件

- flag `agent_loop.concurrent_subagents=false` 即回退到串行。
- 若并发在成功率/正确性/证据一致性上可测地更差，关 flag 并重开讨论。
