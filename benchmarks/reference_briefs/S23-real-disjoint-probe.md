# Slice S23 — Real Disjoint Maintainer Probe

## observed_pattern

- 真实 parallel disjoint write 先在 **隔离 run_dir** 证明：spawn parallel + candidate export + merge dry-run。
- 与 S21 fake_serial 对照：`scheduling_mode=parallel`、`fake_path=false`。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| `run_maintainer_real_disjoint_probe` | policy 临时启用 flag + maintainer 环境 capability |
| `swarm_gate_audit` 扩展 | 可选校验 parallel scheduling |

## green_checks

```bash
pytest tests/integration/test_phase5b_swarm_rollout_gate.py -q
python scripts/swarm_flag_rollout_check.py --root .
```
