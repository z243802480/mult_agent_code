# Slice S1 — Plan 可见

## observed_pattern（行业已验证）

- **OpenCode**：agent/mode 区分 plan（只读）与 build（可写）；server/API 驱动同一 runtime。
- **Claude Code**：计划摘要在主会话可见，不暴露内部 stage 名。
- **Codex**：AGENTS.md 层级 + 明确任务边界后再执行。

## asteria_mapping（我们怎么做）

- 文件：`user_progress_logger.py`、`plan_command.py`、`run_command.py`、`status_command.py`
- 行为：`transcript_kind=plan`，`ui_intent=work_progress`，`display_level=main`；status 中文 plan 摘要
- 用户入口：`asteria goal` / `asteria plan`（见用户交互模型）

## do_not_copy（禁止照搬）

- 不新建第三套 planner UI
- 不把 gate/route 字段搬进主屏
- 不造新的 plan schema 替代 task_plan.json

## 实现记录

- date: 2026-06-05
- notes: `plan_command` 写入中文 `transcript_kind=plan` 主会话事件；`sessions_command`/`runtime_progress.plan` 与 `status --json` 暴露 plan 摘要；测试 `tests/unit/test_plan_progress_contract.py`。
