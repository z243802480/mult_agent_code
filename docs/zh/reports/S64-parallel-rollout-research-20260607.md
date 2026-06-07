# S64 并行编排放量调研报告

**日期**：2026-06-07  
**状态**：research baseline — Wave 2 就绪；生产默认仍 off  
**Brief**：[`S64-orchestration-parallel-gray-rollout.md`](../../benchmarks/reference_briefs/S64-orchestration-parallel-gray-rollout.md)  
**政策**：[`ORCHESTRATION_DECISION_POLICY.md`](../plans/ORCHESTRATION_DECISION_POLICY.md)  
**前置 eval**：[`S62-S63-orchestration-real-model-signoff-20260607.md`](./S62-S63-orchestration-real-model-signoff-20260607.md)

---

## 1. 调研问题

1. 主流产品如何默认并行、何时放量、用什么护栏？  
2. Asteria 在 S63 eval 通过后，下一档放量应放哪一层？  
3. 能否跳过 DecisionPoint / merge 直接开 `parallel_writes`？

---

## 2. 主流做法摘要（2026-06 公开资料）

### 2.1 Claude Code

| 机制 | 做法 |
| --- | --- |
| **默认** | 主 loop turn-by-turn；subagent **按需** spawn（读 description） |
| **loop 内并行** | 独立任务可并行 subagent；**无官方硬上限**，受 rate limit / token 成本约束 |
| **实践建议** | 社区与文档倾向 **≤3–4 并行 Opus**；prompt 可写「最多 N 个 subagent」 |
| **大规模** | **Dynamic Workflows**：脚本编排；**16 并发 agent / run**，**1000 agent/run** 上限 |
| **不做** | keyword 决定 spawn；机械按文件数拆 agent |

**启示**：默认轻、并行靠**模型语义 + 成本护栏**；大规模编排**下沉脚本**，不进主 context。

### 2.2 Cursor

| 机制 | 做法 |
| --- | --- |
| **默认** | 前台 Agent 交互；长任务走 **Background Agents** |
| **并行** | Pro **≤8 并发** cloud agent；各 agent **独立分支 + 远程环境** |
| **护栏** | delegate-and-review；任务需 **well-scoped + stopping conditions**；合并前 CI/PR |
| **不做** | 同 workspace 无隔离的多写者默认并行 |

**启示**：并行 = **隔离环境 + 分支 + 人工/CI 合并**，不是同 session 多写者抢 merge。

### 2.3 对比 Asteria

| 维度 | CC | Cursor | Asteria（目标） |
| --- | --- | --- | --- |
| 默认路径 | 主 loop | 前台 Agent | **session_agent 单写者** |
| 小并行 | loop subagent | — | **AgentLoopDecision.subagent** |
| 大并行 | Workflows 脚本 | Background ×8 | **Coordinator gray + merge**（Phase 5） |
| 抉择 | strong 语义 | 用户委派任务 | **strong route/spawn + DecisionPoint** |

---

## 3. 结论：放哪一层？

| 层级 | 建议 | 理由 |
| --- | --- | --- |
| **Loop subagent** | 已具备；继续 observability | 对齐 CC 1–3 agent；S63 spawn eval 95.7% |
| **CLI `parallel_writes`** | **Wave 2：仅 maintainer 隔离 probe** | 复用 S32 rollback + dual_disjoint；Beta 默认 **false** |
| **Studio `spawn_parallel_workers`** | **Wave 3**；须 Wave 2 probe + strong route 选中 | 入口不 mechanical 拆 worker |
| **CC Workflows 级** | **defer Wave 4** | 需真实 disjoint 生产证据 |

**禁止**：因 S63 eval 通过就默认开 `parallel_writes` 或 catalog 可用 — 缺少 **Wave 2 隔离 probe + DecisionPoint**。

---

## 4. Wave 计划（Asteria）

```text
Wave 0  session_agent 默认                    ✅
Wave 1  strong route + spawn policy + eval    ✅ S62/S63
Wave 2  maintainer parallel_writes 隔离 probe  ← S64 当前
Wave 3  spawn_parallel_workers catalog gray   defer
Wave 4  workflows 级编排                        defer
```

### Wave 2 准入（代码：`orchestration_parallel_gray.py`）

- [x] S63 spawn real eval ≥90%，n≥20  
- [x] S62 route real eval ≥85%，n≥8  
- [x] `ORCHESTRATION_DECISION_POLICY.md` 存在  
- [x] `parallel_writes` CLI 默认 false  
- [ ] S32 gray rollback drill（maintainer `--gray-drill-ok` 或新 drill 证据）  
- [ ] DecisionPoint 写入 `.asteria/decisions/`（`--write-decision`）

---

## 5. 已落实（S64-1）

| 项 | 位置 |
| --- | --- |
| 主流调研 | 本文 §2 |
| Wave 计划 | 本文 §4 · brief S64 |
| 就绪评估 + DecisionPoint | `orchestration_parallel_gray.py` |
| maintainer pulse | `scripts/orchestration_parallel_gray_pulse.py` |
| gate | `benchmarks/orchestration_parallel_gray_gate.json` |

---

## 6. 下一步（Wave 2 执行，非默认开启）

1. maintainer 跑 `orchestration_parallel_gray_pulse.py --gray-drill-ok --write-decision`  
2. 人工 resolve DecisionPoint → `wave2_maintainer_probe`  
3. 复用 S34 `dual_disjoint_files` / S32 drill 于 **隔离 run_dir**  
4. Wave 2 签字后，再评估 Wave 3 catalog 可用性（仍须 strong route 选中）

---

## 7. 风险

| 风险 | 缓解 |
| --- | --- |
| CC/Cursor 并行形态不同，照抄失败 | Wave 分档；Beta 保持 session_agent |
| 模型 over-spawn | S63 eval + when_not_to_use + merge |
| 无 rollback 放量 | S32 drill 必前置；DecisionPoint 默认 defer |
