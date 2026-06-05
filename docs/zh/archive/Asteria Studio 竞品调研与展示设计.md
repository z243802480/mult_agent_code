> **非当前依据（archive）**：机制摘要已并入 [研发总计划.md](../研发总计划.md) §5。下文 dashboard/mission control 方案 **不再执行**；Studio 以 [Studio 会话与上下文设计准则.md](../Studio%20会话与上下文设计准则.md) 为准。

# Asteria Studio 竞品调研与展示设计

本文记录 2026-05-20 对 opencode、Claude Code 和 Codex 的产品调研结论，并把结论转化为 Asteria Studio 的展示设计方案。

## 1. 调研来源

- opencode 官方文档与仓库：TUI、agent/mode、permissions、provider、server/API、share/session。
- Claude Code 官方文档：overview、settings/permissions、hooks、MCP、多端体验、IDE/desktop/web。
- Codex 官方开发者资料：长任务、代码审查、PR/Slack 等工作流、skills、可验证前端/工程任务。

这些产品的共同趋势不是把 agent 做成更长的聊天窗口，而是把真实开发工作压进受控工作台：

- 从自然语言目标进入，但尽快落到计划、差异、命令、证据和下一步动作。
- 明确区分 plan/read-only 与 build/run/write 模式。
- 权限不只是弹窗，而是贯穿工具、文件、shell、MCP/provider 和团队策略。
- 多端 UI 共享同一运行时状态：终端、IDE、desktop/web 只是不同 surface。
- 需要能解释“为什么现在不能继续”：route、budget、permission、validation、promotion、release gate。

## 2. 对 Asteria 的启发

### 2.1 opencode

opencode 的关键价值在于 terminal-first、provider-agnostic 和 client/server。它把 TUI 当作主界面，但保留 server/API，让其他客户端可以驱动同一运行时；同时用 agent/mode 区分 plan 和 build，用 permission 配置控制 tool/MCP 行为。

对 Studio 的落点：

- Studio 不应重写 runtime，只作为 Asteria Runtime OS 的 localhost client。
- 左侧应是 session/workspace，而不是营销导航。
- 主视图应同时展示 agent mode、permission mode、provider route 和最近 evidence。
- 所有动作都要能降级为命令预览，避免 UI 绕过 CLI/policy。

### 2.2 Claude Code

Claude Code 的关键价值在于多 surface 一致性、权限/设置分层、hooks/MCP 扩展、diff/review 和 plan review。它的 desktop/web/IDE 不是替代 CLI，而是补足可视化审阅、并行 session 和远程/长期任务。

对 Studio 的落点：

- Studio 第一屏应该让用户看清当前任务是否处于 understand/plan/execute/review/result。
- Inspector 应展示选中事件的命令、telemetry、evidence refs、artifact refs 和可预览文件。
- 设置与安全边界必须显式化：workspace、runtime root、shell、permission、streaming。
- 后续可以加 hooks/plugins/MCP 观测，但 P0 只做只读展示和受控动作。

### 2.3 Codex

Codex 的关键价值在于把任务做成可验证工作流：review PR、执行长任务、从 Slack/外部上下文启动任务、用 skills 固化重复流程、对前端做视觉验证。它强调任务结果、验证和集成，而不是单纯消息流。

对 Studio 的落点：

- 首页要显示 gate/validation/core validation，而不仅是聊天 transcript。
- 每条运行事件应保留 phase、status、route、artifact/evidence，方便复盘。
- 对文档、小工具、测试修复、受控重构等验证任务，要能看成本、repair、replan、promotion 趋势。
- 未来的 dogfooding 证据包导出应成为 Studio 一级动作。

## 3. 展示设计原则

Studio 当前阶段采用“任务驾驶舱 + 证据 Inspector”的布局：

- 左栏：workspace/session 列表、当前安全模式、入口动作。
- 中栏：validation strip、任务时间线、composer。用户先看到能不能跑、卡在哪，再进入对话。
- 右栏：selected event inspector、runtime health、model routes、recent files。

视觉风格：

- 低噪声、工程化、信息密度高；避免营销 hero 和装饰性背景。
- 颜色表达状态：green=ready/pass，amber=conditional/running，red=blocked/failed，blue=route/model。
- 卡片只用于独立重复项或 inspector 工具；页面结构用 full-height panels。
- 控件使用图标、分段选择、select、按钮和状态 pill，避免大段解释文字。

## 4. 本轮实现范围

本轮只改 Studio 展示和本地 API 消费方式，不改 runtime 内核：

- 新增 `/api/overview` 消费，首屏展示 gate、doctor、package-check、runs、model routes。
- 重新组织主界面为 mission control，而不是普通聊天。
- 把事件 timeline 改为 phase lane，突出 model/tool/permission/final 状态。
- Inspector 增加 evidence/artifact/telemetry 的扫描式布局。
- Empty state 改为可执行入口：plan、run bounded、review、resume。
- 保持当前安全边界：localhost、脱敏、protected path 排除、写入动作仍由 runtime policy 控制。

## 5. 后续计划

- P0：接入 evidence bundle 导出按钮，输出脱敏诊断包路径和摘要。
- P0：把 gate/validation/release 的推荐动作做成只读 command preview。
- P0：把 route guidance 的 provider_route_strategy 展示为产品化判定，而不是裸 JSON。
- P1：展示 candidate workspace / promotion queue 状态，并支持 approve/reject/discard 的受控命令预览。
- P1：把 model streaming heartbeat 做成低噪声进度行：first chunk、last chunk、duration、idle timeout。

## 6. 智能体工作节奏

对话页真正好用的关键不是“像聊天”，而是把一次智能体工作过程编排成可理解、可折叠、可复盘的节奏。Asteria Studio 的主线程应该呈现一条完整 run narrative：

```text
User Goal
  -> Agent Thinking / Goal Understanding
  -> Plan / Task Contract
  -> Tool + MCP + Skill Preparation
  -> Tool Invocation
  -> Tool Result / Evidence
  -> Repair / Replan Loop
  -> Verification / Review
  -> Final Answer
  -> Folded Run Report
```

设计要求：

- 主线程保留“用户正在等待什么”的节奏：正在理解、正在组织工具、正在调用、拿到结果、正在修复、正在验证、已完成。
- 工具、MCP、skills 和 shell 细节默认折叠，但每一步必须能展开到 Inspector 看命令、输出、telemetry、evidence 和 artifact。
- 大模型输出分为 thinking/analysis、plan、final，不把所有 token 混成一团。
- 失败不是噪声，应成为循环节点：failed attempt -> diagnosis -> repair/replan -> retry result。
- 完成后自动生成 `Run Report`，把过程折叠成摘要：目标、关键步骤、工具调用、产物、验证、风险、下一步。
- Run Report 不能替代 evidence，只是把 evidence 翻译成用户可读结论。

本轮实现采用前端聚合，不改变 runtime 内核 schema：

- `toThreadEvents` 仍负责合并 streaming model delta。
- 新增 `buildRunNarrative` 把事件映射成过程节点和最终报告。
- 主线程展示 `NarrativeSummary` 和 `NarrativeStep`，原始事件继续能被选中进入 Inspector。
- 当存在 final/error 时显示完成态 `Run Report`；运行中则显示当前 active step。

后续若 runtime 补充更强的 event schema，Studio 再从启发式映射升级为 schema-driven timeline。

## 7. Evidence Explorer 与 Actionable Validation

在 run narrative 之后，Studio 需要把“发生了什么”继续推进到“证据在哪里、下一步做什么”。本轮补充两个只读能力：

- 新增 `/api/runs/:runId`，只读取 `.asteria/runs/<run-id>` 下固定证据文件：`run.json`、`cost_report.json`、`goal_spec.json`、`task_plan.json`、`task_plan_eval.json`、`agent_run_graph.json`，以及 model calls、task evidence、worker results、validation results、events 的 JSONL tail。
- Inspector 增加 `Evidence Explorer`，用户可以在最近 runs 间切换，扫读 model call、validation、worker、task evidence 摘要，并按需展开单条 JSON。
- Evidence Explorer 只展示证据和可预览文件，不执行命令、不读取任意路径、不突破 protected path 规则。
- 主栏新增 `Actionable Validation`，把 `gate-status --json` 的 `next_actions`、`route_guidance.recommended_actions`、`provider_route_strategy.recommended_action`、`validation_recommendation.command` 和 promotion 风险转成短行动项。
- 推荐动作默认是 command preview，用于提示用户下一步应验证、审查或阻断，而不是让 dashboard 绕过 runtime policy。

这一步让驾驶舱形成三层阅读顺序：

```text
Validation: 当前能不能继续
Run Narrative: 一次任务怎么推进
Evidence Explorer: 证据和下一步动作在哪里
```

后续继续增强时，优先把 evidence bundle 导出、promotion queue 审批预览和 provider route 策略解释接到同一套只读/受控动作模型里。
