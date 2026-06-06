# Slice S17 — Runtime Session Agent

## observed_pattern

- Runtime 默认应像 CC：单 Agent 会话内 tool→verify→retry，而不是 task 图 + replan lineage。
- 完整 Harness 审计（replan、repair_limit、candidate 晋升）属于蜂群/多写者层，不是 Beta 小改默认路径。
- B6 摩擦主要来自 replan/repair_limit 链，而非缺新命令。

## asteria_mapping

| 交付 | 行为 | 状态 |
| --- | --- | --- |
| 执行 profile 契约 | `execution_profile.py` + `run_config.execution_profile` | ✅ |
| 单任务 Plan | `RequirementPlanner` session_agent 合并 | ✅ |
| Run 恢复 | 同任务 requeue，跳过 replan lineage | ✅ |
| Loop profile | `session_agent` in `AgentLoopProfileRegistry` | ✅ |
| status/review replan 软化 | session_agent → `resume` | ✅ |
| RFC | `docs/zh/plans/RUNTIME_SESSION_AGENT_RFC.md` | ✅ |
| B6 复验 | 连续 2 绿（#4+#5） | ✅ |
| doc_update dogfood | `s16_doc_update_dogfood.py --fresh` | ✅ |

## focus

1. **默认 session_agent**：无 parallel_writes / 非 high_risk → 单任务 + 会话内 retry
2. **显式 harness**：`force_harness` / parallel_writes / high_risk → 保留 replan lineage
3. S17 签字 → Phase 4 维护态

## green_checks

```bash
pytest tests/unit/test_execution_profile.py tests/unit/test_planner.py -q
python scripts/s16_doc_update_dogfood.py --repo . --fresh
python scripts/steady_iteration_check.py --root . --skip-b6
pytest tests/unit/test_documentation_contracts.py -q
```

## 退出条件

- ✅ Beta 小改 / doc_update Plan 为单任务（session_agent）
- ✅ B6 连续 2 次绿（见 S16-friction-progress）
- ✅ doc_update dogfood 绿（121s，decide 1 / debug 0）
- ⏳ S17 signoff 报告
