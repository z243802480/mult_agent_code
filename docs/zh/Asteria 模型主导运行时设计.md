# Asteria 模型主导运行时设计

更新时间：2026-05-29

## 1. 结论

Asteria 的核心方向是：

```text
模型主导 agent loop，Runtime 提供能力环境、权限边界、预算、证据和恢复护栏。
编排路径由模型根据 ContextEnvelope + CapabilityManifest 选择，不由固定 if/else 流水线写死。
```

**产品架构真源**：[`架构设计.md`](./架构设计.md)。
**动态调度反模式（禁止 domain 硬分支）**：[`大模型循环与动态上下文设计.md`](./大模型循环与动态上下文设计.md) §3.1。

状态字段只服务于持久化、恢复和查证，不是产品架构，也不替模型写死完整流程。Runtime 的职责是：

- 组织用户目标、项目规则、上下文、能力目录、预算和历史证据。
- 向模型暴露可理解的能力：tools、subagents、candidate workspace、validation、promotion。（MCP 适配器与 skill 发现已实现，但**尚未接入模型循环**，当前不在模型可直接调用的能力面，见 §9。）
- 校验模型输出，执行权限、预算、sandbox、schema、gate。
- 记录可审计 evidence，并把 observation 回灌给模型。

参考 Claude Code 的公开产品思路时，只吸收机制，不照搬形态：subagent 使用独立上下文和受限工具/权限；tool/subagent 调用前后有事件式 gate；session evidence 采用追加式记录；失败不直接消失在 provider/tool 层，而是回到上层 agent loop 纠偏。

模型的职责是：

- 根据 goal/context/capabilities 判断下一步。
- 在边界内选择 tool、subagent、repair、replan、ask 或 stop。
- 阅读 observation 并调整策略。
- 产出用户可理解的阶段性和最终结论。

## 2. Agent Loop 契约

`AgentLoopDecision` 是当前结构化 transport 契约，不是对模型行为的完整本体定义。
Runtime 只在需要执行动作时要求可校验的结构；自然语言说明、提问和最终结果仍属于 Session。

允许的 next action：

```text
tool | subagent | repair | replan | ask | stop
```

每个 action 必须携带：

- `reason`
- `target_task_id`
- `capability_ref`
- `expected_observation`
- `risk`
- `budget_hint`
- `evidence_refs`

Runtime 将 decision 转成 execution result，再转成 observation：

```text
AgentLoopDecision
  -> AgentLoopExecutionResult
  -> AgentLoopObservation
  -> next AgentLoopDecision
```

当前持久化文件：

- `agent_loop_decisions.jsonl`
- `agent_loop_execution_results.jsonl`
- `agent_loop_observations.jsonl`
- `agent_loop_run_summary.json`

## 3. Bounded Loop

`ExecuteCommand` 已从单轮模型提案升级为 bounded loop。

当前规则：

- 默认每个 task 最多 5 轮（CC 式单会话 tool→verify→repair 收敛，给模型足够回合自愈）。
- policy `agent_loop.max_rounds_per_task` 可调整，clamp 1–8。
- 每轮 observation 会回灌给下一轮模型。
- 只有模型显式声明继续条件时才自动进入下一轮。

继续条件包括：

- `expected_observation.next_recommended_action`
- `expected_observation.requires_follow_up_decision`
- `expected_observation.auto_repair_on_failure`

这样可以避免普通失败任务盲目自旋，同时允许模型明确要求：

- tool 成功后再 stop。
- tool 失败后进入 repair。
- 需要用户判断时进入 ask。
- 需要分派时进入 subagent。

### Loop quality 信号（loop_quality_guard）

`max_rounds_per_task` 和预算 hard-stop 是循环的两道**硬保险**。在它们之上，
`agent_loop.loop_quality_guard`（默认 `mode: observe_then_warn`）是一个**可审计的 SLO 信号**，
不是 kill-switch（遵 ADR-0010：调用/repair 次数是 SLO，不是统一硬停止）。

`core/loop_progress_guard.py` 在每个 task 收尾时基于该 task 的 agent-loop observations 计算：

- `repeated_failed_verifications`：尾部连续 `failed` observation 数（默认 window 3）。
- `repeated_identical_observations`：尾部连续指纹相同的无进展 observation 数（默认 window 8）。
  指纹剔除每轮易变的 execution/decision id，只要出现**新 artifact / validation ref** 就视为有进展、
  打断连续计数——正是 ADR-0010 对"可证明无进展循环"的定义（连续重复同类失败且无新 observation/artifact/verification）。

命中窗口时写入 `agent_loop_run_summary.json` 的 `loop_quality.warn=true`，由 `status` / Studio Inspector
呈现，并作为放量 DecisionPoint 的回归证据。默认只观察告警、不改写模型的恢复决定（遵 ADR-0014）；
更强的硬停止模式留作后续按真实 Beta friction 证据再开。

## 4. Runtime 护栏与验证分层

全局 `RuntimeReadinessGate` 已由 ADR-0013 删除。Runtime 不再事后扫描全部内部对象并决定
系统是否可用，责任改为：

- 权限、sandbox、写入、网络和越权风险在 Tool Gateway 动作发生前执行。
- candidate、merge、promotion 和不可逆操作在对应边界执行强护栏。
- Agent Loop 在 observation 后由模型继续决定 tool/subagent/repair/replan/ask/stop。
- schema、execution/observation 对应关系和 summary 一致性由 focused tests 与 Inspector
  diagnostics 查证，不升级为全局 Runtime block。
- provider route 与发布放量由 doctor、model-check、gate-status、validation 和 acceptance
  负责。

禁止重新建立以内部 evidence 完整性为目标的全局 Runtime Gate。

## 5. Subagent 设计

Subagent 不是普通 tool call。它代表“把一个任务交给隔离 worker/agent 执行”。

当前已实现：

- `subagent` action 校验 `capability_ref.type == "subagent"`。
- 必须有 `target_task_id`、`risk`、`budget_hint`。
- Runtime 写入 `workers.jsonl` 和 `worker_results.jsonl`。
- execution result 回填 `worker_invocation_id`、`worker_result_id`、`runtime_profile_id`、`worker_status`。
- AgentLoopRunner 和 ExecuteCommand 主链路支持追加写入 worker completion evidence，并转成父 loop `subagent_result` observation。
- ExecuteCommand 中的 child worker 已支持多轮 bounded tool loop：失败 observation 可回灌 child 下一轮，成功后再回灌父 loop。
- worker/runtime profile evidence 保留 `worker_kind`、`parent_worker_invocation_id`、`parent_runtime_profile_id` 和 `parallel_safety`，为后续并行 worker 调度保留接口。
- child candidate workspace manifest、task execution evidence 和 context mount 记录父子关系与 `subagent_child_context` isolation policy。
- ContextBudgetMeter v2 会为 subagent child context 写入 `context_budget_snapshots.jsonl`，记录 section token attribution、parent worker/runtime profile、compact boundary 和 duplicate context signals。
- status 可以展示 subagent worker/profile。
- gate 可以检查 subagent worker evidence 和 child context snapshot；失败 worker 若没有父 loop repair / replan / ask / stop 纠偏，会被阻断。

仍需推进：

- 子 agent 独立 planner/decomposer。
- ContextBudgetMeter v2 compact before/after token、恢复摘要和文件 hash/diff 降噪。
- 父子 worker graph 和 candidate workspace/promotion 关系继续图谱化。

## 6. Ask 设计

`ask` 不只是状态提示。Runtime-owned ask 必须落到 DecisionPoint：

- 写入 `decisions.jsonl`。
- execution result 记录 `decision_point_id`。
- run summary/status 推荐 `decide --list`。

普通 runtime request 仍由 RuntimeRequestPolicy 创建 DecisionPoint，避免重复。

## 7. Observation 设计

`AgentLoopObservation` 是模型下一轮输入的稳定边界。

当前 observation 类型：

- `tool_result`
- `subagent_result`
- `repair_result`
- `replan_result`
- `decision_pending`
- `decision_resolved`
- `stop_report`

每条 observation 至少包含：

- `observation_id`
- `run_id`
- `task_id`
- `source_execution_id`
- `status`
- `summary`
- `evidence_refs`
- `next_recommended_action`

## 8. Loop Run Summary

`agent_loop_run_summary.json` 是用户、gate 和 Studio 读取 loop 退出原因的产品化入口。

当前记录：

- `status`
- `exit_reason`
- `rounds_completed`
- `max_rounds`
- `summary`
- `recommended_command`
- `latest_decision_id`
- `latest_execution_id`
- `latest_observation_id`
- `latest_action`
- `evidence_refs`

当前退出原因：

```text
completed | tool_failed | max_rounds | budget_hard_stop | ask | stop |
subagent_pending | repair_dispatch | replan_dispatch | no_action
```

## 9. 下一步设计目标

下一步不是继续扩大命令数量。subagent 已是真实子 agent 执行器：模型 action==`subagent` 在多轮 loop 中触发 `_execute_subagent_child_loop`（execute_command.py:2305），递归运行 CoderAgent（注意：单步非循环路径目前对 `subagent` 仍标记 blocked，见 :1345，待定夺是否一致化）。在此基线上进一步增强：

1. 为 subagent worker 增加独立 planner/decomposer，支持 child task graph。
2. 将 child candidate workspace 与父 task merge/promotion 关系纳入 graph/status。
3. 补齐 ContextBudgetMeter v2 compact before/after、恢复摘要和文件 hash/diff 降噪。
4. 用真实 provider 灰度验证父模型选择 subagent、child repair、父 loop stop。
5. 再评估 readonly / disjoint write 的真实并行 worker 调度。

## 10. 非目标

- 不做 unrestricted agent chatroom。
- 不绕过 permissions、protected paths、budget、schema、candidate workspace 和 gate。
- 不让 Studio/dashboard 反向定义 Runtime 核心。
- 不依赖单一 provider。
- 不用历史 validation 通过数替代当前 workspace 的真实 evidence。
