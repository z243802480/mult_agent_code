# Slice S17 — Runtime Session Agent

## observed_pattern

- Runtime 默认应像 CC：单 Agent 会话内 tool→verify→retry，而不是 task 图 + replan lineage。
- 完整 Harness 审计（replan、repair_limit、candidate 晋升）属于蜂群/多写者层，不是 Beta 小改默认路径。
- B6 摩擦主要来自 replan/repair_limit 链，而非缺新命令。

## asteria_mapping

| 交付 | 行为 | 状态 |
| --- | --- | --- |
| 执行 profile 契约 | `execution_profile.py` + `run_config.execution_profile` | ⏳ |
| 单任务 Plan | `RequirementPlanner` session_agent 合并 | ⏳ |
| Run 恢复 | 同任务 requeue，跳过 replan lineage | ⏳ |
| Loop profile | `session_agent` in `AgentLoopProfileRegistry` | ⏳ |
| RFC | `docs/zh/plans/RUNTIME_SESSION_AGENT_RFC.md` | ⏳ |
| B6 复验 | `b6-restricted-user-sim.mjs` 连续 2 绿 | ⏳ |

## focus

1. **默认 session_agent**：无 parallel_writes / 非 high_risk → 单任务 + 会话内 retry
2. **显式 harness**：`force_harness` / parallel_writes / high_risk → 保留 replan lineage
3. B6 摩擦指标收敛后 S16/S17 签字

## green_checks

```bash
pytest tests/unit/test_execution_profile.py tests/unit/test_planner.py -q
pytest tests/integration/test_run_command.py::test_run_command_replans_when_debug_cannot_repair -q
python scripts/steady_iteration_check.py --root . --skip-b6
pytest tests/unit/test_documentation_contracts.py -q
```

## 退出条件

- Beta 三类任务（small_code_change / doc_update / single_file_bugfix）Plan 均为单任务
- session_agent run 不产生 replan lineage（除非 `force_harness`）
- B6 连续 2 次绿或等价 maintainer 记录
