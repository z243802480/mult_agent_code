# Slice S32 — Gray DecisionPoint + Rollback Drill

## observed_pattern

- Phase 5 生产 gray 须走 **DecisionPoint + rollback 演练**，不能默认打开 `parallel_writes` 或生产 flag。
- 与 `swarm_flag_rollout` / `validation-run` 栈对齐。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `swarm_gray_decision.py` | DecisionPoint 模板 + isolated probe + rollback 证据 |
| `phase5e_gray_decision_gate.json` | 闭合 phase5d → gray 闸门 |
| `swarm_gray_rollout_records.jsonl` | 维护者 drill 审计 |

## green_checks

```bash
pytest tests/unit/test_swarm_gray_decision.py -q
pytest tests/integration/test_phase5e_gray_decision_gate.py -q
```

## discipline

- Beta 默认 session_agent 不变
- CLI `parallel_writes` 默认 off
- rollback 后 flag 必须回到 disabled
