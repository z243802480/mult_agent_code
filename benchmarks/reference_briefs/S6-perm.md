# Slice S6 — 权限卡

## observed_pattern（行业已验证）

- **Codex**：sandbox 审批卡；Allow/Deny 明确。
- **Claude Code**：权限请求打断主流程，用户决策后继续。
- **OpenCode**：permission mode 与 UI 一致。

## asteria_mapping（我们怎么做）

- 文件：`PermissionCard.tsx`、`server.mjs`、`user_progress_logger.py`
- 行为：`transcript_kind=permission_request`，主屏 PermissionCard；`interactive-main-path.spec.mjs` 绿
- 用户入口：Studio Accept runtime action → permission card

## do_not_copy（禁止照搬）

- 无审计的自动 Allow All
- 把 capability JSON 暴露到主屏

## 实现记录

- date: 2026-06-05
- notes: PermissionCard 已有；Thread 透传 job_id；interactive-main-path 绿。
