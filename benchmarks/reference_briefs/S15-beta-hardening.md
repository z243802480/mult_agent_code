# Slice S15 — Beta 内测硬化（Phase 7 收口）

## observed_pattern

- Beta 过门后首波反馈通常是 **安装摩擦 + Studio 全路径未完成**，不是缺新架构。
- OpenCode：Studio `run` 应与 CLI `goal` 同等完成 small tasks。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| Studio 全路径 | `server.mjs` run/resume 迭代上限与 CLI 对齐；`b6-restricted-user-sim` 全程 Studio goal |
| Wheel 路径 | 验证试运行手册 §3.1 自动化或 runbook 签字 |
| Beta 任务 2 | `doc_update` 走 Studio 或 CLI 一次 |
| 内测就绪 | 更新 signoff + `phase7_beta_user_path_gate.json` closed |

## do_not_copy

- Phase 5 蜂群
- 新 maintainer 主屏

## green_checks

- `node studio/scripts/b6-restricted-user-sim.mjs`（Studio 全路径，非 CLI goal 回退）
- wheel 复验 runbook 或 integration 契约
- `pytest tests/integration/test_phase7_beta_user_path_gate.py -q`
