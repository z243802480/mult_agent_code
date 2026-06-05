# Slice S4 — Final 可见

## observed_pattern（行业已验证）

- **Claude Code**：Result + Next step 固定结构；compact/handoff 不替代 final 块。
- **Codex**：任务结束有明确 done/continue 语义。
- **OpenCode**：conclusion channel 驱动会话收尾。

## asteria_mapping（我们怎么做）

- 文件：`run_command.py`、`review_command.py`、`accept_command.py`、`user_progress_logger.py`、`user_progress_view.py`
- 行为：`transcript_kind=final|stop`，Result/Next step 固定字段；`required_user_progress_kinds` 齐
- 用户入口：`accept` / run 完成后 `status --json` → `runtime_progress.final`

## do_not_copy（禁止照搬）

- Studio 规则回复冒充 final
- 不把 final_report JSON 路径当主屏文案
- 不跳过 schema 验证

## 实现记录

- date: 2026-06-05
- notes: final_report_event display_level=main；status 投影 `runtime_progress.final`；required_kinds 契约测试。
