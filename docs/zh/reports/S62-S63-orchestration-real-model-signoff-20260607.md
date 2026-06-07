# S62/S63 Orchestration Real-Model 签字记录

**日期**：2026-06-07  
**状态**：signed — strong route + spawn eval 达到 maintainer 阈值  
**Provider**：OS 用户环境变量（strong: glm/zai · 本次 model-check `call_ok: true`）

## 摘要

| Eval | 命令 | 样本 | 命中率 | 阈值 | 结果 |
| --- | --- | --- | --- | --- | --- |
| **S62-4 route** | `orchestration_route_pulse.py --real` | 10 | **90%** (9/10) | ≥85% | ✅ |
| **S63 spawn** | `orchestration_spawn_pulse.py --real` | 23 | **95.7%** (22/23) | ≥90% | ✅ |

证据：

- `.asteria/verification/orchestration_route_real_20260607.json`
- `.asteria/verification/orchestration_spawn_real_20260607.json`

## S62-4 — Strong 语义路由

- **tier**：strong（`ORCHESTRATION_ROUTE_TIER`）
- **延迟**：单 case 最大 ~28.5s；10 case 合计 ~95s
- **miss**：`rm_plan_before_edit` — 模型调用失败 → `conservative_fallback` → `chat_answer`（非路由逻辑误判，属 provider 瞬时失败）
- **亮点**：`rm_chat_handoff`（chat 上下文 +「那就改吧」）正确路由 `cold_goal_execute`

## S63 — Spawn 决策

- **tier**：strong（`SPAWN_EVAL_TIER`）
- **小改 → tool**：15/15 ✅
- **大探索/独立验证 → subagent**：7/8 ✅
- **miss**：`api_surface_explore` — 模型判为单文件 readonly 用 `tool` 即可（边界案例；可接受争议，未放宽 golden）

## §5 放量状态

| 条件 | 状态 |
| --- | --- |
| real-model spawn golden ≥90% · n≥20 | ✅ 95.7% · n=23 |
| real-model route eval | ✅ S62-4 90% |
| 无新增 domain keyword dispatch | ✅（doc contract 仍绿） |
| maintainer signoff | ✅ 本文 |
| DecisionPoint 记录 | ⏳ defer（`spawn_parallel_workers` 仍 gray off） |

**结论**：spawn/route **eval 门槛已满足**；`parallel_writes` / `spawn_parallel_workers` **生产放量仍须 DecisionPoint**，不在本次自动开启。

## 维护者复跑

```powershell
python scripts/orchestration_route_pulse.py --root . --real `
  --summary-json .asteria/verification/orchestration_route_real.json
python scripts/orchestration_spawn_pulse.py --root . --real `
  --summary-json .asteria/verification/orchestration_spawn_real.json
```

CI（无 provider）：

```powershell
python scripts/orchestration_route_pulse.py --root .
python scripts/orchestration_spawn_pulse.py --root .
```
