# Phase 3 Rolling 签字记录

**状态**：signed — real provider 三门禁 scoped cases 连续通过  
**依赖**：Phase 2 / S7 已签字（`S7-mvp-signoff-20260606.md`）  
**契约 CI**：`pytest tests/integration/test_phase3_rolling_gate.py -q`（fake，与本次 real 签字互补）

## 环境

| 项 | 值 |
| --- | --- |
| provider | OS 用户环境变量：`minimax`（medium）、`glm`（strong） |
| 证据目录 | `.asteria/verification/phase3-rolling-real-20260606/` |
| 日期 | 2026-06-06 |
| 总耗时 | ~101s |

## Checklist（`benchmarks/phase3_rolling_gate.json`）

- [x] `model-check --tier medium` → `call_ok: true`
- [x] `model-check --tier strong` → `call_ok: true`
- [x] `doc_update` real smoke → ok
- [x] `single_file_bugfix` real smoke → ok
- [x] `context_maintenance` real smoke → ok
- [x] `matrix_summary.json` → `ok: true`, `passed: 3/3`

## 结果摘要

```text
provider_mode: real
doc_update: completed, review pass, model_calls=2, repair_attempts=0
single_file_bugfix: completed, review pass, model_calls=2, repair_attempts=0
context_maintenance: completed, review pass, model_calls=2, repair_attempts=0
strong_model_calls: 0（三门禁均为 medium fast path）
summary: .asteria/verification/phase3-rolling-real-20260606/matrix_summary.json
```

## 命令（复现）

```powershell
# 使用 OS 用户级 AGENT_MODEL_*，勿用过期 workspace provider 脚本
python scripts/real_model_smoke.py --matrix p0 `
  --matrix-case doc_update --matrix-case single_file_bugfix --matrix-case context_maintenance `
  --matrix-output-dir .asteria/verification/phase3-rolling-real-YYYYMMDD `
  --summary-json .asteria/verification/phase3-rolling-real-YYYYMMDD/matrix_summary.json `
  --no-research --max-iterations 5 --command-timeout-seconds 1200
```
