# Claude Code 编排对齐（调研 · 方向）

**版本**：0.1.0  
**状态**：research-first — 编码前必读  
**日期**：2026-06-07  
**关联**：[ORCHESTRATION_DECISION_POLICY.md](./ORCHESTRATION_DECISION_POLICY.md) · [`RUNTIME_MULTI_DISPATCH_MODEL.md`](./RUNTIME_MULTI_DISPATCH_MODEL.md) §8 · [`S63-cc-loop-convergence.md`](../../benchmarks/reference_briefs/S63-cc-loop-convergence.md) · 报告 [`S63-spawn-decision-research-20260607.md`](../reports/S63-spawn-decision-research-20260607.md)

---

## 1. 原则（产品共识）

```text
学 CC 机制，不抄形态。
抉择（路由、是否 spawn、plan vs execute）→ strong 模型 + capability 描述。
程序只做：显式 mode、available 约束、权限/预算/merge/schema。
何时拆 worker → 调研后由模型语义判断，不用 keyword / 任务数 / 文件数机械拆分。
```

---

## 2. CC 公开机制摘要（2026-06）

| 机制 | CC 做法 | Asteria 映射 |
| --- | --- | --- |
| **主 loop** | 每 turn 模型选 tool / subagent / 继续对话 | `AgentLoopDecision`（tool · subagent · repair · replan · ask · stop） |
| **Subagent** | Markdown frontmatter + `description`；模型**读描述**决定是否 spawn | `CapabilityManifest.subagents` + `capability_ref` |
| **Explore 内置** | Haiku + 只读 tool，模型**按需**委派 | readonly fanout · session_agent 默认不单开 |
| **Dynamic Workflows** | 10+ agent、编排进脚本；**非**默认路径 | 蜂群 Layer 1（gray）；**defer** 直到 strong loop 稳定 |
| **路由** | 无独立 keyword route；语义在主 loop | Studio `route` = **入口薄层**（strong + catalog），长期并入 loop |

**CC 不做的**：用「句子里有 implement/fix」决定路径；用文件数量阈值自动 spawn N 个 worker。

---

## 3. Asteria 两层编排（对齐 CC）

```text
┌─ Studio 入口（S62 · strong route）────────────────────────────┐
│  用户消息 + RuntimeOrchestrationCatalog                        │
│  → 选一条 capability：chat | plan | run | continue | resume …   │
│  默认：session_agent 单路径；不在这里机械拆 worker              │
└────────────────────────────┬──────────────────────────────────┘
                             ▼
┌─ Agent Loop（S63 收敛目标 · CC 主战场）────────────────────────┐
│  strong/medium 执行模型 + CapabilityManifest                     │
│  → AgentLoopDecision：tool | subagent | repair | …              │
│  subagent：模型判断需要隔离上下文 / 并行探索 / 独立验证时才 spawn │
│  Coordinator：仅执行模型已选 decomposition + merge 护栏         │
└────────────────────────────────────────────────────────────────┘
```

**`spawn_parallel_workers`（Studio catalog）**：maintainer gray 能力；Beta 默认 **unavailable**。  
生产默认不应在入口按规则拆 worker；若未来放量，仍须 **strong 模型选 capability + policy gray**，而非程序数 task 拆片。

---

## 4. 何时拆 worker？— 调研结论（当前）

| 问题 | 结论 |
| --- | --- |
| 现在就该默认并行吗？ | **否**。session_agent 单写者 + loop 内 subagent 已覆盖 CC 1–3 agent 场景。 |
| 谁决定 spawn？ | **Loop 内 strong 模型**读 manifest `when_to_use` / risk / scope；不是 Planner 硬编码 child_count。 |
| 机械规则能代替语义吗？ | **不能**。keyword、文件数、task 数阈值仅可作 telemetry 告警，不作 dispatch 条件。 |
| 何时做 Dynamic Workflow 级编排？ | Phase 5 蜂群已签字但 CLI gray off；待 S63 loop 收敛 + 真实任务 eval 后再开调研 gate。 |

### 4.1 模型应何时选 `subagent`（loop 内，非入口）

与 CC subagent `description` 同构，供 strong 模型读：

- 探索面大、中间结果不应污染主 context（只读 fanout）
- 独立验证 / 对抗审查（与执行者隔离）
- 子任务 scope 清晰、可写 delegation brief + verification
- **不应 spawn**：单文件小改、已有 task contract、session_agent 一轮 tool 可完成

### 4.2 程序护栏（非 NLU）

- `parallel_writes` policy + merge gate
- `capability.available` / risk_tier / write_scope schema
- budget hard-stop、DecisionPoint

---

## 5. 与 S62 / S63 关系

| Slice | 内容 | 状态 |
| --- | --- | --- |
| **S62** | Studio strong route · 去 keyword · route-worker | ✅ |
| **S63** | Loop 收敛：spawn policy · spawn/route real eval | ✅ eval 签字 |
| **defer** | 入口 mechanical 多 worker · Workflow 脚本引擎 · cheap route | 明确不做 |

---

## 6. 验收方向（S63）

- golden：小改 **不** spawn；大探索 **可** subagent — real **95.7%** / 23 ✅  
- strong route — real **90%** / 10 ✅（[`S62-S63-orchestration-real-model-signoff-20260607.md`](../reports/S62-S63-orchestration-real-model-signoff-20260607.md)）  
- 无新增 domain keyword dispatch  
- `orchestration_discipline` + catalog 与 loop manifest 同源 — ✅  
- 调研报告：[`S63-spawn-decision-research-20260607.md`](../reports/S63-spawn-decision-research-20260607.md)

---

## 7. do_not_copy

- CC Dynamic Workflows JS runtime 整包
- 按 task 数 / 文件数自动 `ThreadPoolExecutor`
- cheap 模型做 orchestration / spawn 抉择
