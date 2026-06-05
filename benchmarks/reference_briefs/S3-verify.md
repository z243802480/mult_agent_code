# Slice S3 — Verify 可见

## observed_pattern（行业已验证）

- **Claude Code**：测试/验证结果以结论句呈现，失败时给出下一步而非 raw pytest 输出。
- **Codex**：验证后才标记 done；验证块与执行块分离。
- **OpenCode**：validation channel 可订阅，主屏消费摘要。

## asteria_mapping（我们怎么做）

- 文件：`task_attempt_runner.py`、`review_command.py`、`user_progress_view.py`、`runtime_progress.py`
- 行为：`transcript_kind=verification`，`display_level=main`，中文结论；`status --json` → `runtime_progress.verification_progress`
- 用户入口：`review` / execute 内验证后 `status --json`

## do_not_copy（禁止照搬）

- 不把 gate-status 字段搬进主屏
- 不用规则引擎替代 validation_event
- 不把 verification 与 tool_result 混为一谈

## 实现记录

- date: 2026-06-05
- notes: task_attempt_runner validation_event + status 投影 `runtime_progress.verify`。
