# Slice S22 — Swarm Flag Rollout

## observed_pattern

- OpenCode / Codex：feature flag + capability gate + rollback 演练先于生产放量。
- S21 仅 fake_serial；真实 parallel 需 **DecisionPoint 级** 就绪链。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| `swarm_flag_rollout.py` | 评估 `real_disjoint_write_workers` 就绪、规划 transition、生成 rollback policy |
| `phase5b_swarm_rollout_gate.json` | wave2 闸门契约 |
| `swarm_flag_rollout_check.py` | maintainer 一键复验 |

## do_not_copy

- 不抄外部产品 flag 控制台 UI
- 不默认打开 CLI `parallel_writes`

## green_checks

```bash
pytest tests/unit/test_swarm_flag_rollout.py -q
python scripts/swarm_flag_rollout_check.py --root . --skip-probe
```
