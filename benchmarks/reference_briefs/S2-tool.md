# Slice S2 — Tool 可见

## observed_pattern（行业已验证）

- **Claude Code**：工具调用在主会话以可读块展示（命令/结果摘要），raw stdout 进 Inspector。
- **Codex**：sandbox 工具前后有用户可见状态，不暴露内部 stage 名。
- **OpenCode**：tool channel 与主 Thread 分离，主屏只显示摘要。

## asteria_mapping（我们怎么做）

- 文件：`tool_execution_gateway.py`、`user_progress_view.py`、`runtime_progress.py`、`sessions_command.py`
- 行为：`transcript_kind=tool_use|tool_result`，`display_level=main`，中文摘要；`status --json` → `runtime_progress.tool`
- 用户入口：`goal` / `execute` 后 `status --json`

## do_not_copy（禁止照搬）

- 不把 stdout 全文搬进主屏
- 不新建第二套 tool timeline schema
- 不重构 `execute_command.py` 核心逻辑

## 实现记录

- date: 2026-06-05
- notes: gateway main 级 tool_use/tool_result；status 投影 `runtime_progress.tool`。
