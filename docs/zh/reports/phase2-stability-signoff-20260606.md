# Phase 2 稳态指标签字记录

**状态**：signed — `reviewed_auto` scoped 稳态阈值已通过  
**依赖**：Phase 2 / S7 MVP 已签字；Phase 3 rolling real provider 三门禁已签字  
**契约 CI**：`pytest tests/integration/test_phase2_stability_gate.py -q`（fake scoped runs）

## 阈值（`benchmarks/phase2_stability_gate.json` / 研发总计划 §10）

| 指标 | 阈值 | 实测 |
| --- | --- | --- |
| median model calls（scoped） | ≤ 5 | **2** |
| max repair attempts / run | ≤ 1 | **0** |
| permission_mode | `reviewed_auto` | 是 |

## Checklist

- [x] fake CI：`doc_update` + `single_file_bugfix` scoped runs → stability gate pass
- [x] real provider：`.asteria/verification/phase3-rolling-real-20260606/matrix_summary.json` → 3/3 cases model_calls=2, repair=0
- [x] （可选）S7 workspace `evidence-bundle` → pass（`evidence-2026-06-06T134327-0800.zip`）
- [x] 本报告 + 闸门文档更新

## 结果摘要

```text
fake scoped samples: 2/2 within thresholds (integration test)
real matrix samples: doc_update, single_file_bugfix, context_maintenance — median model_calls=2, max repair=0
S7 signoff run (run-20260606-0001): 曾有 repair 循环技术债；稳态 gate 以 scoped matrix 样本为准，不混 workspace 全量 run。
evidence-bundle: .asteria/s7-signoff-workspace/.asteria/evidence_bundles/evidence-2026-06-06T134327-0800.zip
```

## 命令（复现）

```powershell
pytest tests/integration/test_phase2_stability_gate.py tests/unit/test_phase2_stability_audit.py -q
python -m asteria_runtime evidence-bundle --root .asteria/s7-signoff-workspace --json
```
