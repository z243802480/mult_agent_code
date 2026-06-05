# Slice S5 — Studio 对齐

## observed_pattern（行业已验证）

- **OpenCode**：client/server 共享 runtime 事件；Thread 与 CLI status 同一叙事。
- **Claude Code**：主会话 timeline 与终端状态一致，Inspector 看 raw。

## asteria_mapping（我们怎么做）

- 文件：`studio/server.mjs`、`Thread.tsx`、`narrative.ts`
- 行为：Thread 消费 `display_level=main` + `transcript_kind`；`/api/runs/:id` 的 `runtime_progress.plan` 与 status 同形
- 用户入口：Studio run detail + `run-detail-smoke.mjs`

## do_not_copy（禁止照搬）

- 像素级复刻竞品 UI
- 从 stdout 推断进度
- job 结束时合成假 final

## 实现记录

- date: 2026-06-05
- notes: server enrichRuntimeProgress + Thread/narrative transcript_kind；run-detail-smoke 绿。
