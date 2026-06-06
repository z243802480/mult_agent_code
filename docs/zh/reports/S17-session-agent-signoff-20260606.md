# S17 Runtime Session Agent — Signoff 2026-06-06

## 交付摘要

Runtime 默认路径改为 **session_agent**（CC 级单任务会话）；Harness（replan lineage / repair_limit）仅在高风险、parallel_writes 或 `force_harness` 时启用。

## 证据

| 检查 | 结果 |
| --- | --- |
| `pytest tests/unit/test_execution_profile.py` | ✅ |
| B6 连续 2 绿 | ✅ #4 164s、#5 244s；friction 0/1/0 |
| `s16_doc_update_dogfood.py --fresh` | ✅ 121s；ACCEPTED；decide 1 / debug 0 |
| `steady_iteration_check.py --skip-b6` | ✅ |
| doc contracts | ✅ |

## 关键 commit

- `5323ec1` — S17 session_agent 核心 + B6/dogfood 脚本
- （待）status replan 软化 + 文档同步

## 未做（defer）

- Phase 5 蜂群 harness 叠加
- doc_update `context_request` 低风险自动放行
