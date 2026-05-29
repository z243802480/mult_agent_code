# Asteria 模型主导运行时设计

更新时间：2026-05-29

## 1. 结论

Asteria 的核心方向是：

```text
模型主导 agent loop，Runtime 提供能力环境、权限边界、预算、证据和恢复护栏。
```

状态机仍然重要，但它不应该替模型写死完整流程。Runtime 的职责是：

- 组织用户目标、项目规则、上下文、能力目录、预算和历史证据。
- 向模型暴露可理解的能力：tools、MCP、skills、subagents、candidate workspace、validation、promotion。
- 校验模型输出，执行权限/预算/sandbox/schema/gate。
- 记录可审计 evidence，并把 observation 回灌给模型。

模型的职责是：

- 根据 goal/context/capabilities 判断下一步。
- 在边界内选择 tool、subagent、repair、replan、ask 或 stop。
- 阅读 observation 并调整策略。
- 产出用户可理解的阶段性和最终结论。

## 2. AgentLoopDecision 契约

模型每轮必须产出一个稳定的 `AgentLoopDecision`。

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

Runtime 负责把 decision 转成 `agent_loop_execution_results.jsonl`，并按 action 分派：

- `tool` -> Tool Gateway / verification
- `subagent` -> WorkerInvocation / WorkerResult dispatch evidence
- `repair` -> Debug / recovery
- `replan` -> Replan
- `ask` -> DecisionPoint
- `stop` -> stop report / status debug

## 3. Runtime Gate

RuntimeReadinessGate 当前输入：

- model call contract：role、deadline、streaming telemetry。
- route guidance：provider route health 和 fallback evidence。
- context pressure：context window ratio 和 section source。
- observation decision：失败 observation 是否进入 AgentLoopDecision。
- agent loop execution：decision 是否有 matching execution result；subagent 是否有 worker evidence。
- capability selection：catalog 和实际 tool/skill/MCP/subagent 选择是否一致。

缺失 decision、缺失 execution、subagent 缺 worker evidence、重复失败无 recovery route 都应进入 blocked/review，而不是只写日志。

## 4. Subagent 设计

Subagent 不是普通 tool call。它代表“把一个任务交给隔离 worker/agent 执行”。

当前已实现：

- `subagent` action 校验 `capability_ref.type == "subagent"`。
- 必须有 `target_task_id`、`risk`、`budget_hint`。
- Runtime 写入 `workers.jsonl` 和 `worker_results.jsonl`。
- execution result 回填 `worker_invocation_id`、`worker_result_id`、`runtime_profile_id`、`worker_status`。
- status 可以展示 subagent worker/profile。
- gate 可以检查 subagent worker evidence。

仍需推进：

- 子 agent 独立 context window。
- 子 agent 多轮 tool loop。
- 子 agent completion / failed observation 回灌父 loop。
- 父子 worker graph 和 candidate workspace/promotion 关系。

## 5. Ask 设计

`ask` 不只是状态提示。Runtime-owned ask 必须落到 DecisionPoint：

- 写入 `decisions.jsonl`。
- execution result 记录 `decision_point_id`。
- status 推荐 `decide --decision-id ...`。

普通 runtime request 仍由 RuntimeRequestPolicy 创建 DecisionPoint，避免重复。

## 6. Observation 设计缺口

当前已经有 decision 和 execution result，但还需要统一的 `AgentLoopObservation`。

建议 observation 类型：

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

这会让 loop runner 能稳定地执行：

```text
decision -> execution -> observation -> next decision
```

## 7. 下一步设计目标

下一步不是继续扩大命令数量，而是把 agent loop 多轮化：

1. 新增 `AgentLoopObservation` schema 和 JSONL。
2. tool/subagent/debug/replan/ask/stop 都写 observation。
3. 新增最小 `AgentLoopRunner`，读取 observation 后调用模型生成下一轮 decision。
4. RuntimeReadinessGate 检查最新 execution 是否有 observation。
5. 用 fake-provider 小灰度验证至少两轮循环。

## 8. 非目标

- 不做 unrestricted agent chatroom。
- 不绕过 permissions、protected paths、budget、schema、candidate workspace 和 gate。
- 不让 Studio/dashboard 反向定义 Runtime 核心。
- 不依赖单一 provider。
- 不用历史 validation 通过数替代当前 workspace 的真实 evidence。
