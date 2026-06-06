# S38 North Star Goal Queue — Signoff 2026-06-06

## 目标

闭合 Phase 6 **North Star 目标队列**：bounded slice 序列、accept 后 Continue 提示（非 silent auto goal）。

## 交付

| 项 | 证据 |
| --- | --- |
| `goal_queue.py` | `.asteria/goal_queue.json` · seed / mark_done / release |
| accept 集成 | Continue 提示 + `shlex.quote` 安全命令 |
| run 关联 | `link_run_to_goal` · 优先 `linked_run_ids` 匹配 |
| 闸门 | `phase6d_goal_queue_gate.json` |

## 设计对齐

- 对标 Claude Code **permission gate + 用户显式继续**，队列只提示不 silent execute。
- 失败 slice 通过 `release_in_progress` 避免队列卡死。

## green_checks

```powershell
pytest tests/integration/test_phase6d_goal_queue_gate.py -q
pytest tests/unit/test_goal_queue.py -q
```

## 纪律确认

- North Star 不 silent auto execute
- `parallel_writes` 默认 false
