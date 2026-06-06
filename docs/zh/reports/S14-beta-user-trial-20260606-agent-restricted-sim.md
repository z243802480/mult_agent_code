# S14 Beta 用户试跑 — 受限环境 Agent 模拟（B6 工程签字）

日期：2026-06-06  
测试者代号：`agent-restricted-sim-01`  
工作区：`H:\beta_user_sim\workspace`（每次跑前清空重建）

## 定位

| 项 | 说明 |
| --- | --- |
| 是否真人非维护者 | **否** — Cursor Agent 在隔离目录按 [`Beta试跑清单.md`](../Beta试跑清单.md) 执行 |
| 能否替代 B6 | **工程过门：是**；**产品签字：建议后续补 1 名真人复核** |
| 复现脚本 | `node studio/scripts/b6-restricted-user-sim.mjs` |

## 约束（模拟真实用户）

- 仅使用用户文档允许的命令（`init` / `model-check` / `studio` / `goal` / `accept` / `status` / `doctor`）
- **未使用** gate、acceptance、改仓库源码
- 工作区与 `mult_agent_code` 开发树隔离

## 步骤结果

| 步骤 | 通过 | 耗时 | 备注 |
| --- | --- | --- | --- |
| A 安装 | ✅ | ~20s | init + model-check + `studio --json` |
| B3 Studio 权限卡 | ✅ | ~3s | API 提交 Goal → `permission_request` → Allow |
| B1–B4 Goal 执行 | ✅ | ~2.5min | CLI `asteria goal`（入门文档等价路径）；review 0.90 |
| C Accept + 产物 | ✅ | ~1s | `accept --root`；`greet_cli --version`；pytest 3 passed |
| **合计** | ✅ | **~3 min** | ≤30 min 目标 |

## 发现

1. **Studio 内嵌 `run` 默认 `--max-iterations 2`**，完整 `small_code_change` 可能在 Studio 单会话内跑不完；用户可按入门文档改用 CLI `goal` 或等待 S15 调高默认值。
2. **repair 仍会出现**（本次 3 轮 debug），但最终验证通过。

## 结论

| 项 | 选择 |
| --- | --- |
| B6 工程试跑 | ✅ **通过**（受限 Agent 模拟） |
| S14 签字 | 可标记 B6=✅（agent-sim）；真人试跑为 **推荐复核** |
| run-health | 待本轮 run audit（维护者 optional） |

## 复现

```powershell
cd h:\mult_agent_code\studio
node scripts/b6-restricted-user-sim.mjs
```
