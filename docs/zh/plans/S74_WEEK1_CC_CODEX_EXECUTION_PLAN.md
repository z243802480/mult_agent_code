# S74 Week-1 执行计划（CC / Codex 对标 · 组合化）

**状态**：ACTIVE  
**日期**：2026-06-09  
**Brief**：[`benchmarks/reference_briefs/S74-week1-cc-codex-execution.md`](../../benchmarks/reference_briefs/S74-week1-cc-codex-execution.md)  
**基线**：[`S74_REFERENCE_PRODUCT_BASELINE.md`](./S74_REFERENCE_PRODUCT_BASELINE.md) · [`S74_COMPLEXITY_LIQUIDATION_REGISTER.md`](./S74_COMPLEXITY_LIQUIDATION_REGISTER.md)  
**总计划**：[`研发总计划.md`](../研发总计划.md) · ACTIVE_SLICE **S74** · [`S74_POST_S73_BETA_CONVERGENCE_PLAN.md`](./S74_POST_S73_BETA_CONVERGENCE_PLAN.md)

## 0. 与总计划对齐（Week-1 是 S74 的执行节奏，不是旁支）

| 总计划 S74 完成定义 | Week-1 轨道 | 状态（2026-06-09） |
| --- | --- | --- |
| 1 文档真源一致 | W1-A | ✅ steady + doc contracts 绿 |
| 2 Execute 集成全绿 | W1-A / W1-C | ✅ 43 passed |
| 3 pulse 可复现 | W1-A | ✅ `steady_iteration_check` |
| 4 3–5 真实 Beta 统一报告 | **W1-D** | ✅ 4 槽（含真实委派） |
| W1-C 主路径效率 | CL-010 + 委派复验 | ✅ 114s / 3 model calls（基线 17） |
| 5 Studio/runtime 一致 | W1-D 字段 | ✅ run-scoped 审计（`s74_session_telemetry_audit`） |
| 6 DecisionPoint | **W1-E** | ✅ 正式（选项 1） |
| 7–8 复杂度审计 | W1-B | 🔄 CL-010 ✅；CL-002/007 exit ✅；Batch C S9 reachability ✅ |

**原则**：干扰项清理（删重复 pulse、过期引用）仅为 W1-A 子项；**不得替代** W1-D 矩阵与 W1-E 裁决。

## 1. 全局对标结论（一句话）

Claude Code 与 Codex 的共同产品形态是：**一条连续 Session + 模型在 observation 后自主选下一步 + 动作边界权限 + Inspector 查证**。  
Asteria 的差异化在 **本地证据链、candidate/promotion、多 provider、scoped opt-in 编排**——不在更多内部状态机或后置恢复流水线。

| CC / Codex 机制 | Asteria Week-1 对应 | 本周动作 |
| --- | --- | --- |
| Session 连续 Thread | Session Transcript 单一真源 | 维持；补缺失用户语义事件 |
| Subagent 结果回主会话 | 子 worker observation → 父 loop | **修：成功后停止父 loop**（CL-010） |
| Plan / Review / Debug 显式 | 删除 Run 自动 Review/Debug | 已完成；保持 |
| 权限在动作边界 | DecisionPoint + permission_preview | 维持；不建全局 Gate |
| Compact / 分层 memory | 角色上下文投影 + compact | Batch C 继续删重复 catalog |
| 真实过程建立信任 | 禁止合成成功 | 已完成 CL-008 |

## 2. 组合化工作包（5 天 × 可并行轨道）

```text
┌─────────────────────────────────────────────────────────────┐
│  Pulse 层：steady_iteration_check（含 S74 收敛测试）              │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ W1-A 真源    │ W1-B 删走偏  │ W1-C 主路径  │ W1-D 真实任务  │
│ doc/切片一致 │ REGISTER+删码 │ Execute/sub  │ Beta 矩阵 3–5  │
└──────────────┴──────────────┴──────────────┴────────────────┘
                              ↓
                    W1-E DecisionPoint 草案（周五）
```

### W1-A · 真源与脉搏（Day 1，✅ 可日更）

| # | 交付 | 退出条件 |
| --- | --- | --- |
| A1 | `python scripts/steady_iteration_check.py --root . --skip-b6 --skip-wheel` | 含 S74 收敛测试 + doc contracts 全绿 |
| A2 | `vibe_slices` / 状态文档 / brief 无过期 active | documentation contracts 无 stale 引用 |
| A3 | 无独立 Week-1 pulse 脚本 | 脉搏统一进 steady gate，Beta 矩阵仅保留 JSON 配置 |

**干扰项原则**：一个 active slice 只保留 **一条默认 maintainer 脉搏**（`steady_iteration_check`）；slice 签字脉搏、编排 eval 仅在 `--with-orchestration` 或 maintainer 显式调用时出现。

### W1-B · 复杂度清算（Day 2–3，一次一条）

| # | CL | 动作 | 验证 |
| --- | --- | --- | --- |
| B1 | CL-010 | subagent 成功后父 loop 不再因 `stop` 继续 | `test_execute_subagent_continuation` + Execute 集成 |
| B2 | reachability | 删 stale test/doc 引用（如已删 catalog 测试） | doc contracts |
| B3 | Batch C | 无消费者 schema/report 登记后删除 | golden traces + focused pytest |

**规则**：每项进 REGISTER → Golden Task → 单 diff → pytest → 更新 REGISTER 状态。

### W1-C · 主路径效率（Day 3–4，对标 CC subagent）

| # | 问题 | CC 做法 | Asteria 改法 |
| --- | --- | --- | --- |
| C1 | 委派任务 17 model calls | 子 Agent 完成即回主会话 | CL-010 已覆盖 |
| C2 | strong review 拖慢小任务 | Review 查证不二次编排 | 已有 deterministic-first；观察 bugfix 样本 |
| C3 | 父任务重入 repair | observation 回流同一 loop | 禁止 Debug 第二执行器（Batch A ✅） |

### W1-D · 真实 Beta 矩阵（Day 4–5）

Gate：`benchmarks/s74_beta_matrix_gate.json`（配置 only，非 pulse 入口）

| 路径 | 场景 | 记录字段 |
| --- | --- | --- |
| session agent | `validation_small_cli` | elapsed_*, model/tool calls, repair, goal_completed |
| session agent | `validation_doc_update` | 同上 |
| subagent | `runtime_delegation_contract` + 真实 provider 委派 | 父子 evidence、dispatch truth |
| opt-in | parallel_writes / L3 | 仅 maintainer；不扩默认 |

```powershell
python scripts/steady_iteration_check.py --root . --skip-b6 --skip-wheel
python scripts/real_model_acceptance.py --repo . --scenario validation_small_cli --fresh
```

### W1-E · 产品 DecisionPoint 草案（Day 5）

基于矩阵结果，三选一写入 `docs/zh/reports/S74-week1-decision-draft-YYYYMMDD.md`：

1. **继续维护默认关闭** — opt-in 有价值但样本不足  
2. **扩大显式 opt-in** — 复杂路径稳定优于串行  
3. **回退/删除复杂路径** — 维护成本 > 收益  

**禁止**：S74 Week-1 不批准全局 `parallel_writes=true` 或新编排 Wave。

## 3. 停止规则（与 POST_S73 计划一致）

- 基线未全绿 → 不开新 Slice  
- 无 reference + eval → 不保留劣质实现  
- 不为单点失败加 keyword/parser 尾巴  
- Studio 新面板需 friction top 桶（F2 规则）
- **默认 maintainer 脉搏唯一**：`steady_iteration_check`（含 S74 收敛测试）
- **brief/README/green_checks 不得引用已删模块**（doc contracts 扫描）
- 编排 eval 仅 `triple_track --with-orchestration` 或 maintainer 显式调用

## 4. 干扰项清理（持续）

| 类型 | 处理 |
| --- | --- |
| 重复 pulse | 合并进 steady gate，删除 slice 级 pulse 脚本 |
| 过期 brief / README | 随删除同步改；`test_reference_briefs_do_not_reference_deleted_paths` |
| 已闭合 slice active 引用 | 改 closed + reports 索引 |
| 无消费者代码 | REGISTER → 单 diff 删除 |

## 5. Week-1 完成定义

1. `steady_iteration_check` 默认路径全绿（含 S74 收敛测试） — **✅**  
2. CL-010 落地 + REGISTER 更新 — **✅**  
3. ≥3 个 Beta 矩阵槽位有统一 JSON 证据 — **✅**（见 `.asteria/verification/s74_beta_matrix_20260609.json`）  
4. DecisionPoint 草案完成 — **✅**（见 `docs/zh/reports/S74-week1-decision-draft-20260609.md`）  
5. 文档三源指向 S74 Week-1 进展 — **✅**（矩阵 + run-scoped 一致审计 + DecisionPoint 正式）

矩阵证据命令会在 `audit_policy.mode=audit_only` 下填充 `user_progress_consistent` / `studio_runtime_consistent` 与 `session_audit.telemetry`（SLO 仅 warning，不阻塞 matrix `ok`）。

## 6. 命令速查

```powershell
python scripts/steady_iteration_check.py --root . --skip-b6 --skip-wheel
python scripts/s74_beta_matrix_evidence.py --root .
pytest tests/integration/test_execute_command.py -q
python scripts/beta_friction_aggregate.py --root . --markdown
# 编排 maintainer（S74 默认不跑）
python scripts/triple_track_pulse.py --root . --skip-b6 --with-orchestration
```
