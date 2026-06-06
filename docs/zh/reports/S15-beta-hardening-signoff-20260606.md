# S15 Beta 内测硬化 — 签字

日期：2026-06-06  
前置：Phase 7 关闭（[`phase7-beta-close-signoff-20260606.md`](./phase7-beta-close-signoff-20260606.md)）

## 交付

| # | 项 | 状态 | 证据 |
| --- | --- | --- | --- |
| C1 | Studio 全路径 `small_code_change` | ✅ | `node studio/scripts/b6-restricted-user-sim.mjs`（161s，3 pytest passed） |
| C2 | Wheel 安装复验 | ✅ | `python scripts/s15_wheel_install_smoke.py`（venv + wheel + init/doctor） |
| C3 | 小范围内测邀请 | ✅ | [`Beta内测邀请.md`](../Beta内测邀请.md) |

## C1 说明

- `b6-restricted-user-sim.mjs` 全程 Studio API（goal / permission / runtime-actions / accept）。
- wait 循环自动处理 decide / resume / debug；`scope_expansion` 默认 `review_contract`。

## C2 说明

- 轻量 §3.1：`scripts/s15_wheel_install_smoke.py`（全新 venv + wheel + version/init/doctor）。
- 完整 real-model gate 仍属 maintainer 发布流程，不阻塞 Beta 内测。

## C3 说明

- 维护者用 [`Beta内测邀请.md`](../Beta内测邀请.md) 邀请 3–5 人。
- 试跑记录：[`S14-beta-user-trial-template.md`](./S14-beta-user-trial-template.md)。

## 签字

| 角色 | 日期 | 结论 |
| --- | --- | --- |
| 工程 | 2026-06-06 | ✅ S15 green — 可发放内测材料 |
| 产品 | 2026-06-06 | ✅ Agent 模拟 + 材料就绪 |

**不纳入**：Phase 5 蜂群、North Star 自动 execute。

**下一步**：维护者按邀请文档发放内测；收集真人反馈（optional）；ACTIVE_SLICE 可转 Phase 7 维护或 Phase 4 稳态。
