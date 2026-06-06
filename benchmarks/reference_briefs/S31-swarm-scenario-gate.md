# Slice S31 — Swarm Scenario Gate (Global)

## observed_pattern

- Phase 5 有两条 harness 路径（execute 并行 vs subagent 计划），需 **统一审计** 并挂到 **validation matrix + 一条脉搏**。
- 禁止再增第四套 maintainer 脚本孤岛。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `swarm_scenario_audit.py` | run_dir 路径识别 + 证据审计 |
| `phase5d_swarm_scenario_gate.json` | 闭合 phase5→5c 闸门链 |
| `swarm_holistic_check.py` | steady + integration + rollout + phase5d |
| `runtime_validation_matrix` | `swarm_disjoint_evidence` case |

## green_checks

```bash
python scripts/swarm_holistic_check.py --root . --skip-studio
pytest tests/integration/test_phase5d_swarm_scenario_gate.py -q
```

## real provider（optional）

`real_model_gate` 通过后，validation-run 记录 disjoint 场景；非 CI 阻塞项。
