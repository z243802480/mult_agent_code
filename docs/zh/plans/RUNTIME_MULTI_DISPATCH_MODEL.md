# Runtime 多对多调度模型（Orchestrator · Coordinator · Worker）

**版本**：1.0.0  
**状态**：current — S61 R0–R5 哲学真源  
**日期**：2026-06-07  
**关联**：[RUNTIME_SESSION_AGENT_RFC.md](./RUNTIME_SESSION_AGENT_RFC.md) · [SWARM_SANDBOX_RFC.md](../deferred/SWARM_SANDBOX_RFC.md) · [大模型循环与动态上下文设计.md](../大模型循环与动态上下文设计.md) §3.1

---

## 1. 术语（项目既有语境，勿混用外来词）

| 术语 | 含义 | 代码/数据锚点 |
| --- | --- | --- |
| **Runtime** | 默认执行层；CC 级单会话 loop；证据异步落盘 | `execution_profile=session_agent` · S17 RFC Layer 0 |
| **Harness** | 显式多 task 图 + replan lineage + repair_limit + promotion | `execution_profile=harness` · S17 Layer 1 |
| **Goal Loop** | 核心 Agent Loop：调度、收敛、验收 | `AgentLoopDecision` · GoalSpec/Plan/Execute/Review |
| **Orchestrator run** | 用户一次 Goal 对应的编排单元（可 spawn 子 worker） | `swarm_orchestrator.py` · SWARM RFC |
| **Coordinator** | 任务图调度与多路 dispatch（**多对多**） | `ExecutionCoordinator` · `TaskGraphScheduler` |
| **Worker** | Coordinator 启动的一次执行挂载（非「Boss 的对立面」） | `workers.jsonl` · `worker_invocation_id` · `RuntimeProfile` |

**不用 Boss/Worker 作为产品名词**：Boss/Worker 仅作 **Netty 三种线程池** 的类比，说明「调度面可并行、执行面可多实例」，**不引入新层级命名**。

---

## 2. 两层执行 + 三层调度（与 S17 / 蜂群一致）

### 2.1 产品两层（已有）

```text
Layer 0 — Runtime（默认）
  session_agent：单任务、会话内 retry
Layer 1 — Harness / 蜂群（显式）
  harness + candidate + merge gate
  parallel_writes CLI 默认 off
```

### 2.2 调度三层（Netty 类比 · 多对多）

类比 Netty **Boss / Worker / Business** 三组线程池的**关系**，映射到 Asteria **已有组件**（非新命名）：

```text
┌─ 编排面（Orchestrator / Goal Loop · strong）──────────────┐
│  GoalSpec · Plan · risk_tier · North Star 监督              │
│  child_plan → SwarmOrchestrator                           │
│  小目标可 collapse 为单 task，不强行 spawn                  │
└───────────────────────────┬───────────────────────────────┘
                            │ 任务图 / spawn plan
┌─ 协调面（Coordinator · 可多路并行 dispatch）──────────────┐
│  ExecutionCoordinator                                     │
│  · serial（默认 Beta）                                     │
│  · parallel_readonly（fanout 多对多）                      │
│  · parallel_safe_batch / parallel_writes（gray）            │
│  TaskGraphScheduler · agent_loop_dispatch                 │
└───────────────────────────┬───────────────────────────────┘
                            │ N × worker_invocation
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   Worker 执行面        Worker 执行面        Worker 执行面
   RuntimeProfile       RuntimeProfile       RuntimeProfile
   session_agent        harness+cw           readonly
   (AgentLoop)          (AgentLoop)          (AgentLoop)
```

**多对多**：一个 Orchestrator run 可 dispatch **多个** Worker；每个 Worker 挂载独立 `RuntimeProfile`；Coordinator 按 `parallel_safety` / task 图选择 **串行或批量并行**（见 `ExecutionCoordinator.execute_selection` + `ThreadPoolExecutor`）。

---

## 3. 与 Claude Code 的吸收（进 Runtime Agent，非定向优化）

| CC 机制 | Asteria 落点 | 调度层 |
| --- | --- | --- |
| QueryEngine loop | Worker 执行面 · session_agent | 执行面 |
| CLAUDE.md | `prompt_envelope` + AGENTS.md | 共享 |
| Plan / strong 分解 | Goal Loop · GoalSpec/Planner | 编排面 |
| Subagent / 并行 | Coordinator dispatch · worker_spawn | 协调面 |
| tool_use | Worker transport（S61 R4） | 执行面 |
| Hooks | runtime_policy · shell_guard | 全层确定性护栏 |

差异与先进性：**Coordinator 多对多 + Harness 可审计合并**；CC 偏单会话，Asteria 蜂群 Layer 1 已签字（CLI 默认不放量）。

---

## 4. 「最强大脑」在哪（勿新建 Boss 角色）

强模型默认在 **编排面**（GoalSpec、Plan、复杂 review），不在 Worker 执行面堆 domain 分支：

- **编排面**：分解、risk_tier、spawn 决策、合并监督  
- **协调面**：规则 + 任务图；`parallel_readonly` / `parallel_writes` 由 policy 与 plan 驱动  
- **执行面**：medium 默认；capability_feedback 可升档；**同一套** AgentLoop + tool surface  

编排面 **具备** Runtime 的全部能力（可 collapse 为单 task 自执行），但职责偏向调度与契约，而非替每个 Worker 写实现细节。

---

## 5. S61 五阶段在本模型上的落点

| 阶段 | 编排面 | 协调面 | 执行面（Worker） |
| --- | --- | --- | --- |
| R0 | 本文 + 术语冻结 | — | — |
| R1 | — | — | 回滚 S60 domain 分支 |
| R2 | risk_tier 进 plan/goal_spec | Coordinator 读 plan 并行策略 | profile 由契约非关键词 |
| R3 | orchestration_discipline | — | execution_discipline |
| R4 | Plan structured output | — | tool_use transport |
| R5 | validation 进 plan | merge 前 evidence | preparer 执行契约 |

---

## 6. 冻结原则

1. **Runtime 默认、Harness/蜂群叠加**（S17 + SWARM RFC）  
2. **Coordinator 多对多可并行，写并行必 candidate + merge**  
3. **prompt/policy/contract 积累 > domain 代码分支**（对齐 [大模型循环](../大模型循环与动态上下文设计.md) §3.1 反模式）  
4. **execute/run 主链稳定**；调度能力通过 Coordinator / profile 扩展  
5. Netty 类比只说明**调度拓扑**，不引入 Boss 产品概念  

---

## 7. 非目标

- 不重命名 Runtime/Harness/Orchestrator/Coordinator/Worker  
- 不为单一场景（静态页等）加执行面特化  
- 不默认开启 parallel_writes  

---

## 8. 模型掌舵（Model-Steered Orchestration）

**结论（North Star 编排哲学）**：

```text
Runtime 提供标准能力与确定性护栏；模型读 ContextEnvelope + CapabilityManifest，决定体系如何运转。
编排面 / 协调面 / 执行面不是写死在 if/else 里的固定流水线，而是模型可理解、可选、可审计的能力单元。
```

### 8.1 两类编排（现状 vs 目标）

| | **程序编排（当前 Beta 缺口）** | **模型掌舵（目标）** |
| --- | --- | --- |
| 谁选路径 | Studio/CLI router + RunCommand 状态机 | 模型读用户句 + 上下文，产出 `AgentLoopDecision` |
| Plan | cold `run` 必经 GoalSpec/Plan | 用户语义像「先想清楚」→ 只读 plan；像「直接改」→ 短链 execute |
| 续作 | 规则路由（`ACCEPTED` → `--continue-session`） | 模型识别续改语义，选 resume / 同 run 追加 / compact |
| 并行 / 蜂群 | policy 与 profile 硬开关 | 模型见 capability 描述后选 subagent / Coordinator dispatch |
| 护栏 | — | **仍由程序强制**：权限、预算、schema、merge gate、不可逆动作 |

Claude Code / Codex 的典型形态是 **model-orchestrated**：用户一句话 → 模型解析 intent → 该 plan 就 plan、该短链就短链、该拆 subagent 就拆。  
Asteria **能力更强、证据更全**，但若用固定程序流水线默认激活全套 Harness，会「杀鸡用牛刀」；**盘活方式**是把能力描述清楚交给模型，而不是再加 domain 分支。

### 8.2 模型可见的能力语言（盘活整体的关键）

模型不读代码里的 `if (phase == ACCEPTED)`，而读标准化上下文：

| 输入 | 作用 |
| --- | --- |
| **ContextEnvelope** | 目标、active_goal_memory、run 相位、blocker、context pressure |
| **CapabilityManifest** | 当前可调度的 tools / MCP / skills / subagent / plan / execute / review / accept |
| **编排面能力** | GoalSpec、Planner（structured plan）、risk_tier、North Star 监督 |
| **协调面能力** | serial / parallel_readonly / parallel_writes（含 merge 前提与 gray 状态） |
| **执行面能力** | session_agent 单写者 loop、harness 多 task、worker transport（json / tool_use） |
| **Observation 回灌** | tool / subagent / review 结果 → 下一轮 decision |

**原则**：每加一项特性（并行、Coordinator、新 transport、warm 续作），必须在 manifest + envelope 里增加 **模型可消费的说明与约束**，而不是只在 Python/Studio 里加一条硬路由。

### 8.3 三层调度 = 能力目录，不是固定脚本

```text
用户目标 + 上下文
        │
        ▼
   模型决策（AgentLoopDecision）
   · tool | subagent | repair | replan | ask | stop
   · 可选：只读 plan 文本（不进 run 契约）
   · 可选：spawn → Coordinator 多路 dispatch
        │
        ▼
   Runtime 执行 + Gate + Evidence
        │
        ▼
   Observation → 下一轮模型决策
```

- **Orchestrator**：分解、契约、spawn 决策——模型**可调用**，非每次 cold 必跑。  
- **Coordinator**：任务图与多对多 dispatch——模型**可请求**，写并行仍受 candidate/merge 约束。  
- **Worker / 执行器**：挂载 `RuntimeProfile` 的 AgentLoop——模型通过 `subagent` 或 execute 路径选用。  

程序只保证：**选了的 path 有 schema、有证据、有预算上限**；不替模型写「小改也必须 Plan→Execute→Review 全链」。

### 8.4 与现有文档的关系

- 能力原子化、反硬编码：`大模型循环与动态上下文设计.md` §3.1  
- AgentLoopDecision 契约：`Asteria 模型主导运行时设计.md` §2–3  
- session_agent 默认、Harness 叠加：`RUNTIME_SESSION_AGENT_RFC.md`  
- warm `--continue-session`：**程序层桥接**（同 workspace 续改），目标态改为模型 semantic routing  

### 8.5 实现方向（不写死，只列约束）

1. **Semantic routing slice**：`asteria route` + `RuntimeOrchestrationCatalog` + Studio 调用（✅ 首版）；模型读 capability 界面，程序执行护栏。  
2. **CapabilityManifest 扩展**：`orchestration_paths` 已挂入 chat context / manifest（✅）。  
3. **Studio 默认**：用户消息 → `route` 选 capability → permission / execute（✅ 首版，policy `studio.orchestration_router=model`）。  
4. **禁止**：为 web/doc/coding 等场景新增 `if domain == …` 执行分支；应用 manifest + model decision 替代。  

**冻结**：确定性护栏（权限、预算、schema、merge、hard-stop）永不交给模型绕过；**弹性路径**交给 strong 模型。

### 8.6 CC 对齐 · spawn 决策（research-first）

- **入口 route（S62）**：strong 读 `RuntimeOrchestrationCatalog`；默认 session_agent 单路径；不在 Studio 机械拆 worker。  
- **Loop 内 subagent（S63）**：与 CC 相同——模型读 manifest `description` / `when_to_use` 决定是否 `subagent` action。  
- **defer**：按文件数/task 数/keyword 自动 spawn；cheap 模型做 spawn 抉择；CC Dynamic Workflows 引擎移植。  
- 调研真源：[`CC_ORCHESTRATION_ALIGNMENT.md`](./CC_ORCHESTRATION_ALIGNMENT.md) · brief [`S63-cc-loop-convergence.md`](../../benchmarks/reference_briefs/S63-cc-loop-convergence.md)。
