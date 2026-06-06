# Slice S39 — Supervised Goal Loop

## observed_pattern

- 监督式长期迭代：`--toward-north-star --max-slices N` 在 budget 内连续 bounded slice。
- 必须有 kill switch（`.asteria/STOP`）与 hard-stop budget，每 slice 仍走 goal→execute→verify→review→accept。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| CLI `--toward-north-star` | run/goal 入口 bounded 续跑 |
| kill file + budget | `.asteria/STOP` · cost policy hard_stop |
| slice 链 | 复用 S37 completion + S38 queue |
| `phase6e_supervised_goal_loop_gate.json` | Phase 6 wave 5 闸门 |

## do_not_copy

- 无限制 autonomous agent chatroom
- 无策略 destructive shell

## green_checks（规划）

```bash
pytest tests/integration/test_phase6e_supervised_goal_loop_gate.py -q
```

## discipline

- 每 slice 结束须 accept 或显式用户决策点
- defer 至 S37/S38 闭合后实现

---

## 实现记录（2026-06-06）

| 交付 | 路径 |
| --- | --- |
| 监督循环核心 | `supervised_goal_loop.py` |
| CLI 命令 | `SupervisedGoalLoopCommand` · `goal --toward-north-star --max-slices N` |
| kill switch | `.asteria/STOP` |
| budget 硬停 | `budget_hard_stop_reached` |
| 闸门 | `phase6e_supervised_goal_loop_gate.json` |
