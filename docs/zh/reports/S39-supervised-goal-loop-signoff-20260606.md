# S39 Supervised Goal Loop — Signoff 2026-06-06

## 目标

闭合 Phase 6 **监督式多 slice 循环**：`goal --toward-north-star --max-slices N`、kill file、预算与 per-slice accept。

## 交付

| 项 | 证据 |
| --- | --- |
| `supervised_goal_loop.py` | band runner · kill file `.asteria/STOP` |
| CLI | `SupervisedGoalLoopCommand` · `--toward-north-star` |
| progress | 按 slice `run_id` 分写 user_progress |
| 闸门 | `phase6e_supervised_goal_loop_gate.json` |

## 设计对齐

- 对标 ReAct while-loop + **deterministic infra**（accept/review/verify 分离），非第二 runtime。
- kill file 对应 Claude 侧 terminal / interrupt 控制面。

## green_checks

```powershell
pytest tests/integration/test_phase6e_supervised_goal_loop_gate.py -q
pytest tests/unit/test_supervised_goal_loop.py -q
```

## 纪律确认

- 每 slice 仍需 accept，不 bypass 监督
- 循环失败时 queue `release_in_progress`
