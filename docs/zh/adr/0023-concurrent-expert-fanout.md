# ADR-0023：并发专家扇出 —— 模型驱动的 spawn_subagent 真并发（Part B1）

**状态**：Accepted（B1-a readonly 已落地；B1-b 隔离写已落地；前端子 agent 面板已落地）
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

### B1-b 并发隔离写扇出（已落地）

lead 一批发的专家里**含写专家**且 flag 开时：每个写 child 在**独立 candidate 工作区**里跑 → 写各自隔离根、零共享写竞争（同 Claude Code 子代理独立 context 模型）；混批里的只读 child 仍用共享 context（不写）。join 后经 `CandidateExecutionGateway.preview_and_promote_batch` 汇合——导出每个 candidate → **一次跨任务** `MergeGateDryRunner`（pre-flight 声明 write_scope disjoint + per-task scope/verification + post-exec 跨任务文件冲突）→ **全过则全晋升、任一冲突则全不晋升**（永不半并入冲突写），`candidate.promote` 在 `_PROMOTION_APPLY_LOCK` 下把非冲突写并回共享根。

- flag `agent_loop.isolated_parallel_write_production_path`（**现存·默认关**·逐字节可回退）门控；关时写批仍串行走共享工作区（等同今日）。此为能力 opt-in，**不**等于翻 `parallel_writes` 全局默认。
- **候选创建串行**（`_candidate_id()` 基于时间戳 + `git worktree add` 改共享库·均非线程安全）→ 主线程先建好所有 candidate，只让昂贵的模型驱动 child **运行**并发；晋升在 join 后串行做。
- `_disjoint_write_gate_result` 从硬跳过 stub **重启用**为真声明-scope disjoint 预检（单任务永不自冲突→`preview_promotion` 等单任务调用者不受影响；只读专家不声明 write_scope→空→ok）；真正的合并安全由早已实装的 `_cross_task_file_conflicts`（post-exec）兜底，本预检是更便宜的声明-意图前置门。**不需要** `real_disjoint_write_workers` 之类新 flag——底盘早在。
- 写线程实际写进 candidate 根，靠的是 `ToolExecutionGateway` **对传入的 `context.root` 解析每条路径**（call/existence/registry 全一致）→ 把隔离 candidate context 传给 `executor.run_subagent(context=…)` 即把 child 的写重定向进 candidate。
- 合并门阻止时 → child 隔离写留在各自 candidate、共享工作区零污染，写 child 的结果标 failure 上报 lead（模型看到失败自行决定下一步·认知归模型 ADR-0016）。

### 前端：子 agent 状态面板 + 下钻（已落地，学 Claude Code · peek→attach→drill）

`studio/src/features/inspector/SubagentPanel.tsx`——Inspector「子 agent」tab：`buildExpertRows` 纯函数按 `child_task_id` 聚合专家（dispatch/result 卡定状态·子 transcript 按 `subagent_role`/`task_id` 归集）→ 状态分组（running/failed/done）每专家一行（色点 + role + 状态线 + 步数）→ 点行下钻到该专家完整过程；主线程只留 dispatch/result 摘要卡（Part B4 的 subagent_summary）。形态照搬 CC。

**B1-b 合并可见性（拉齐）**：并发隔离写的 `merge_gate` 汇合卡是**批级**（无 `child_task_id`），故 `buildExpertRows` 会跳过它 → 之前不可见。新增 `buildReconciliation` 纯函数抽出该卡，渲染成面板**顶部横幅**：绿（isOk）"晋升 N 个文件到工作区" / 红（isBlocked）"被合并门阻止：…"，诚实呈现并发写到底并回了几个文件还是被冲突挡下（写 child 各自的 done/failed 状态已由 result 卡驱动的行呈现）。SSR 确定性验证（真组件 + 真投影，覆盖 ok/blocked/无卡三态）。

## 边界与非目标

- **不翻 `parallel_writes` 全局默认开**：解冻的是并发专家能力的研发（flag opt-in，B1-a/B1-b 两 flag 均默认关），把出厂默认自主并发行为翻开仍是独立的自主性/安全 DecisionPoint，须用户另行确认。
- **不恢复 swarm 中央 FSM 编排**（2026-06-28 已删）：并发经模型 tool-call 扇出 + harness 护栏，不是中央调度器。
- **CloudSessionExecutor 真远程**、高级 scheduler（角色依赖/成本延迟/跨机）、北极星 flesh 仍冻结（B3·须另 DecisionPoint）。**实现候选（调研 2026-07-13）**：腾讯云 **CubeSandbox**（RustVMM+KVM MicroVM·**E2B SDK 兼容**·国产化对齐）——真做云执行时优先接 E2B 兼容层而非自造沙箱；但它是 Linux/KVM 云集群，**不适合本地 Windows 缺口**（本地按定位维持轻量硬化）。详见记忆 `cubesandbox-cloud-sandbox-candidate`。

## 后果

- B1-a：`_SubagentAwareToolRunner` 认并发批、`_spawn_batch` closure 决策串行/并发、两处计数器线程安全修；deterministic 并发证明测试（`threading.Barrier` 迫使两 child 必须并发到达否则超时）。默认关 → 全量回归零影响。
- B1-b：`_spawn_subagent` 拆出 `_prepare_child`/`_run_child`/`_result_from_outcome` 三个可复用件（串行路径逐字节不变），新增 `_spawn_isolated_writes`（串行建 candidate → 并发跑 child → 合并门汇合 → 原子晋升）+ 网关 `preview_and_promote_batch`（导出/一次跨任务 merge gate/锁下晋升）；`_disjoint_write_gate_result` 重启用为真声明-scope 预检。三条确定性测试：Barrier(2) 证并发 + disjoint 双写晋升进共享工作区 + 同路径冲突被合并门阻止零污染 + flag-off 串行回退无 candidate/无 merge 卡。默认关 → 全量 1174 绿（唯 3 `runtime_profiles` 既有 provider 失败无关）·ruff/mypy 净。
- 逐字节可回退（flag）；每切片独立提交。
- 弱模型是否真扇出、扇出多少由 eval/模型决定，不反射式强制（ADR-0016 nuance）。

## 真栈复验（2026-07-13 · Part B B1 · 从 Barrier fake 升级为真 glm/minimax 跑通）

此前 B1-a/B1-b 只由 `threading.Barrier(2)` 确定性 fake 证过 ThreadPool 真并发，**从未在真弱模型栈跑通**。新增 `scripts/concurrent_experts_smoke.py`（零 src 改动·纯验证）忠实驱动**完整 `ExecuteCommand` 生产路径**（`_SubagentAwareToolRunner`+`_spawn_batch`+`preview_and_promote_batch`+`MergeGateDryRunner`，不绕网关），planning 桩 + **execution 真模型**，覆盖 task_plan 播种明确指示并行委派的 lead 任务。真栈无 Barrier → 并发信号=两 dispatch 卡都先于两 result 卡（`card_order=[dispatch,dispatch,result,...]`=并发批）。

- **readonly 扇出**：glm(strong) ✅ + minimax(medium) ✅（各 2 dispatch+2 result·concurrent_batch=True·reviewer·2 distinct child·event_id 无撞·合并摘要已写）。
- **disjoint 写**：glm(strong) ✅（concurrent_batch=True·coder·**merge_gate_runs=1**·**alpha.py+beta.py 均并入共享工作区**=disjoint 全晋升·event_id 无撞）。
- **conflict 写（2026-07-13 补·`--mode conflict`）**：glm(strong) ✅——两 coder 都写 src/shared.py·concurrent_batch=True·**merge_gate 挡下(ok=False)**·**共享工作区无 src/shared.py(零污染)**·冲突隔离写留 candidate 未晋升。此前 conflict 分支只 Barrier fake 证过，现真栈坐实"永不半并入冲突写"。
- **结论**：真弱模型（含 minimax）会**自发**在一批发 ≥2 个 spawn_subagent 并发扇出，且 merge_gate 的双分支（disjoint 全晋升 / conflict 全挡下零污染）在真栈成立——B1-a/B1-b 完整成立，不只是 fake。
- **张力已修复（2026-07-13）**：真栈发现 FSM 时代 `worker_recorder.delegation_gate`（`execute_command:568`）对模型驱动委派模式误挡——lead 天真 `write_scope=[]`（写委派给子专家各自声明 scope）被判"写类任务 brief 缺 `allowed_writes`"整任务 blocked、根本没进脊梁。**修**：`delegation_brief` 加诚实标记 `delegates_writes`（`spawn_subagent`∈allowed_tools 且自身无 write_scope）→ `brief_quality` 对委派型 lead 免除 `allowed_writes` 要求。**边界不减配**：brief-质量门非安全门（真写边界=gateway 逐路径 scope + merge_gate）；直接写无 scope 任务仍被挡。真栈端到端证：disjoint smoke 恢复自然委派形态后 glm 过 gate→并发扇出 2 coder→merge_gate 晋升进共享工作区。+2 单测·全量绿。brief=`benchmarks/reference_briefs/B1-realstack-concurrent-experts-validation.md`。

## 回滚或替代条件

- flag `agent_loop.concurrent_subagents=false` 即回退到只读并发前的串行；`agent_loop.isolated_parallel_write_production_path=false` 即回退到写批串行（两 flag 出厂均关）。
- 若并发在成功率/正确性/证据一致性上可测地更差，关 flag 并重开讨论。
