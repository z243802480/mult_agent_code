# S74 Week-1 DecisionPoint（正式）

**日期**：2026-06-09  
**状态**：正式 — 选项 1  
**依据**：[`S74_POST_S73_BETA_CONVERGENCE_PLAN.md`](../plans/S74_POST_S73_BETA_CONVERGENCE_PLAN.md) §S74-D · [`S74_WEEK1_CC_CODEX_EXECUTION_PLAN.md`](../plans/S74_WEEK1_CC_CODEX_EXECUTION_PLAN.md) W1-E · ADR-0010  
**证据**：`.asteria/verification/s74_beta_matrix_20260609.json` · `steady_iteration_check` 全绿 · CL-010 已落地 · run-scoped 一致审计

## 1. 矩阵摘要

| 槽位 | 路径 | 结果 | 耗时 | model/tool | repair |
| --- | --- | --- | --- | --- | --- |
| session_small_cli | session agent | ✅ 通过 | 46.8s | 2 / 5 | 0 |
| session_doc_update | session agent | ✅ 通过 | 43–51s | 2–3 / 2–3 | 0 |
| subagent_delegation | 契约灰度 | ✅ 护栏通过 | 0.2s | — | 0 |
| **subagent 真实委派** | subagent | ✅ **CL-010 后** | **114s** | **3–4** / 3–4 | 0 |

| 历史灰度（CL-010 前） | 明确委派 ~10 分钟 / 17 model calls | 效率不合格 |
| **CL-010 后复验**（2026-06-09） | ✅ 114s / **3 model calls** / 3 tool calls / 0 repair | 首轮 subagent dispatch；child plan ✅；父 loop 1 轮 completed |

## 2. 三选一裁决

**推荐：选项 1 — 继续维护默认关闭（opt-in 保留、不扩大默认）**

| 选项 | 条件对照 | 判断 |
| --- | --- | --- |
| 1 继续维护默认关闭 | opt-in 有价值但样本不足，或复杂路径不稳定 | **部分符合**：主路径与 doc_update 已分钟级；委派效率 CL-010 后达标（3 calls/114s），但仍缺外部 Beta 与 L3 样本 |
| 2 扩大显式 opt-in | 完成率、耗时、恢复均优于串行 | **不符合**：无外部 Beta 用户证据；L3/parallel_writes 未进本轮矩阵 |
| 3 回退/删除复杂路径 | 维护成本 > 收益 | **暂不符合**：subagent 契约与 spawn 护栏仍服务 scoped 委派；应 REPLACE 而非删除 |

## 3. 具体动作（服务总计划 S74 完成定义）

### 立即（Week-1 收尾）

1. ~~**P0 主路径**：调查 `validation_doc_update`~~ ✅ 已修复（51s / 3 model calls / 3 tool calls；见矩阵证据）。
2. ~~**P0 subagent 效率**~~ ✅ CL-010 后复验：`validation_subagent_delegation` 114s / 3 model calls（基线 17 calls / ~10min）。
3. ~~**P1 证据**~~ ✅：矩阵 JSON 统一字段；`user_progress_consistent` / `studio_runtime_consistent` 由 `s74_session_telemetry_audit`（run-scoped Studio benchmark，`audit_only`）填充。
4. ~~**P1 清算**~~ ✅：REGISTER Batch C — S9 brief 去除已删 catalog 恢复引用；CL-002/007 exit 更新。

### 禁止（Week-1 边界）

- 全局 `parallel_writes=true`
- 新编排 Wave / 新 slice 级 pulse 脚本
- 为 doc_update 单点失败加 keyword/parser 分支

### 下一阶段入口（S74 闭合后）

- 外部非维护者 Beta 试跑（F2 friction 桶）
- L3 workflow + parallel_writes opt-in 槽位进矩阵（maintainer only）
- DecisionPoint 正式化：若 doc_update + 委派复验稳定 → 评估扩大 opt-in 范围

## 4. 与研发总计划对齐

```text
总计划 ACTIVE_SLICE：S74 Post-S73 Beta convergence
Week-1 是 S74 的执行节奏，不是并行产品线
完成定义：基线绿 + 矩阵证据 + DecisionPoint + REGISTER 推进
产品投运前提：默认 Session 主路径可靠 → 本草案选「默认关闭、主路径优先修复」
```

## 5. 签字状态

**正式** — Week-1 完成定义已闭合：基线绿、4 槽矩阵、CL-010、run-scoped 一致审计、DecisionPoint 选项 1。
