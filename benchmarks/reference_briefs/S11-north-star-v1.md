# Slice S11 — North Star v1（Phase 4 入口）

## observed_pattern（行业已验证）

- **OpenCode utw**：workspace 级远端目标，跨 session/run 主动靠近，不阻塞当前 run。
- **Claude Code / Codex**：长目标与当前 task 分离；用户面只见摘要与 next step。

## asteria_mapping（我们怎么做）

- 前置：`phase2_stability_window.json` → `ready_for_implementation`
- 文件：`.asteria/north_star.json`（schema `schemas/north_star.schema.json`）
- 行为：只读投影进 `status --json` 的 `long_horizon`；**不**做 gate 主屏、不阻塞 goal/plan/ask
- milestone：≥3 run 可链接 `linked_run_ids`；由 accept/review 或 handoff 更新

## do_not_copy（禁止照搬）

- 无限制全局聊天续作
- North Star 驱动自动 execute 不经 permission
- 蜂群 parallel write（仍 defer SWARM RFC）

## green_checks（窗口打开后）

- `pytest tests/unit/test_north_star_storage.py -q`
- `pytest tests/integration/test_status_long_horizon.py -q`
- `pytest tests/unit/test_accept_command.py -q -k north_star`
- doc contracts 含 `north_star.schema.json`
