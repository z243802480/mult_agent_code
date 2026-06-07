# S63 Spawn 决策调研报告

**日期**：2026-06-07  
**状态**：research baseline — 放量前须更新 golden eval  
**政策真源**：[ORCHESTRATION_DECISION_POLICY.md](../plans/ORCHESTRATION_DECISION_POLICY.md)  
**Brief**：[`benchmarks/reference_briefs/S63-cc-loop-convergence.md`](../../benchmarks/reference_briefs/S63-cc-loop-convergence.md)

---

## 1. 调研问题

1. 何时应在 **Studio 入口** 拆多个 worker？  
2. 何时应在 **Agent Loop** 内选 `subagent`？  
3. 规则/keyword/计数能否代替 strong 模型的语义理解？  

---

## 2. 结论（吸收产品讨论）

| 问题 | 结论 |
| --- | --- |
| Studio 入口拆 worker？ | **默认否**。Beta 保持 session_agent 单路径；`spawn_parallel_workers` catalog 项 **unavailable**。 |
| Loop 内 subagent？ | **是，由 strong 模型**读 manifest `when_to_use` / `when_not_to_use` 决定。 |
| 规则代替语义？ | **否**。`rules` 路由仅 maintainer CI；生产 `orchestration_router: model` + strong。 |
| cheap 做 route/spawn？ | **否**。cheap 仅机械/重复劳动（summarization 等）。 |

---

## 3. 对标 Claude Code（2026-06 公开文档）

- **Subagent**：模型读 `description` 按需 spawn；1–3 个在对话 turn 内。  
- **Dynamic Workflows**：10+ agent 时编排下沉脚本；**非**默认。  
- **无** keyword 列表决定「问答 vs 改代码」——语义在主 loop / 路由模型。  

Asteria 映射：

- Studio `route` ≈ CC 入口前薄层（strong + catalog），长期可并入 loop。  
- `AgentLoopDecision.subagent` ≈ CC subagent spawn。  
- 蜂群 parallel_writes ≈ CC workflows 方向，**defer** 至本报告 §5 条件满足。  

---

## 4. 已落实（代码 + 文档）

| 项 | 位置 |
| --- | --- |
| 政策单点 | `src/asteria_runtime/core/orchestration_spawn_policy.py` |
| Manifest subagent when_to_use | `AgentHarness` → `CapabilityManifest.subagents` |
| Catalog 与 policy 同源 | `catalog_selection_guidance()` |
| Route prompt 携带 policy JSON | `orchestration_router._model_route` |
| spawn_decision_policy 进 boundaries | `CapabilityManifest.boundaries` |
| spawn eval（S63-3 CI） | `orchestration_spawn_eval.py` · `orchestration_spawn_pulse.py` |
| chat→execute handoff（S62-5） | `studio/lib/chat-route-context.mjs` |
| 人读政策 | `docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md` |

---

## 5. 放量条件（未满足 — 保持 gray off）

在开启 `spawn_parallel_workers` 或 CLI `parallel_writes` 默认前，须：

- [x] CI golden（fake）：小改 **不** spawn / 大探索 **可** subagent  
- [x] real-model golden：95.7% 命中率，23 样本（`orchestration_spawn_pulse.py --real`）  
- [x] S62-4 real-model route eval：90% / 10 样本  
- [x] DecisionPoint 模板 — S64 `decision-orchestration-parallel-0001`（本地 `.asteria/decisions/`，待 resolve）  
- [ ] maintainer resolve → Wave 2 隔离 probe 执行  
- [ ] 无新增 domain keyword dispatch（doc contract 测试 — 持续 CI）  

---

## 6. 下一步（S63 编码）

1. ~~real-model spawn golden~~ ✅ — 见 [`S62-S63-orchestration-real-model-signoff-20260607.md`](./S62-S63-orchestration-real-model-signoff-20260607.md)  
2. ~~S62-4 route real eval~~ ✅  
3. DecisionPoint + 评估 `spawn_parallel_workers` 放量  
4. 长期：Studio `route` 并入 AgentLoop 首步（CC 完全对齐）  

---

## 7. 风险

| 风险 | 缓解 |
| --- | --- |
| strong route 延迟 | route-worker + cache（S62） |
| 模型误 spawn | when_not_to_use + merge 护栏 + 观测 spawn_decision_policy |
| 政策漂移 | 代码单点 + 本文 + ORCHESTRATION_DECISION_POLICY 同步改 |
