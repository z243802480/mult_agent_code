# S74 真实 Beta 任务矩阵签字 — 2026-06-28

**结论：PASS**（4/4 slot recorded，audit-only 非阻塞）。M2 两类失败（模型合规 / 传输）已关，
session + subagent 双路径在真实 provider 上稳定通过，具备进入放量 DecisionPoint 的证据基础。

- Runner：`python scripts/s74_beta_matrix_evidence.py --root . --live`
- Gate：`benchmarks/s74_beta_matrix_gate.json`（audit_policy: audit_only, matrix_blocking=false）
- 原始证据（本机）：`.asteria/verification/s74_beta_matrix_20260628.json`
- Providers：medium=`minimax`，strong=`glm-5`（路由解析为 `zai / glm-5.2`）
- run_id：run-20260628-0001

## 统一结果

| slot | path | goal | artifact | elapsed_total | model_calls | tool_calls | repair | replan | user_progress | studio_runtime | SLO |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| session_small_cli | session_agent | ✅ | ✅ | 124.2s | 2 | 4 | 0 | 0 | ✅ | ✅ 1.0 | pass |
| session_doc_update | session_agent | ✅ | ✅ | 144.9s | 2 | 2 | 0 | 0 | ✅ | ✅ 1.0 | pass |
| subagent_delegation¹ | subagent | ✅ | ✅ | 0.6s | — | — | 0 | 0 | ✅ | ⚠️ 0.75 | pass |
| subagent_real_delegation | subagent | ✅ | ✅ | 292.2s | 4 | 2 | 0 | 0 | ✅ | ✅ 1.0 | pass |

¹ `runtime_delegation_contract`：非真实 provider 的轻量合约探针（0.57s，summary 仅 run_id+runtime_os）。

## 关键结论

- **4/4 goal_completed + artifact_verified；全程 0 repair / 0 replan。**
- **强弱委派成立**：`goal_spec` 走 medium(minimax)，`task_execution` 走 strong(zai/glm-5.2)，
  `strong_used=true` 全覆盖——默认强模型 + 体力工作给中档的委派机制按设计生效。
- **传输稳定**：strong 首块一度慢到 50.9s / 127.4s，仍**无 provider_timeout**——
  strong-tier deadline headroom（×1.7，commit `a28f1ea`）在多场景真实 run 中验证有效。
- **SLO 全 pass**：model_calls ≤ 8（实际 2–4）、repair ≤ 2（实际 0）、elapsed ≤ 600s（实际 ≤ 292s）。
- **loop_quality 已在真实 run 落地**：三个真实 run 的 `agent_loop_run_summary.json` 均含
  `loop_quality={warn:false, mode:observe_then_warn}`（无 spin，符合 0-repair）。
- **subagent CL-010 契约成立**：`parent_loop_exit_reason=completed`、
  `post_subagent_stop_observation=true`、worker_count=3——child 成功后父循环正确停止。

## 残留（非阻塞）

- `subagent_delegation`（合约探针场景）`studio_runtime_consistent=false`（score 0.75，3/4 子检查）。
  属轻量合约场景不发完整 studio `task_progress` 所致，非真实路径缺陷（3 个真实 slot 均 1.0）。
  audit-only 非阻塞；归入后续 **Studio 前端** 阶段一并核。

## 放量就绪评估

本机 `.asteria` 证据 + 本脱敏摘要构成 Beta 阶段证据基础（参 `S74_POST_S73_BETA_CONVERGENCE_PLAN.md`
§S74-C / 签字要求）。建议作为放量 DecisionPoint 的输入；放量本身（扩大默认权限 / parallel writes
默认 / 新编排）仍需用户在 DecisionPoint 显式裁决，不在本签字范围内。
