# Slice S30 — Execute Policy Passthrough

## observed_pattern

- Orchestrator 计划已在 agent loop 写入证据；execute 主路径 subagent 分解仍缺 **policy 上下文**。
- DO_NOT_TOUCH 允许：execute 仅 append policy 透传，不 refactor。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| `execute_command.py` | `persist_subagent_child_plan_for_execution(..., policy=context.policy)` |
| `subagent_planner.py` | `build/persist` 透传 policy → `enrich_child_task` |
| 集成测试 | execute subagent gray path 产生 `swarm_execution_plans.jsonl` |

## do_not_copy

- 不打开 CLI 默认 parallel_writes
- 不 refactor execute/run 控制流

## green_checks

```bash
pytest tests/integration/test_execute_swarm_policy_passthrough.py -q
pytest tests/integration/test_execute_command.py::test_execute_command_records_subagent_dispatch_gray_path -q
```
