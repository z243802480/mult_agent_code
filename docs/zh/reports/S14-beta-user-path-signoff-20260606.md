# S14 Beta 用户路径 — 签字记录

日期：2026-06-06  
Slice：S14（Phase 7 Beta 精简版）  
Brief：[`benchmarks/reference_briefs/S14-beta-user-path.md`](../../benchmarks/reference_briefs/S14-beta-user-path.md)

## 交付摘要

| # | 交付 | 状态 |
| --- | --- | --- |
| B1 | [`docs/zh/Beta用户入门.md`](../Beta用户入门.md) | ✅ |
| B2 | `asteria studio` CLI | ✅ |
| B3 | `phase7_beta_user_path_gate.json` + pytest | ✅ |
| B4 | Studio workflow 卡 + `/accept` | ✅ |
| B5 | `benchmarks/beta_user_tasks.json` | ✅ |
| B6 | 封闭 Beta 用户验证 | ⏳ 进行中 | 见下方 B6 流程 |

## B6 封闭试跑流程

1. **发给测试者**：[`Beta试跑清单.md`](../Beta试跑清单.md) + [`Beta用户入门.md`](../Beta用户入门.md) + clone 地址 + Key 配置说明  
2. **维护者不做**：逐步带敲命令、代点 Review/Accept  
3. **试跑后**：复制 [`S14-beta-user-trial-template.md`](./S14-beta-user-trial-template.md) 填写归档  
4. **通过标准**：非维护者 30 分钟内完成 `small_code_change` 的 Goal → Review → Accept  
5. **签字**：本文件 B6=✅，`AGENTS.md` ACTIVE_SLICE 改为 S14（signed）

**维护者 smoke（非 B6）**：[`S14-beta-user-trial-20260606-maintainer-smoke.md`](./S14-beta-user-trial-20260606-maintainer-smoke.md) — `H:\test_agent` 工程路径已验证。

## Green checks（维护者）

```powershell
pytest tests/integration/test_phase7_beta_user_path_gate.py tests/unit/test_studio_command.py -q
node studio/scripts/beta-workflow-smoke.mjs
python -m asteria_runtime studio --root . --json
```

## 备注

- Studio 仍随仓库 checkout 提供；wheel 仅打包 runtime。
- 蜂群 parallel **未**纳入本 slice。
- 非维护者完成 beta 任务包中 1 项后，将 B6 标为 ✅ 并更新 AGENTS `ACTIVE_SLICE` 为 signed。
