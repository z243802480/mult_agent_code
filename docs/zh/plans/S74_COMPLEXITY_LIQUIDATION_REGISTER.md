# S74 Complexity Liquidation Register

状态：S74 execution input
治理依据：[ADR-0011](../adr/0011-reference-first-complexity-liquidation.md)

## 使用规则

本登记表覆盖全系统，不限于已知问题。每个对象必须按“能力契约”和“当前实现”分别审计，并给出 `KEEP_CORE | REPLACE_IMPLEMENTATION | OPT_IN | FREEZE | DELETE` 结论。

未完成 reference、真实入口、配对 Eval 和删除影响分析前，不得声称某项实现应保留或删除。确认 `REPLACE_IMPLEMENTATION` / `DELETE` 后，不得继续增加修补代码。

## 裁决字段

每个审计项必须记录：

```text
audit_id
capability_contract
current_implementation
user_problem
real_entrypoints
reference_products
reference_mechanism
asteria_unique_need
paired_eval
product_benefit
safety_invariant
duplicate_responsibilities
maintenance_cost
decision
replacement_or_deletion_plan
verification
owner
exit_date
```

## 第一批审计队列

该队列是起点，不是范围上限。

| 优先级 | 审计对象 | 首要问题 | 初始假设 |
| --- | --- | --- | --- |
| P0 | 默认 Session Agent 主循环 | 是否保持简单的 model-tool-observation loop | 保留能力，清理 Runtime 语义代决策 |
| P0 | JSON action 与 native `tool_use` 双 transport | 是否存在两个默认真源和重复 repair | 配对 Eval 后只保留一个默认 |
| P0 | retry / schema repair / Debug / task repair 分层 | 是否重复重入、错误归因和预算混算 | 对齐成熟产品的消息回流与分层失败 |
| P0 | review / verification 完成链 | deterministic 验证通过后是否仍触发不必要模型调用 | 删除重复 review 重入 |
| P0 | user_progress / runtime_progress / summary 投影 | 是否多个层手工映射同一用户语义 | 收敛生产侧真源，删除重复映射 |
| P1 | RuntimeReadinessGate 与 gate-status 规则 | 是否保护真实风险，还是追逐内部完整性 | 已裁决：删除全局 Gate，保留动作边界与发布 preflight |
| P1 | subagent / worker / L3 orchestration | 是否优于单 Session 或只证明机制存在 | 保持 opt-in，按真实收益裁决 |
| P1 | candidate workspace / merge / promotion | 是否有重复状态机，能否复用成熟 worktree/checkpoint 机制 | 保留安全不变量，审计实现质量 |
| P1 | context envelope / package / budget / compact | 是否重复复制上下文或维护多套压力判断 | 对齐 session + compact + scoped context |
| P1 | capability / tool / MCP / skill catalog | 是否重复描述同一工具能力并扩大 prompt | 对齐按需发现与声明式权限 |
| P1 | Studio session narrative 与 Inspector 映射 | 是否手工穷举 Runtime 行为并暴露内部设计 | 主会话消费用户语义事件，Inspector 查证 |
| P2 | maintainer commands / acceptance / validation / evidence 壳 | 是否重复包装相同运行结果 | 隐藏、合并或删除无独立价值入口 |
| P2 | schema、JSONL、报告与兼容 fallback | 是否存在无人消费的持久化对象 | 无稳定消费者和迁移价值则删除 |
| P2 | deferred Agent 类、旧 aliases、legacy logger | 是否仍有真实调用 | 无调用即删除，不保留备用实现 |

## 已执行裁决

### CL-001：简单任务自动切换 native `tool_use`

| 字段 | 结论 |
| --- | --- |
| capability_contract | Provider 可以使用 native `tool_use` 传输 ExecutionAction |
| current_implementation | Planner 和 worker transport resolver 根据 fast-path task kind 自动选择 `tool_use`，覆盖默认 JSON policy |
| reference_mechanism | 成熟 Harness 允许原生工具调用，但实验 transport 不应在没有 rollout 决策时从多层自动覆盖显式配置 |
| evidence | 2026-06-09 rolling matrix 未证明 `tool_use` 降低 medium execution 或 repair；文档口径仍为受控灰度 |
| duplicate_responsibilities | Planner 与 resolver 同时决定 transport；默认 policy 已声明 `json` |
| decision | `OPT_IN` + `REPLACE_IMPLEMENTATION` |
| action | 删除按任务类型自动选择 `tool_use` 的两处逻辑；保留显式 task/runtime hint 和 policy 配置能力 |
| verification | worker transport、planner、coder、runtime profile、execute/run focused tests |
| exit | 配对真实 Eval 证明稳定收益后，才能重新提出默认 rollout DecisionPoint |

### CL-002：Phase 2 稳定性审计把效率 SLO 当硬 Gate

| 字段 | 结论 |
| --- | --- |
| capability_contract | 观察 scoped 任务的模型调用、repair 和稳定性趋势 |
| current_implementation | `phase2_stability_audit` 在 median model calls 或 max repair 超阈值时返回 `ok=false` |
| reference_mechanism | 成熟 Harness 将 turns/预算作为可配置保险丝，将调用量、repair 和耗时作为 eval/SLO；效率越界不等于任务或产品能力失败 |
| evidence | ADR-0010 已明确 SLO 与硬边界分离；旧 S10 目标只适用于历史 scoped 样本 |
| decision | `REPLACE_IMPLEMENTATION` |
| action | 保留样本缺失硬失败和全部指标；效率目标越界改为 `pass_with_warnings` + `slo_warnings`，不再生成 gate violation |
| verification | phase2 stability unit/integration、documentation contracts、steady iteration |
| exit | 后续产品 DecisionPoint 消费趋势与 warning；不得重新把统一效率目标升级为 Runtime 硬 Gate |

### CL-003：Run Health 用固定 repair/replan 次数判定失败

| 字段 | 结论 |
| --- | --- |
| capability_contract | 识别 blocked run、运行证据体积失控和不可恢复循环 |
| current_implementation | `run_health_audit` 将固定 repair/replan 次数越界直接写为 violation |
| reference_mechanism | 成熟 Harness 允许复杂任务多轮推进；只有资源失控、blocked terminal 或可证明无进展循环应硬失败 |
| evidence | 当前审计只统计次数，没有判断是否产生新 observation、artifact 或 verification，无法证明 stuck loop |
| decision | `REPLACE_IMPLEMENTATION` |
| action | 保留 blocked terminal、progress bytes/events 硬失败；repair/replan 次数改为 `slo_warnings` |
| verification | run health unit/integration、steady iteration |
| exit | 后续若增加 no-progress 硬判定，必须基于重复失败且无新增证据，而不是恢复次数本身 |

### CL-004：Studio 从多套 Runtime 投影重建主会话

| 字段 | 结论 |
| --- | --- |
| capability_contract | 用户在连续 Session 中看到真实发生的计划、工具、验证、询问、恢复和结果 |
| current_implementation | Studio 同时读取 `user_progress`、`runtime_progress`、`main_path`、final/run-loop summary，并合成缺失过程与 Final |
| reference_mechanism | Claude Code / Codex 将真实过程作为 Session messages；内部状态和证据进入 Inspector，不反向猜测主会话 |
| evidence | Studio `runtimeNarrative.ts` 包含多级 runtime progress fallback、五类合成事件和猜测 Final；与用户进展协议及 Studio 准则冲突 |
| decision | `REPLACE_IMPLEMENTATION` |
| action | Studio 主会话只从带 `transcript_kind` 的 `user_progress(display_level=main)` 构建；无合格 transcript 时回到隔离 legacy events；删除 progress/summary 合成过程、Final、channel/phase/provider wording 推断和固定 WorkflowPhaseStrip |
| verification | Studio build、run-detail smoke、interactive main path、session transcript focused tests |
| exit | Runtime 必须生产缺失的用户语义事件；不得把合成逻辑重新搬回 Studio |

### CL-005：RuntimeReadinessGate 全局内部完整性总闸门

| 字段 | 结论 |
| --- | --- |
| capability_contract | 权限、sandbox、candidate、merge、promotion、发布验证和可恢复 Session 必须受到保护 |
| current_implementation | 约 1800 行全局 Gate 事后扫描 route/context/capability/loop/subagent/promotion 证据；validation-run 维护 probe 绕过白名单 |
| reference_mechanism | Claude Code/Codex 在动作边界执行权限与 sandbox；Session/trace/eval 用于恢复和验证，不建立内部对象完整性总闸门 |
| duplicate_responsibilities | route、model contract、promotion、plugin 已由 gate-status 独立检查；loop/schema/capability 已由 Runtime 与 focused tests 检查 |
| decision | `DELETE` |
| action | 删除 RuntimeReadinessGate、控制面字段、自证测试和 validation bypass；probe 改为直接验证动作边界结果 |
| verification | gate-status、validation-run、control-surface contracts、主路径与 steady iteration |
| exit | 禁止以 evidence 完整性名义重建全局 Runtime gate；新增护栏必须有明确动作边界 |

### CL-006：Review / Debug / Goal policy 重复恢复控制器

| 字段 | 结论 |
| --- | --- |
| capability_contract | 失败 observation 回到当前 session，由模型选择 repair / replan / ask / stop；用户可显式 review、accept、debug |
| current_implementation | Execute Agent Loop、Run 自动 Debug/Replan、Review follow-up planner、Run Goal policy 同时决定失败后的下一步 |
| reference_mechanism | Claude Agent SDK 将 tool result 回流同一 session；Codex review 用于查证和反馈，不是第二 orchestrator |
| duplicate_responsibilities | 四层都解释失败、生成后续动作并修改 run/task 状态，导致恢复责任不唯一 |
| decision | `REPLACE_IMPLEMENTATION` + `DELETE` |
| action | 删除 Run 自动 Review/Debug/Replan/Goal-policy 重入；删除 Review 创建 task/DecisionPoint/AgentLoopDecision；显式 Review/Accept/Debug 保留兼容 |
| verification | run/review/user-workflow focused tests；文档源码契约；主路径和 steady iteration |
| exit | 真实 Beta 若暴露恢复不足，优先修 Agent Loop observation/decision，不得新增后置恢复控制器 |

### CL-007：Review follow-up planner 与 keyword DecisionPolicy

| 字段 | 结论 |
| --- | --- |
| capability_contract | 重大选择由模型显式 ask 或动作边界 DecisionPoint 表达 |
| current_implementation | 无产品消费者的 FollowUpTaskPlanner 与基于关键词/类别的 DecisionPolicy 仅由自测保护 |
| duplicate_responsibilities | Review 已不再编排；Agent Loop 与动作边界已经拥有 ask/DecisionPoint |
| decision | `DELETE` |
| action | 删除两个实现及只保护旧行为的单元测试 |
| verification | planner、review、run、documentation contracts |
| exit | 禁止重新通过 review follow-up 或关键词表创建任务/DecisionPoint |

### CL-008：真实 Provider 验证合成成功

| 字段 | 结论 |
| --- | --- |
| capability_contract | smoke/gate/acceptance 严格记录真实 Runtime 结果 |
| current_implementation | timeout、partial 或缺失 review artifact 时伪造 eval/review/final，并把 scenario 判成功 |
| user_problem | 真实 Beta 证据被污染，无法判断产品是否真的完成、停在哪里 |
| decision | `DELETE` |
| action | 删除 artifact-verified/review-timeout fallback 与 timeout salvage；缺失真实结果即失败 |
| verification | real-model smoke/gate/acceptance script tests、matrix tests、steady iteration |
| exit | 允许记录可恢复 partial evidence，但不得将其改写为成功 |

### CL-009：DebugCommand 独立 repair engine

| 字段 | 结论 |
| --- | --- |
| capability_contract | 用户可显式诊断失败，并让当前 Session 从 evidence 继续 |
| current_implementation | 约 1200 行独立执行器重复工具调用、验证、candidate、promotion、任务状态和预算逻辑 |
| reference_mechanism | Claude Code/Codex 将诊断反馈和失败结果放回当前线程，由同一 agent loop 继续 |
| decision | `REPLACE_IMPLEMENTATION` |
| action | 保留显式 debug 产品能力，下一批替换为诊断/恢复薄适配器；禁止继续扩展独立 repair engine |
| verification | explicit debug paired eval、session resume、candidate safety、user_progress |
| exit | 显式 debug 不再拥有第二套工具执行与任务状态机 |

## 横向反查清单

每次审计还必须反查：

- 是否存在同义命令、同义 schema、同义事件和同义状态。
- 是否存在 Runtime、CLI、Studio 三处重复业务判断。
- 是否存在只为测试 probe 生产的产品代码。
- 是否存在未被真实消费者读取的 evidence。
- 是否存在 feature flag 永久开启或永久关闭但代码仍保留。
- 是否存在历史 fallback 已无调用但继续污染主路径。
- 是否存在依赖顺序、状态转换或映射表只能靠开发者记忆。
- 是否存在比成熟产品稳定原语更复杂、却无法证明收益的自研抽象。

## 完成定义

S74 第一批清算完成不以删除行数衡量，而以以下结果衡量：

1. 默认主路径责任更少、真源更少、可解释性更强。
2. 被删除或替换的路径有配对 Eval，结果、安全和恢复不退化。
3. 每项复杂能力都有明确结论、owner 和退出条件。
4. 没有继续扩展已判定劣质的实现。
5. 文档、测试、schema、入口和代码同步清理，不留下干扰信息。
