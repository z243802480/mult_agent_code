# 蜂群 Sandbox 并行写 RFC（Phase 5）

**状态**：S18–S21 ✅ Phase 5 蜂群入口已签字；真实 parallel_writes 仍 defer  
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
2. ✅ sandbox 契约链：fake → export → dry-run → Studio（S18–S21）
3. ⏳ `real_disjoint_write_workers` feature flag 生产灰度 + rollback 演练
4. ✅ Studio：worker 进度 + merge 证据 Inspector（S20）

**仍关闭**：`parallel_writes` CLI 默认 `false`；12 Agent 新类；真实 sandbox 生产放量。

---

## 6. 实现里程碑（建议 Slice）

| Slice | 交付 | 状态 |
| --- | --- | --- |
| S18 | Worker spawn 契约 + harness profile 强制 | ✅ |
| S19 | candidate export + merge gate dry-run | ✅ |
| S20 | Studio worker 进度条 + promotion UI | ✅ |
| S21 | 1 disjoint-write 灰度（maintainer） | ✅ |

**闸门**：`benchmarks/phase5_swarm_gate.json` · `scripts/swarm_maintainer_gray_check.py`

---

## 7. 非目标

- 不替换 Runtime session_agent 默认路径
- 不在 Beta 主屏暴露 gate / repair_limit 词汇
- 不复制外部产品专有 swarm 实现

---

## 8. 参考

- `src/asteria_runtime/core/execution_profile.py`
- `src/asteria_runtime/core/worker_spawn.py`
- `src/asteria_runtime/core/swarm_pipeline.py`
- `docs/zh/reports/phase5-swarm-entry-signoff-20260606.md`
- 研发总计划 Phase 5 · §6 KEEP_PLACEHOLDER
