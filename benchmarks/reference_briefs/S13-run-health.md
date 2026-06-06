# Slice S13 — Run Health（Phase 4 一大步）

## observed_pattern

- 长任务 harness 必须 **有界 recovery**（repair/replan），否则 user_progress 与 task_plan 爆炸。
- MVP 签字不仅要 benchmark score，还要 **run 健康度**（体积、状态、repair 次数）。

## asteria_mapping

- `RunCommand._execute_until_no_ready`：inner recovery cycle cap（policy 驱动）
- `ModelProgressSink`：model delta 持久化上限（Inspector 仍可通过 model_calls 查）
- `run_health_audit.py` + `phase4_run_health_gate.json`
- A3：**S7 clean re-run**（real provider）+ run-health 阈值 + evidence-bundle

## do_not_copy

- 无上限 debug/replan 循环
- 用 workspace-wide benchmark 代替 run-scoped 验收

## green_checks

- `pytest tests/integration/test_phase4_run_health_gate.py -q`
- `pytest tests/unit/test_run_health_audit.py -q`
- real: `studio-benchmark --run-id <id>` ≥ 0.8 + run-health pass
