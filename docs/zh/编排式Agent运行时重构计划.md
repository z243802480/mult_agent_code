# 编排式 Agent 运行时重构计划

## 1. 文档定位

本文档把外部先进 Agent 架构中的可学习部分沉淀为本项目的长期架构方向和重构计划。

它不是对某个厂商实现的复刻，也不是为了追求“更多 Agent 同时聊天”。它定义的是本项目接下来要逐步逼近的运行时形态：

```text
一个本地优先、可编排、可恢复、可验证、可审计、可控成本的 Asteria Runtime OS。
```

从产品意义上看，这类架构很可能是通用智能能力落地到真实生产系统的一种重要形态：模型负责规划、判断和协调，运行时负责状态、权限、预算、沙盒、验证、恢复和报告。

本文档后续所有重构都遵循一个补充原则：**硬外壳，软内核**。运行时负责不可协商的安全、预算、权限、状态、验证和恢复边界；模型负责边界内的推理、方案选择、代码组织、调试路径和自我修复。不要把模型内部本应发挥推理能力的部分，过早固化成大量确定性业务补丁。

## 2. 核心吸收点

### 2.1 大脑与双手解耦

模型的规划与决策能力不应和具体执行环境绑定死。

目标形态：

```text
Orchestrator / Coordinator
  负责目标理解、任务拆解、调度、决策、预算和验收

Worker / Sandbox
  负责受控文件修改、命令执行、测试、调研和产物生成
```

设计含义：

- Worker 可以失败、污染、超时或被销毁。
- Worker 失败不应破坏 Session、Store 或主工作区状态。
- 执行环境应逐步走向可重建、可隔离、可替换。
- Runtime 的稳定性不能依赖某个长期运行 Agent 的隐式记忆。

近期不要求立刻引入 Docker 或远端沙盒，但所有接口应朝“执行单元可丢弃”的方向设计。

### 2.2 AgentSpec 与 Session 分离

Agent 是静态模板，Session 是动态运行态。

```text
AgentSpec = 我是谁
Session = 我正在做什么
Run/Event/Artifact = 我做过什么
ContextSnapshot = 我如何恢复
```

AgentSpec 应描述：

- 角色。
- 模型层级。
- 允许工具。
- 写入范围。
- 输入输出契约。
- 预算。
- 系统提示词或指导引用。

Session 应描述：

- 用户目标。
- 当前任务图。
- 上下文快照。
- 决策记录。
- 工具调用记录。
- 模型调用记录。
- 产物与验证结果。
- 修复历史和失败证据。

这能避免把角色、任务、上下文、文件副作用和历史聊天混在一起，后续才能支持恢复、复制、并发、审计和压缩。

### 2.3 Coordinator 编排专业 Worker

系统的核心不是“多 Agent 自由聊天”，而是 Coordinator 调度一组有职责边界的 Worker。

典型角色：

```text
GoalSpecAgent
PlannerAgent
ArchitectAgent
CoderAgent
TesterAgent
ReviewerAgent
DebuggerAgent
MemoryAgent
ReporterAgent
```

每个 Worker 都必须通过结构化任务契约工作：

```text
TaskContract
  objective
  inputs
  dependencies
  allowed_tools
  expected_outputs
  acceptance_checks
  sandbox_policy
  budget
  failure_policy
```

Coordinator 的职责是：

- 生成或维护 TaskGraph。
- 选择可运行节点。
- 分配 Worker。
- 收集产物。
- 运行验证。
- 触发修复。
- 在预算、权限或方向问题出现时创建 DecisionPoint。

### 2.4 TaskGraph 取代线性对话

长任务不应被建模成一条无限增长的聊天记录，而应建模成可调度任务图。

目标数据流：

```text
GoalSpec
  -> TaskGraph
  -> WorkerInvocation
  -> Artifact
  -> ValidationResult
  -> RepairLoop
  -> Merge / Keep / Discard
  -> FinalReport
```

Phase 1B 可以继续串行执行，但数据模型要预留 DAG：

- task dependencies。
- ready node selection。
- parallel-safe 标记。
- merge node。
- blocked node。
- repair edge。
- validation gate。

### 2.5 无状态 Worker 与可恢复上下文

Worker 不应是记忆的唯一载体。真正的长期状态应在 Store 中。

本项目的本地优先版本先使用文件系统和 JSON/JSONL：

```text
.asteria/
  sessions/
  runs/
  context/snapshots/
  tasks/
  acceptance/
  memory/
  reports/
```

恢复能力的最小要求：

- 从 ContextSnapshot 恢复目标、决策、任务、产物和风险。
- 从 events.jsonl 追踪运行轨迹。
- 从 tool_calls.jsonl 和 model_calls.jsonl 审计成本与行为。
- 从 validation/evidence 文件定位失败原因。
- 修复循环不依赖旧聊天窗口里的隐式上下文。

### 2.6 启动时挂载运行环境

无状态 Agent 不代表 Agent 没有差异，而是差异不写死在长期运行进程里。每次启动 Worker 时，Coordinator 应通过结构化 profile 挂载运行环境。

可挂载信息包括：

- 模型供应商和模型名。
- 模型层级和用途。
- API 账号或凭据引用。
- 工具权限。
- 文件写入范围。
- 工作目录或沙盒。
- 上下文快照。
- 记忆 Store 挂载点。
- 成本预算。
- 网络权限。
- 安全策略。

目标形态：

```text
WorkerInvocation
  -> AgentSpec
  -> ModelProfile
  -> ToolPermissionProfile
  -> AccountProfile
  -> SandboxProfile
  -> ContextMount
  -> BudgetProfile
```

这也是实现“不同模型使用不同 Agent”的关键。系统不应该把模型选择硬编码到某个 Agent 类里，而应该让 Coordinator 根据任务类型、风险、成本和历史能力画像选择运行 profile。

示例：

```text
PlannerAgent + strong_model + read_only_tools + high_context_snapshot
CoderAgent   + medium_model + patch_tools     + task_workspace
ReviewerAgent + strong_model + read_only_tools + artifact_index
FormatterAgent + cheap_model + no_write_tools + compact_context
```

账号也应按 profile 管理，而不是散落在环境变量读取逻辑里。不同 Worker 可以使用不同权限的账号，例如：

- 只读调研账号。
- 低成本本地模型账号。
- 强模型评审账号。
- 禁止网络的离线执行 profile。
- 仅允许特定目录写入的代码 profile。

凭据本身不得写入 profile，只能写入凭据引用或环境变量名，并继续遵守 protected paths 和 secret 读取策略。

### 2.7 验证与修复循环是核心能力

多 Agent 的价值不在“数量”，而在每个任务都能进入可靠闭环：

```text
execute
  -> validate
  -> attribute failure
  -> repair
  -> revalidate
  -> report
```

因此 Phase 1B 的优先级仍然是：

- acceptance loops。
- execution-loop hardening。
- structured task contracts。
- failure evidence。
- budget hard stop。
- context snapshot。

不要为了并发规模牺牲验证、审计和安全边界。

### 2.8 模型驾驭：边界不是笼子

模型会持续升级。今天为了补齐模型短板而写出的复杂规则、上下文拼接技巧或“替模型思考”的业务代码，可能在下一代模型出现后迅速变成负资产。

因此，本项目不能把运行时设计成一个巨大的规则引擎。更好的形态是：

```text
Runtime = 硬外壳
  强制安全、预算、权限、schema、日志、验证、回滚、决策升级

Agent = 软内核
  在任务合同允许范围内自主推理、选择步骤、组织代码、诊断失败、补充验证
```

对 runtime 来说，应该强制的是风险边界，而不是执行细节：

- 可以强制 `protected_paths`、secret 不可读、破坏性 shell 不可执行。
- 可以强制写入必须落在 `write_scope`，只读任务不能写。
- 可以强制所有工具调用、模型调用、产物、验证和失败证据必须落盘。
- 可以强制预算硬停和高风险动作进入 DecisionPoint。
- 不应把某类业务任务的完整实现步骤写成固定分支，让模型只能填空。
- 不应因为当前模型容易犯错，就把大量易过时的 prompt 补丁、文件猜测和流程特判塞进核心运行时。

对 TaskContract 来说，`read_scope`、`write_scope`、`allowed_tools`、`context_requirements` 和 `validation_commands` 应表达“工作空间和验收边界”，而不是表达“模型必须照着这份脚本逐行执行”。当模型变强时，同样的 contract 应允许它提出更好的局部设计、更少的步骤、更完整的验证和更高质量的修复。

这也意味着未来的 Planner 和 Coordinator 要支持“弹性边界”：

- 对安全、权限、预算和审计使用硬约束。
- 对实现方案、搜索路径、补丁形态和验证增强使用软约束。
- 当模型判断当前 scope 过窄、上下文不足或工具不够时，应生成结构化的 scope expansion / context request / tool request，而不是偷偷越界。
- 对模型提出的越界请求，由 Coordinator 根据风险、成本和用户策略决定批准、拒绝或升级为 DecisionPoint。

这类设计更接近成熟 agentic coding 工具的实践：不是用代码替代模型，而是用运行时驾驭模型。模型越聪明，系统越应该受益，而不是被旧规则拖累。

### 2.9 可进化机制：让系统长期吸收进步

本项目目标不是一次性写出某个固定工作流，而是打造通用性的自主生产力底座。它必须能持续吸收行业优秀设计、适配模型能力变化，并在长期运行中保持结果一致性。

因此，系统需要把“开放吸收”和“结果一致”之间的博弈机制化，而不是依赖开发者临场感觉。

#### 2.9.1 行业设计吸收机制

当外部出现值得学习的 agentic coding、sandbox、context recovery、multi-agent orchestration 或 evaluation 设计时，不应直接照搬实现，也不应因为不是自研就排斥。

推荐流程：

```text
External Pattern
  -> Architecture Note
  -> Applicability Analysis
  -> Risk / Cost / Local-first Check
  -> Small Spike
  -> Acceptance Scenario
  -> Runtime Integration
  -> Capability / Cost Tracking
```

每次吸收外部思想时，至少回答：

- 它解决的是模型能力问题、运行时问题、交互问题，还是组织工程问题。
- 它是否增强通用生产力底座，而不是只服务某个 demo。
- 它是否保持本地优先、可审计、可恢复和可替换模型。
- 它是否可以通过 schema、日志、验收和回滚保持结果一致性。
- 它引入的复杂度是否能被长期收益抵消。

#### 2.9.2 能力画像与模型升级机制

模型升级后，旧的补丁、提示词、流程特判和 deterministic fallback 都应被重新评估。

运行时应持续记录：

- 不同模型在 planning、coding、debugging、review、summarization 上的成功率。
- 每类任务的验证通过率、修复次数、成本和耗时。
- 格式错误、工具误用、越界请求、上下文不足、验证缺失等失败类型。
- 同一任务在不同 model profile 下的质量差异。

后续 Coordinator 应优先基于 capability profile 调整路由，而不是把某个模型名写死进业务逻辑。强模型变强时，系统应减少过时的补丁和特判；便宜模型能力提升时，系统应把低风险任务迁移到更低成本路径。

#### 2.9.3 规则退役机制

每条复杂运行时规则都应有存在理由。为了避免系统变成历史补丁堆，新增规则时应尽量记录：

- 规则解决的失败类型。
- 触发条件。
- 相关验收场景。
- 是否属于安全硬边界，还是模型能力补丁。
- 未来可退役条件。

安全硬边界一般不退役，例如 secret、protected paths、破坏性 shell、预算硬停和审计日志。

模型能力补丁必须可退役，例如：

- 某个模型经常漏字段而增加的字段归一化。
- 某类 prompt 格式错误的特殊修复。
- 某个任务类型的过细实现步骤模板。
- 某个文件名猜测或产物路径特判。

当验收数据证明新模型已经稳定处理这些场景，应删除或降级旧规则，让模型重新获得空间。

#### 2.9.4 弹性边界请求机制

如果模型认为当前任务合同不足，正确行为不是越界执行，而是生成结构化请求：

```text
ScopeExpansionRequest
ContextRequest
ToolRequest
BudgetRequest
ModelUpgradeRequest
DecisionRequest
```

Coordinator 对请求做判断：

- 低风险、低成本、符合 policy 的请求可以自动批准并记录。
- 中风险请求可以创建 DecisionPoint 或进入 review。
- 高风险请求必须拒绝或要求用户确认。

这样既不给模型无限权限，也不让初始 TaskContract 过窄时卡死执行。模型能力越强，越能主动识别自己需要什么；runtime 负责把这种主动性转成可审计、可恢复的状态变化。

#### 2.9.5 结果一致性机制

开放不等于随机。系统需要用结果层的一致性约束，允许过程层的模型自由度。

应优先稳定这些结果层对象：

- GoalSpec 是否表达用户目标。
- TaskContract 是否可执行、可验证。
- Artifact 是否存在且满足验收。
- ValidationResult 是否真实通过。
- FailureEvidence 是否能解释失败。
- CostReport 是否在预算内。
- FinalReport 是否能复盘过程和产物。

模型可以用不同路径完成任务，但最终必须落到同一套持久化对象、验证门禁和报告结构中。这是“软内核”能被生产系统使用的前提。

#### 2.9.6 长期运行自进化闭环

长期运行时，系统应逐步形成闭环：

```text
Run
  -> Evidence
  -> Evaluation
  -> Capability Profile
  -> Routing / Contract / Context Policy Update
  -> Acceptance Regression
  -> Memory / Roadmap Update
```

当系统发现某类失败重复出现，不应只修当前任务，而应沉淀为：

- failure_lesson memory。
- 新 acceptance scenario。
- Planner 或 Coordinator 的策略调整。
- 模型路由调整。
- 文档或 schema 更新。

当系统发现某类规则长期不再触发，也应提出退役建议，减少运行时复杂度。

这个机制是本项目成为“通用生产力底座”的关键：它不是靠某一次架构设计保持先进，而是靠持续证据、评估和回归测试，让系统能吸收新模型、新工具和新行业实践。

### 2.10 关键技术难点

这条路线的难点不在概念，而在运行时工程。

#### 2.10.1 并发编排难点

大脑支配多个 Worker 时，必须处理：

- 任务依赖判断。
- 就绪节点选择。
- 写入范围冲突。
- 多个候选实现的保留/丢弃。
- 验证节点和合并节点的顺序。
- 某个分支失败后的局部停止。
- 预算在 session、task、worker 三层的归因。
- 并发日志的排序和可读性。
- 用户决策点对下游任务的阻塞传播。

设计原则：

- Phase 1B/1C 先实现串行 TaskGraph，不急于并发。
- 所有任务必须声明 read/write scope。
- 默认只允许只读任务并发。
- 写任务并发必须经过冲突检查。
- 合并必须经过 ValidationGate 和 ReviewGate。
- 失败分支必须产出 FailureEvidence，不能只留下控制台错误。

#### 2.10.2 上下文恢复效率难点

上下文恢复不能每次把所有历史重新塞回模型。

主要难点：

- 长 session 的事件日志会很大。
- 不同 Worker 需要的上下文不同。
- 失败修复需要精确证据，而不是泛化摘要。
- 评审需要 artifact diff、验收结果和决策依据。
- 低成本模型不能承受完整上下文。
- 过度压缩会丢失关键约束。

设计原则：

- ContextSnapshot 只保存恢复索引和高价值摘要。
- ArtifactIndex 记录产物路径、任务来源、验证状态和摘要。
- FailureEvidence 单独结构化保存，修复时优先加载。
- Worker 启动时按 task contract 选择 context mount。
- 采用分层上下文包：root guidance、goal brief、task brief、artifact slice、failure slice、recent events。
- cheap model 默认只拿 task brief 和局部 artifact slice。
- strong review model 可以拿更完整的 decision、validation 和 diff 索引。

#### 2.10.3 沙盒与环境挂载难点

Worker 可丢弃以后，环境构建会成为成本和性能瓶颈。

主要难点：

- 启动慢。
- 依赖安装重复。
- 工作区复制成本高。
- 不同任务的工具权限不同。
- 容器和本地 worktree 的行为差异。
- 沙盒销毁前需要保留产物和证据。

设计原则：

- MVP 不把 Docker 作为硬依赖。
- 先用 workspace policy 和 patch 记录模拟沙盒边界。
- 再引入 per-task temp workspace 或 Git worktree。
- 最后才引入容器沙盒。
- 沙盒必须显式导出 Artifact、Diff、ToolCall、FailureEvidence。

#### 2.10.4 多模型与多账号路由难点

多模型不是简单轮询，而是运行时调度问题。

主要难点：

- 模型能力变化快。
- 不同供应商格式和失败模式不同。
- 同一模型在 planning、coding、review 上表现差异大。
- 账号权限、预算和速率限制不同。
- 失败时需要知道是任务问题、模型问题还是工具问题。

设计原则：

- ModelProfile 独立于 AgentSpec。
- ModelCall 必须记录 purpose、provider、model、tier、status、error_type 和成本估计。
- 能力画像按 purpose 聚合，而不是只按模型名聚合。
- Coordinator 根据 task type、risk、budget、capability profile 选择模型。
- 格式修复、分类、摘要优先 cheap/local。
- 架构、计划、评审和高风险修复优先 strong。

## 3. 与当前项目目标的关系

本项目原目标是：

```text
把 compact user goal 转化为 verified artifacts。
```

吸收编排式 Agent 架构后，目标可以更明确地表达为：

```text
通过 GoalSpec、TaskGraph、WorkerSandbox、ValidationGate、RepairLoop、ContextSnapshot 和 FinalReport，
把紧凑用户目标转化为可验证、可恢复、可审计的持久产物。
```

这不是目标扩张，而是把原目标的运行时结构说清楚。

仍需坚持的边界：

- 不做无限制 Agent 聊天室。
- 不允许无策略审批的破坏性 shell。
- 不绑定单一模型供应商。
- 不跳过持久化对象 schema 校验。
- 不在核心 CLI/runtime 闭环稳定前优先做 dashboard。

## 4. 目标架构切片

### 4.1 Control Plane

控制平面负责稳定性，而不是生成内容。

职责：

- 加载根指导和项目策略。
- 管理 Session。
- 维护 TaskGraph。
- 分配 Worker。
- 管理预算和权限。
- 创建 DecisionPoint。
- 触发验证、修复和报告。

### 4.2 Agent Plane

Agent 平面负责模型推理。

职责：

- 目标规格化。
- 任务拆解。
- 方案设计。
- 编码建议。
- 失败诊断。
- 评审。
- 摘要和报告。

Agent 不应直接拥有长期状态。长期状态必须写入 Store。

### 4.3 Tool Plane

工具平面负责真实世界动作。

职责：

- 文件读写。
- 代码搜索。
- 补丁应用。
- 命令执行。
- 测试运行。
- schema 校验。
- 本地报告生成。

所有工具必须经过权限、预算和日志入口。

### 4.4 Execution Plane

执行平面负责隔离和可丢弃执行。

阶段目标：

```text
Phase 1B: 单工作区受控执行
Phase 1C: WorkerInvocation 抽象
Phase 2: 隔离工作目录或 Git worktree
Phase 3: 可选容器沙盒
Phase 4: 本地/远端 Worker 混合
```

### 4.5 Store Plane

Store 平面负责可恢复和可审计。

必须持久化：

- Session。
- Run。
- TaskGraph。
- AgentSpec。
- WorkerInvocation。
- ToolCall。
- ModelCall。
- Artifact。
- ValidationResult。
- FailureEvidence。
- ContextSnapshot。
- DecisionPoint。
- CostReport。

## 5. 重构计划

### P0：文档与概念对齐

目标：

- 把编排式 Asteria Runtime OS 作为长期方向写入主文档。
- 明确 AgentSpec、Session、TaskGraph、Worker、Store 的边界。
- 确认当前 Phase 1B 不追求大规模并发，先追求结构正确。

产物：

- 本文档。
- `架构设计.md` 中增加架构北极星。
- `文档导航.md` 中加入本文档入口。

验收：

- 新贡献者能从文档理解系统不是聊天群，而是运行时操作系统。
- 后续实现任务能映射到明确架构层。

### P1：TaskContract 与 TaskGraph 硬化

目标：

- 把现有 task_plan 从任务列表提升为可验证任务图。
- 每个任务必须带输入、输出、依赖、工具、验收和失败策略。

建议改动：

- 扩展 task schema，增加 `contract` 或显式字段。
- 增加 `graph_node_type`：work、validation、merge、repair、decision。
- 增加 `parallel_group` 和 `merge_strategy` 的预留字段。
- 强化 task_plan_quality_gate，阻止不可执行计划进入执行。

验收：

- `/plan` 生成的计划能被确定性检查。
- `/execute` 只执行 contract 完整的 ready task。
- 失败任务能生成结构化 FailureEvidence。

### P2：WorkerInvocation 抽象

目标：

- 从“命令直接调用 Agent/工具”过渡到“Coordinator 创建 WorkerInvocation”。
- 为后续 worktree、容器和远端执行预留接口。

新增概念：

```text
WorkerSpec
WorkerInvocation
WorkerResult
WorkerFailure
SandboxPolicy
```

建议落盘：

```text
.asteria/runs/<run_id>/workers.jsonl
.asteria/runs/<run_id>/worker_results.jsonl
```

验收：

- 本地同步执行也通过 WorkerInvocation 记录。
- 每次执行都有 worker_id、task_id、agent_spec_id、allowed_tools、workspace_policy、budget。
- Worker 失败不会丢失 evidence。

### P3：Session Store 与 ContextSnapshot 强化

目标：

- 让 Session 成为恢复、复制和审计的中心对象。
- ContextSnapshot 从“摘要”升级为“可恢复运行状态索引”。

建议改动：

- 明确 `.asteria/current_session.json` 与 `.asteria/runs/<run_id>/` 的关系。
- 增加 session-level artifact index。
- ContextSnapshot 引用 artifact、decision、task、validation，而不是只写自然语言。
- `/resume` 基于 snapshot 恢复下一步 action。

验收：

- 用户可以从最近 snapshot 看懂当前任务状态。
- 系统可以基于 snapshot 继续计划、验证或报告。
- 压缩上下文不会丢失验收和失败证据。

### P4：Execution Isolation 渐进落地

目标：

- 把 Worker 的文件副作用从主工作区中逐步隔离。

阶段：

```text
1. 单工作区 + 严格 patch 记录
2. per-task 临时目录
3. Git worktree
4. 可选 Docker/轻量沙盒
```

验收：

- 每个任务能列出修改文件和产物。
- keep/discard 前能评审 diff。
- 隔离执行失败不会污染主工作区。

### P5：并发与多模型路由

目标：

- 在 TaskGraph、WorkerInvocation、Store 稳定后，再启用并发。

启用条件：

- 任务依赖图可验证。
- 写入范围可判定不冲突。
- Worker 结果可合并。
- 预算控制能按 worker 和 session 双层统计。
- 失败时能停止低价值分支。

多模型策略：

- planning、architecture、review 使用 strong。
- coding 使用 medium 或 strong，按任务风险选择。
- summarization、classification、format repair 使用 cheap。
- 模型选择必须记录到 ModelCall 和能力画像中。

验收：

- 支持至少两个只读任务并发。
- 支持多个 candidate 实现后选择 keep/discard。
- 并发不会绕过安全、预算和日志。

## 6. 技术实施路线

### 6.1 第一阶段：运行时对象补齐

目标：

- 先把无状态 Worker 所需的结构化对象补齐。
- 不改变外部 CLI 行为，降低重构风险。

优先实现：

```text
ModelProfile
ToolPermissionProfile
AccountProfile
SandboxProfile
ContextMount
WorkerInvocation
WorkerResult
WorkerFailure
ValidationResult
ArtifactIndex
```

建议文件：

```text
schemas/model_profile.schema.json
schemas/worker_invocation.schema.json
schemas/worker_result.schema.json
schemas/context_mount.schema.json
src/asteria_runtime/core/worker.py
src/asteria_runtime/core/runtime_profile.py
src/asteria_runtime/storage/worker_store.py
```

验收：

- schema 可以加载并校验示例对象。
- 本地同步执行也能生成 WorkerInvocation 和 WorkerResult。
- 不需要真实并发即可记录 agent、model、permission、context 和 budget 挂载信息。

### 6.2 第二阶段：TaskContract 升级

目标：

- 让任务从“自然语言列表项”升级成“可调度、可验证、可恢复的 contract”。

优先实现：

- 扩展 `task.schema.json`。
- 扩展 `TaskContract` Python 对象。
- 强化 `task_plan_quality_gate`。
- 让 `/plan` 和 `/execute` 读写同一套 contract 字段。

新增字段方向：

```text
input_refs
output_contract
read_scope
write_scope
context_requirements
validation_commands
failure_policy
parallel_safety
merge_strategy
```

验收：

- 缺少验收、输出或工具权限的任务不能进入执行。
- 写范围不明确的任务默认不允许并发。
- 每个失败任务能关联 FailureEvidence。

### 6.3 第三阶段：Coordinator 到 WorkerInvocation 的执行改造

目标：

- 把命令层直接调用 agent/tool 的路径，逐步改成 Coordinator 创建 WorkerInvocation。

改造顺序：

1. `/execute` 包装当前本地执行逻辑，先只增加记录。
2. `/run` 通过 WorkerInvocation 执行 ready task。
3. `/debug` 和 repair loop 使用 WorkerFailure/FailureEvidence。
4. `/review` 使用 ArtifactIndex 和 ValidationResult。

验收：

- 老命令继续可用。
- 每次执行都有 workers.jsonl 和 worker_results.jsonl。
- final report 能引用 worker 级执行摘要。

### 6.4 第四阶段：ContextMount 与恢复效率

目标：

- 不再把完整 session 直接塞给每个 Worker。
- 按任务类型生成最小可用上下文包。

优先实现：

- `ContextMountBuilder`。
- ArtifactIndex。
- FailureEvidence loader。
- recent event slice。
- task brief。
- goal brief。

上下文包类型：

```text
planning_context
coding_context
review_context
debug_context
summary_context
```

验收：

- debug task 优先加载失败证据和相关文件摘要。
- review task 优先加载 artifact index、diff、validation result 和 decision。
- cheap model 上下文包明显小于 strong review 上下文包。

### 6.5 第五阶段：隔离执行与并发预备

目标：

- 为真正并发和可丢弃 Worker 做准备。

实施顺序：

1. 增加 workspace policy，只记录不隔离。
2. 支持 per-task temporary workspace。
3. 支持 Git worktree worker backend。
4. 在只读任务上开启并发。
5. 在写任务上增加 scope conflict check。
6. 通过 merge/review gate 合并结果。

验收：

- 只读任务可并发执行且日志不混乱。
- 写任务如果 write_scope 冲突，Coordinator 必须串行或创建 DecisionPoint。
- Worker workspace 销毁前必须导出 artifact、diff 和 failure evidence。

### 6.6 第六阶段：多模型、多账号、多权限调度

目标：

- 用 profile 实现不同 Agent 使用不同模型、账号和权限。

优先实现：

- `ModelProfile` 与现有 model routing 对接。
- `AccountProfile` 只保存凭据引用，不保存 secret。
- `RuntimeRequestPolicy` / `ToolPermissionPolicy` 承接 runtime request、policy decision、read/write scope 和 ToolRegistry 权限检查，命令层只消费策略结果。
- `SandboxProfile` 与 workspace policy 对接。
- capability profile 反哺 Coordinator。
- ContextPackage 必须从“按 refs 汇总证据”升级为“按 `read_scope`、TaskContract 和 ContextMount 裁剪上下文包”，并显式包含 runtime request、worker result、validation 与 merge gate evidence。
- Sandbox backend 必须抽成统一 selector：干净 Git 仓库优先 `git_worktree`，否则回退 `temp_workspace` copy；RuntimeProfile 和 CandidateWorkspace 使用同一选择结果。
- Planner 生成宽泛 `write_scope` 时必须触发 scope quality 检查。能推断具体文件就收窄，不能推断则要求 worker 通过 runtime request 申请扩边界，而不是默认放大权限。
- 能力画像必须吸收 worker 成功率、validation pass rate、merge gate block 和 runtime request 类型，作为模型路由和后续 Planner/Coordinator 调整的反馈信号。

验收：

- Planner、Coder、Reviewer 可以在同一 session 中使用不同 model profile。
- 只读 Agent 不能调用写工具。
- 禁止网络 profile 不能触发网络工具。
- ModelCall 能记录 profile_id、purpose、provider、model、status 和 cost。

### 6.7 当前建议的第一批开发任务

近期真正开始代码重构时，建议按以下顺序开工：

1. 新增 `WorkerInvocation` / `WorkerResult` schema 和 core 类型。
2. 在现有 `/execute` 路径旁路记录 worker 执行，不改变行为。
3. 新增 `RuntimeProfile` / `ModelProfile` / `ToolPermissionProfile` 类型。
4. 扩展 `TaskContract`，补齐 read/write scope 和 validation contract。
5. 新增 `ContextMountBuilder`，先服务 debug/review 两类任务。
6. 更新验收测试，确保 worker 记录、task contract gate、context mount 都可验证。
7. 把 runtime request、policy decision 和工具权限从 `/execute` 下沉到 runtime policy 层，避免命令层直接承载边界规则。

这条路线的好处是：先让运行时学会“记录和表达”新架构，再逐步替换执行机制。系统不会因为一次性大重构而失去现有闭环。

## 7. 近期优先级

当前阶段最值得做的不是“马上拉起很多 Agent”，而是把以下基础打硬：

1. TaskContract 完整性。
2. TaskGraph 数据结构。
3. WorkerInvocation 记录。
4. FailureEvidence 标准化。
5. ContextSnapshot 可恢复性。
6. AcceptanceGate 与 RepairLoop 的硬停止策略。
7. AgentSpec 与 Session 的边界清理。

完成这些之后，再谈多 Agent 并发才不会变成不可控的聊天和副作用放大器。

## 8. 架构判断

这套方向的高明之处在于，它没有把 Agent 当作一个越来越长、越来越脆弱的对话窗口，而是把 Agent 放进了运行时系统：

```text
模型能力持续变化，所以补丁式 prompt 和记忆技巧会过时。
运行时边界、状态持久化、任务契约、沙盒隔离、验证修复和成本治理不会过时。
```

因此，本项目的长期竞争力不应建立在某个模型、某个提示词或某个单体 Agent 上，而应建立在：

- 清晰的控制平面。
- 可替换的模型接口。
- 可丢弃的执行单元。
- 结构化的任务与状态。
- 强制验证与失败证据。
- 本地优先的数据主权。
- 可审计的成本和安全边界。

这就是我们要吸收的核心。
