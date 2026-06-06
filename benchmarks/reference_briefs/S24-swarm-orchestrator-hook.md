# Slice S24 — Swarm Orchestrator Hook

## observed_pattern

- CC subagent：orchestrator 分解 → worker 执行 → 证据汇总；合并仍经 gate。
- Asteria：不 refactor execute；在 core 层提供 **child_plan → spawn → coordinator** 薄 hook。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| `swarm_orchestrator.py` | `plan_swarm_execution(child_plan, policy)` → spawn + coordinator config |
| `subagent_planner` | 已有 `enrich_child_task`；orchestrator 消费 child_plan 输出 |

## do_not_copy

- 不引入新 CLI 命令
- 不修改 DO_NOT_TOUCH execute/run

## green_checks

```bash
pytest tests/unit/test_swarm_orchestrator.py -q
```
