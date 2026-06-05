# Slice S8 — 续作

## observed_pattern（行业已验证）

- **Claude Code**：同 session 续作带上文；handoff/compact 不丢目标。
- **OpenCode**：session resume 恢复 workspace 与 run 上下文。

## asteria_mapping（我们怎么做）

- 文件：`resume_command.py`、`sessions_command.py`、`active_goal_memory.py`
- 行为：同 session 第二条 goal 带上文；`status --json` 显示 active_goal_memory
- 用户入口：`goal` → 中断 → 第二条 `goal` / `resume`

## do_not_copy（禁止照搬）

- 无 run_id 的全局聊天续作
- 把 North Star 混进 S8

## 实现记录

- date: 2026-06-05
- notes: `tests/integration/test_session_continuation.py` 同 workspace 续作 plan + status 投影。
