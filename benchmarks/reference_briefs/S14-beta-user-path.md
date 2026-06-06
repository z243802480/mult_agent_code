# Slice S14 — Beta 用户路径（Phase 7 精简版）

## observed_pattern

- **OpenCode / Claude Code**：安装 → 打开客户端 → 提 goal → 看进度 → 审查/接受 → 续作。
- **Beta 关键**：非维护者 30 分钟内完成第一个任务，不靠 gate 词汇。

## asteria_mapping

| 交付 | 文件/行为 |
| --- | --- |
| Beta 入门 | `docs/zh/Beta用户入门.md` |
| 一键 Studio | `asteria studio` → server + UI |
| Beta 任务包 | `benchmarks/beta_user_tasks.json`（3 任务） |
| 主路径 Review/Accept | Studio Thread workflow 卡 + Composer `/accept` |
| Wheel 用户路径 gate | `phase7_beta_user_path_gate.json` + pytest |
| 封闭 Beta 签字 | `S14-beta-user-path-signoff-*.md` |

## do_not_copy

- 把 gate/acceptance 栈暴露给普通用户
- 等 Phase 5 蜂群再开 Beta
- Studio 第二套 runtime

## green_checks

- `pytest tests/integration/test_phase7_beta_user_path_gate.py -q`
- `pytest tests/unit/test_studio_command.py -q`
- `node studio/scripts/beta-workflow-smoke.mjs`
- 1 名真实用户完成 beta 任务包中 1 项（[`Beta试跑清单.md`](../../docs/zh/Beta试跑清单.md) + [`S14-beta-user-trial-template.md`](../../docs/zh/reports/S14-beta-user-trial-template.md)）
