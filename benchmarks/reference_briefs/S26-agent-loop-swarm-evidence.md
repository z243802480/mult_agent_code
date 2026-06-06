# Slice S26 — Agent Loop Swarm Evidence

## observed_pattern

- Harness 计划必须与 **run_dir 证据** 同链，不能只在 maintainer 脚本里存在。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| `persist_swarm_execution_plan` | 写入 `swarm_execution_plans.jsonl` + events |
| `persist_subagent_child_plan_for_execution` | append-only 挂接 |

## green_checks

```bash
pytest tests/integration/test_swarm_agent_loop_integration.py -q
```
