# ADR-0014: 单 Session 恢复与显式 Review

日期：2026-06-09  
状态：Accepted

## 背景

Asteria 曾同时让以下层负责执行失败后的下一步：

- Execute Agent Loop 根据 observation 选择 repair / replan / ask / stop；
- RunCommand 在 blocked 后自动调用 DebugCommand，并在失败后自动 Replan；
- ReviewCommand 把模型 review 的 follow-up 直接变成任务或 DecisionPoint；
- RunCommand 再用 Goal policy 根据 review 结果决定继续修复、停止、接受或自动接受。

同一个失败因此会被多套控制器重复解释和重入。模型的原始 observation 被后置规则覆盖，
调试、评审和目标策略也逐渐成为第二、第三套 orchestrator。

公开机制显示，Claude Agent SDK 的稳定主循环是
`model -> tool -> result -> model`，工具拒绝和失败结果回到同一 session；
Codex 的 review 用于查证变更、给出反馈和决定保留内容，反馈继续回到原线程。
二者都把权限、sandbox、promotion 等不可逆风险放在动作边界，而不是让 review 成为自动编排器。

参考：

- https://platform.claude.com/docs/en/agent-sdk/agent-loop
- https://platform.claude.com/docs/en/agent-sdk/sessions
- https://platform.claude.com/docs/en/agent-sdk/permissions
- https://developers.openai.com/codex/app/review
- https://developers.openai.com/codex/agent-approvals-security

## 决策

默认产品主路径只有一个恢复控制器：Execute Agent Loop。

| 责任 | 唯一位置 |
| --- | --- |
| tool result 后的 repair / replan / ask / stop | 当前 session 的 Agent Loop |
| blocked / paused 后继续 | 保留 session evidence，显式 `resume` |
| 质量查证与反馈 | 显式 `review` |
| 接受、promotion 与不可逆动作 | 显式 `accept` 和对应动作边界 |
| 手工诊断兼容入口 | 显式 `debug`，不得由默认 Run 自动调用 |

因此：

- `RunCommand` 不自动调用 `ReviewCommand`、`DebugCommand` 或 `ReplanCommand`；
- `RunCommand` 不根据 review verdict 做 Goal-policy 自动接受或自动修复；
- `ReviewCommand` 只写 verdict、证据和反馈，不创建任务、DecisionPoint 或 AgentLoopDecision；
- review 未通过时，反馈回到当前 session，推荐继续 `resume`；
- 显式 Review、Accept、Debug 命令暂时保留兼容；后续是否进一步合并必须经过真实 Beta 证据裁决。

## 保留的不变量

- 权限、sandbox、candidate、merge、promotion、预算 hard-stop 仍在动作边界强制执行；
- review 和 deterministic verification 仍可独立查证结果；
- DecisionPoint 仍用于真实的权限、预算和重大产品选择，不由 review follow-up 自动生成；
- blocked session 必须保留 durable evidence，并可恢复。

## 禁止回归

- 禁止在默认 `RunCommand` 中重新导入或调用 `ReviewCommand` / `DebugCommand`；
- 禁止让 `ReviewCommand` 创建 follow-up task、DecisionPoint 或 AgentLoopDecision；
- 禁止用 Goal policy 覆盖模型已经基于 observation 作出的恢复决定；
- 若真实 Beta 证明单 session 恢复不足，应先修复 Agent Loop 契约，不得新增后置 orchestrator。

