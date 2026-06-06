# 蜂群 Sandbox 并行写 RFC（Phase 5）

**状态**：defer — S17 session_agent 已签字；蜂群 **显式 harness 层** 待 Phase 5 启动  
**关联**：[RUNTIME_SESSION_AGENT_RFC.md](../plans/RUNTIME_SESSION_AGENT_RFC.md) · ADR candidate / merge gate

---

## 1. 设计分层（与 S17 对齐）

```text
Layer 0 — Runtime（默认）
  session_agent：单 Agent 会话，CC 级 tool→verify→retry
  证据异步落盘；无 replan lineage

Layer 1 — Harness（蜂群 / 多写者 / 晋升）
  execution_profile = harness
  candidate workspace → promotion → merge gate
  repair_limit · DecisionPoint · worker 证据仲裁
```

**原则**：Runtime 先像 CC；蜂群不是改 Runtime，而是在其上叠加 **可审计的多写者合并**。

---

## 2. 蜂群产品单位

| 概念 | 定义 |
| --- | --- |
| **Orchestrator run** | 用户 Goal；Plan 分解为可并行 worker 任务 |
| **Worker** | 独立 `session_agent` 或 `harness` 子 run，绑定 candidate workspace |
| **Evidence bundle** | 每 worker 的 task_execution + verification + diff |
| **Promotion** | 候选区改动经 merge gate 进入主工作区 |
| **Merge gate** | schema 验证 + conflict detection + 维护者/策略签字 |

---

## 3. Worker execution_profile 策略

| Worker 场景 | profile | 说明 |
| --- | --- | --- |
| _disjoint 文件实现_ | harness | 需 promotion；write scope 互斥 |
| _只读调研 fanout_ | session_agent | readonly tools；无 promotion |
| _Beta 单用户小改_ | session_agent | **不经过蜂群** |
| _跨模块 / 高风险_ | harness | 完整 DecisionPoint + merge gate |

默认：**worker 写路径 = harness**；只读 fanout = session_agent。

---

## 4. 与 Claude Code / 定时任务的差异

| | CC + Cron | Asteria 蜂群 |
| --- | --- | --- |
| 并行 | 独立 session | worker + 同源 evidence |
| 合并 | 人工 | promotion + merge gate |
| 审计 | 终端历史 | `.asteria/` 可签字 |
| 长任务 | 单 loop 拉长 | orchestrator + worker 预算 |

---

## 5. 启动条件（Phase 5 gate）

1. ✅ S7 MVP、S17 session_agent Beta 路径稳定（B6 连续绿、doc_update dogfood）
2. ⏳ sandbox 全链路：fake → 1 readonly 灰度 → 1 disjoint-write 灰度
3. ⏳ `disjoint_write_gate` feature flag 与 rollback 演练
4. ⏳ Studio：worker 进度 + merge 证据 Inspector（非主屏 gate 词汇）

**仍关闭**：`parallel_writes` CLI 默认 `false`；12 Agent 新类；真实 sandbox 生产放量。

---

## 6. 实现里程碑（建议 Slice）

| Slice | 交付 | green_checks |
| --- | --- | --- |
| S18 | Worker spawn 契约 + harness profile 强制 | unit tests + fake worker path |
| S19 | candidate export + merge gate dry-run | integration + schema |
| S20 | Studio worker 进度条 + promotion UI | smoke mjs |
| S21 | 1 disjoint-write 灰度（maintainer） | SWARM gate json |

---

## 7. 非目标

- 不替换 Runtime session_agent 默认路径
- 不在 Beta 主屏暴露 gate / repair_limit 词汇
- 不复制外部产品专有 swarm 实现

---

## 8. 参考

- `src/asteria_runtime/core/execution_profile.py`
- `src/asteria_runtime/core/multi_agent_strategy.py`
- `benchmarks/reference_briefs/S17-runtime-session-agent.md`
- 研发总计划 Phase 5 · §6 KEEP_PLACEHOLDER
