# S64 Wave 2 隔离 Probe 签字记录

**日期**：2026-06-07  
**状态**：signed — maintainer 隔离 `parallel_writes` probe 通过；Beta 默认仍 off  
**前置**：[`S62-S63-orchestration-real-model-signoff-20260607.md`](./S62-S63-orchestration-real-model-signoff-20260607.md) · [`S64-parallel-rollout-research-20260607.md`](./S64-parallel-rollout-research-20260607.md)

## 摘要

| 步骤 | 结果 |
| --- | --- |
| DecisionPoint resolve → `wave2_maintainer_probe` | ✅ |
| 隔离 workspace S34 `dual_disjoint_files` | ✅ |
| S32 gray rollback drill | ✅ |
| CLI `parallel_writes` 默认 | **false**（未改） |
| Studio `spawn_parallel_workers` catalog | **unavailable**（未改） |

## 命令

```powershell
python scripts/orchestration_wave2_probe.py --root .
python scripts/orchestration_parallel_gray_pulse.py --root . --gray-drill-ok
pytest tests/unit/test_orchestration_parallel_gray.py tests/integration/test_phase5f_production_gray_gate.py -q
```

## 证据

| 类型 | 路径 |
| --- | --- |
| Wave 2 band | `.asteria/verification/orchestration_wave2_probe.json` |
| DecisionPoint | `.asteria/decisions/decision-orchestration-parallel-0001.json`（`resolved` · `wave2_maintainer_probe`） |
| S62 route eval | `.asteria/verification/orchestration_route_real_20260607.json` |
| S63 spawn eval | `.asteria/verification/orchestration_spawn_real_20260607.json` |

## 实现

| 项 | 位置 |
| --- | --- |
| resolve + band 封装 | `src/asteria_runtime/core/orchestration_parallel_gray.py` |
| maintainer 脚本 | `scripts/orchestration_wave2_probe.py` |
| 单元测试 | `tests/unit/test_orchestration_parallel_gray.py::test_wave2_band_resolves_decision_and_runs_gray` |

## 结论

Wave 2 **maintainer 隔离 probe 已闭合**。下一档为 **Wave 3**：评估 `spawn_parallel_workers` catalog gray（仍须 strong route 选中 + 新 DecisionPoint；**不**自动开启 CLI `parallel_writes`）。
