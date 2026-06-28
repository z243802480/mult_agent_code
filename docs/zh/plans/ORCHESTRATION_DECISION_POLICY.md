# 编排与 Spawn 决策政策

**版本**：1.0.0  
**状态**：冻结期架构参考 · 非当前工作（S63）— 编排能力已 opt-in 冻结，删/改编排代码前必读；不是 S74 工作。当前主线见 [`当前状态与路线.md`](../当前状态与路线.md) §4  
**日期**：2026-06-07  
**关联**：[CC_ORCHESTRATION_ALIGNMENT.md](./CC_ORCHESTRATION_ALIGNMENT.md) · [RUNTIME_MULTI_DISPATCH_MODEL.md](./RUNTIME_MULTI_DISPATCH_MODEL.md) §8.6 · 代码 [`orchestration_spawn_policy.py`](../../src/asteria_runtime/core/orchestration_spawn_policy.py)

---

## 0. 产品共识（2026-06 讨论吸收）

以下原则来自架构讨论，**已写入代码单点**，后续实现须先改 policy 再改行为：

| 共识 | 落地 |
| --- | --- |
| **抉择类必须 strong** | route、GoalSpec、Plan、Review、spawn 判断 — 不用 cheap |
| **cheap 只做体力活** | summarization、批量抽取、重复格式化 — **非** orchestration |
| **keyword/hybrid 不能假装 NLU** | 生产默认已删除 hybrid 快路径；`rules` 仅 CI |
| **spawn 由 strong 语义判断** | loop 内读 manifest `when_to_use`；禁止文件数/task 数机械拆 worker |
| **何时拆 worker 先调研** | `spawn_parallel_workers` gray off；放量见调研报告 §5 |
| **对标 CC 方向** | 模型读 capability 描述掌舵；程序守 schema/权限/预算/merge |

**曾尝试但拒绝的路径**：hybrid keyword 快路径（像问答对引擎、无法通用、与 CC 不一致）。

---

## 1. 目的

把产品讨论中达成的编排原则**写成可执行、可审计、可进 manifest 的政策**，避免：

- keyword / 规则假装理解用户意图  
- cheap 模型做 route 或 spawn 抉择  
- 程序按文件数、task 数机械拆 worker  

**代码真源**：`SPAWN_DECISION_POLICY`（Python 单点）→ catalog · route prompt · CapabilityManifest.boundaries。

---

## 2. 模型分层（tier 政策）

| 类别 | tier | 示例 purpose |
| --- | --- | --- |
| **抉择类** | **strong** | orchestration_route、goal_spec、planning、review、subagent 委派判断 |
| **执行类** | medium | coding、debugging（loop 内实现） |
| **机械类** | cheap | summarization、批量抽取、重复格式化（**非**路由/spawn） |

**冻结**：`orchestration_route` 固定 strong；不得用 `classification: cheap` 做 Studio 入口路由。

---

## 3. 两层编排

### 3.1 Studio 入口（RuntimeOrchestrationCatalog）

- strong 模型读 catalog + `SPAWN_DECISION_POLICY` → 选一个 capability  
- 显式 UI mode（chat/plan/run/…）→ 程序映射（非 NLU）  
- 默认边界：**session_agent 单路径**（cold / continue / chat）  
- **不在此层**按 keyword 或数量拆 worker  

### 3.2 Agent Loop（CapabilityManifest + AgentLoopDecision）

- strong/medium 执行模型每 turn 产出 `AgentLoopDecision`  
- `subagent`：仅当 manifest 中 `when_to_use` 与任务上下文匹配且 strong 判断需要隔离/并行探索/独立验证  
- Coordinator 多 worker：**仅**在 gray policy + 模型选中 + merge 护栏下执行  

---

## 4. Subagent：何时 spawn（语义，非机械）

### 4.1 可以选 `subagent`（loop 内）

- 只读探索面大，中间结果不应污染主 context  
- 需要与执行者隔离的独立验证 / 对抗审查  
- 可写 delegation brief：goal、约束、write scope、verification  
- **strong 模型**读完 task contract 与 manifest 后的判断  

### 4.2 不应 spawn

- 单文件/小范围改动，direct tools 一轮可完成  
- task contract 已适合 session_agent 串行  
- 用户仅问答或只读 plan  
- spawn 只增加 merge/协调成本而无收益  

### 4.3 程序护栏（非 NLU）

- `parallel_writes` policy、merge gate、DecisionPoint  
- schema：`parallel_safety`、`write_scope`、`risk_tier`  
- budget hard-stop  

---

## 5. 明确不做（defer）

| 项 | 原因 |
| --- | --- |
| keyword 入口快路径（hybrid NLU） | 无法通用；已删除生产默认 |
| cheap 模型 route/spawn | 抉择类必须 strong |
| 文件数/task 数阈值自动 spawn | 机械规则替代语义 |
| Studio 入口默认多 worker | 与 CC 1–3 subagent 在 loop 内不一致 |
| CC Dynamic Workflows 引擎移植 | defer；蜂群 Layer 1 已签字但 gray off |

---

## 6. 与 CC 对齐摘要

| CC | Asteria |
| --- | --- |
| 主 loop 模型选 tool/subagent | AgentLoopDecision + manifest when_to_use |
| subagent frontmatter description | CapabilityTool.description + when_to_use |
| 无 keyword route | strong route + catalog；rules 仅 CI |
| 10+ workflows | defer；调研后再定 |

---

## 7. 文档与证据

| 文档 | 作用 |
| --- | --- |
| 本文 | 政策真源（人读） |
| [CC_ORCHESTRATION_ALIGNMENT.md](./CC_ORCHESTRATION_ALIGNMENT.md) | CC 调研与映射 |
| [S63-spawn-decision-research-20260607.md](../reports/S63-spawn-decision-research-20260607.md) | 调研结论与放量条件 |
| `benchmarks/reference_briefs/S63-cc-loop-convergence.md` | Slice 验收 |

---

## 8. 变更规则

- 调整 spawn/route 政策：**先改** `orchestration_spawn_policy.py`，再同步本文与 CC 对齐 doc  
- 新增 dispatch 条件：**禁止** domain keyword 分支；须增加 manifest 描述 + golden eval  
- 放量 `spawn_parallel_workers`：须 S63 调研签字 + DecisionPoint  
