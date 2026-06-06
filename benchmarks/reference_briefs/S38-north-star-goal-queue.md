# Slice S38 — North Star Goal Queue

## observed_pattern

- 长期目标需要 **bounded goal queue**：每次一条 slice goal，accept 后提示下一条，用户显式 Continue。
- 竞品 planner-worker 分离：queue 由 planner 填充，worker 只执行当前 slice。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `.asteria/goal_queue.json` | bounded items：pending / done |
| `GoalQueueStore` | seed from north_star milestones · mark_done · continue_hint |
| accept 收尾 | next_actions + user_progress「North Star 下一条 slice」 |
| `phase6d_goal_queue_gate.json` | Phase 6 wave 4 闸门 |

## do_not_copy

- 不 silent auto `goal` / `run`
- 不无限队列自动执行

## green_checks

```bash
pytest tests/integration/test_phase6d_goal_queue_gate.py -q
pytest tests/unit/test_goal_queue.py -q
```

## discipline

- Continue 须用户确认（recommended_next_command 仅为建议）
