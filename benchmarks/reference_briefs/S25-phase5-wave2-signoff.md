# Slice S25 — Phase 5 Wave2 Signoff

## observed_pattern

- Phase 5 entry（S18–S21）与 wave2（S22–S24）分闸门签字，避免混签。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| `phase5b_swarm_rollout_gate.json` | 汇总 S22–S24 契约 |
| `docs/zh/reports/phase5-wave2-signoff-*.md` | 签字报告 |
| RFC §6 里程碑表 | 更新 S22–S25 状态 |

## green_checks

```bash
python scripts/swarm_flag_rollout_check.py --root .
pytest tests/integration/test_phase5b_swarm_rollout_gate.py -q
pytest tests/unit/test_documentation_contracts.py -q
```
