# Asteria Studio 产品与架构

Asteria Studio 是 Asteria 的独立产品交互面和通用智能体前端载体。它不是新的执行内核，也不是远端托管服务；后端 runtime 仍负责护栏、证据、权限、计费、schema、恢复和验证边界。Studio 消费 runtime CLI/API、`.asteria/` 证据、`user_progress`、Inspector 和脱敏诊断包，同时承担用户心流、实时过程展示、文件预览/对比、Git 集成、MCP 管理、plugin 管理、skills 管理、session 管理、用户管理、token 额度查看、权限设置、模型设置和展示/配置管理。

当前优先级是先完成通用智能体 Asteria 的后端 runtime；Studio 的后端对接进度可以略落后。但 Studio 的产品设计长期有效，不能被降格成简单 dashboard 或命令包装器，也不应被临时后端实现反向绑死。

## 1. 产品定位

Studio 面向三类场景：

- 普通用户智能体工作区：输入 Goal / Plan / Ask，看到实时模型判断、工具调用、文件变化、权限请求、验证过程和最终结果。
- Project / Workspace 管理：像 Codex / Claude Code 一样展示最近项目，支持打开本地文件夹，切换后 session、run、Git、文件预览、MCP、plugin、skills 和设置都以该 workspace 为边界。
- 开发者本机内测：确认安装、路由、gate、validation、core、证据导出是否正常。
- 真实项目 dogfooding：查看 run timeline、模型调用、worker/validation evidence、promotion 风险和证据包。

Studio 不负责：

- 绕过 runtime policy 执行任务。
- 保存或显示 API key。
- 直接修改 `.asteria/` schema 对象。
- 取代 CLI / JSON 控制面。
- 做营销式 dashboard。
- 提供 unrestricted agent chatroom。

Studio 的原则是：视图层轻，runtime 可信。所有关键判断仍来自 runtime 命令和证据文件。

竞品调研与展示设计维护在 [Asteria Studio 竞品调研与展示设计.md](./archive/Asteria%20Studio%20竞品调研与展示设计.md)。当前展示方向从普通聊天页收敛为“任务驾驶舱 + 证据 Inspector”：第一屏优先回答 gate/route/runtime 是否可用，主线程承载任务 phase 和用户反馈，右侧承载 evidence、artifact、telemetry 和文件预览。



## 1.1 2026-05-24 Product/Ops separation principle

Studio must separate the real product experience from backend operations/debugging. Mixing chat, run status, evidence, model routes, goal_policy, and raw runtime details in the same primary thread makes the product feel neither like a good AI assistant nor like a professional operations console.

Product Workspace rules:

- The default entry is a normal AI/Agent input. Users state goals; they should not need to understand run, status, evidence, goal_policy, model route, schema, stdout, or run ids.
- The main thread is outcome-oriented: natural answers, clarified goals, permission requests when needed, task progress in user terms, and final deliverables.
- Backend objects are not shown in the main thread by default.
- If a request needs a long task, Studio may internally route to plan/run/goal loop, but the user should see only what matters: what is happening, what needs approval, what was completed, and what the next user action is.
- Chat/Auto is an intent and product-path selector, not a runtime control surface.

Ops / Debug Console rules:

- Add a separate AI Debug Agent for developers, internal testers, and operators.
- The Debug Agent can explain backend state: blocked reasons, model route rationale, costs, evidence, schema, gate/policy state, run loop, DecisionPoint, and validation/report artifacts.
- Inspector, Evidence Explorer, run detail, route timeline, goal_policy, and raw artifacts belong to Ops/Debug by default.
- Debug output may include evidence references and suggested CLI/backend actions, but it must not pollute the Product Workspace.



2026-05-24 correction after preview:

- Debug/Ops must not be mounted on the Product Workspace home page.
- The home page should stay focused on the user-side assistant experience: natural input, streaming answer, permissions when needed, progress in user terms, and deliverables.
- Inspector/Evidence Explorer/AI Debug Agent should be dormant or moved to a separate advanced URL such as `/ops` in a later phase.
- Until that separate route exists, do not expose Debug/Ops controls in the default app shell.

Target information architecture:

```text
Product Workspace
  normal user thread
  Auto input
  natural answers / goal clarification / permissions / deliverables
  no internal runtime state unless the user explicitly enters advanced/debug mode

Ops / Debug Console
  AI Debug Agent
  run/status/review/accept/evidence/model route/cost/gate/policy
  Inspector / Evidence Explorer / raw artifacts
  for developers, dogfooding, operations, and failure diagnosis
```

Future Studio work must first decide whether a feature belongs to Product Workspace or Ops Console. Product usability takes priority; observability serves debugging.

## 2. Agent Workspace

上一版 Studio 偏后台 dashboard，Conversation 被放在侧栏，只能问证据，不能承担“用户如何使用智能体”的入口。现在主界面应修正为 Product Workspace：

- Composer：用户用自然语言输入目标或问题。
- Mode selector：只暴露 Goal、Plan 和轻量 Ask/Chat；也可以由意图识别自动选择。
- Context / Tools menu：模型、skills、MCP servers、图片等属于上下文和能力选择，不是 runtime 命令入口。
- Progress thread：显示目标理解、计划、权限请求、用户级进展、验证结果和最终交付。
- Permission cards：需要写入、执行、联网、提权或增加预算时，请用户确认。
- Deliverables：预览生成的文件、报告、测试结果和验收回顾。
- Ops link：进入单独的 Ops / Debug Console，而不是在默认首页展示 backend 面板。

Studio P0 不应让用户直接选择 `execute-one`、`review`、`promotions`、`gate-status`、`validation` 等 runtime 命令。它可以在内部把自然语言和模式选择映射为受控 runtime action，但默认界面只展示用户能理解的 Goal / Plan / Ask 和结果进展。

写入型真实任务暂不直接从 Studio 自动执行。Studio 可以生成建议动作或权限卡，但必须走 runtime policy、预算、approval 和证据记录后再放开。

## 3. 工程边界

建议保持两个工程边界：

```text
asteria-runtime
  Python CLI / Runtime OS / gate / evidence / provider route

studio/
  React + Vite UI
  Node localhost API adapter
  subprocess 调用 asteria CLI
```

`studio/` 可以和当前仓库同源开发，也可以未来拆成独立仓库。第一版放在当前仓库中，方便共享文档和验证。

## 4. 本地 API Adapter

Studio 后端只监听 localhost，默认端口 `8787`。它提供稳定 JSON API：

```text
GET  /api/health
GET  /api/overview
GET  /api/workspaces
POST /api/workspaces/open
POST /api/workspaces/select
GET  /api/doctor
GET  /api/package-check
GET  /api/gate-status
GET  /api/runs
GET  /api/runs/:runId
GET  /api/model-routes
GET  /api/workspace-files
GET  /api/workbench-actions
GET  /api/agent-actions
GET  /api/conversations
GET  /api/conversations/:conversationId
POST /api/workspace-files/preview
POST /api/workbench-actions
POST /api/agent-actions
POST /api/conversations
POST /api/evidence-bundle
```

`POST /api/agent-actions` 接收 `actionId`、`message`、`execute`：

- `execute=false`：只返回命令预览。
- `execute=true`：只执行白名单安全动作。
- 写入型动作：返回命令建议，不直接执行。

实现规则：

- 优先调用 runtime CLI 的 `--json` 输出。
- 对没有 JSON 输出的视图，读取 `.asteria/` 中的 JSON/JSONL evidence。
- API adapter 启动时必须绑定一个 workspace；所有 run/session/evidence/file preview 默认从该 workspace 读取。
- 全局 recent workspace、current workspace、模型本机 route 和 UI 偏好读取用户目录下的 `.asteria/`；单工程 evidence、session、run、Studio conversation 必须读取 workspace 内 `.asteria/`。
- API response 必须脱敏。
- 不读取 protected paths。
- 不把 API key、route local 文件或 `.env` 发送给前端。
- 文件预览只允许安全白名单路径和小文本文件，默认排除 secrets、`.env`、`.git`、`model.routes.local.*`、`node_modules`、`dist`。

## 5. 证据字段

Studio 第一版依赖这些稳定字段：

- `gate-status --json`：`stage`、`release_ready`、`release_state`、`blocking_reason`、`gates`、`route_guidance`、`evidence_sources`、`next_actions`。
- `doctor --json`：`checks`、`routes`、`sandbox`、`plugin_control`。
- `package-check --json`：`checks`、`artifacts`、`runbook`。
- `.asteria/runs/<run-id>/`：`run.json`、`cost_report.json`、`events.jsonl`、`model_calls.jsonl`、`task_execution_evidence.jsonl`、`worker_results.jsonl`、`validation_results.jsonl`。
- `.asteria/model/capability_profile.json`。
- `.asteria/studio/conversations.jsonl`。

## 6. Conversation 数据契约

Conversation 是 Studio 自己的本地状态，落在 `.asteria/studio/conversations.jsonl`。它不进入 runtime 核心 schema，但必须可审计、可导出、可删除。

P0 assistant response 可以先使用规则化解释，但必须明确这是受限解释，不可冒充真实智能体执行结果：

- gate/status 问题读取 `gate-status --json`。
- provider 慢/超时问题读取 model route summary。
- run 问题读取 selected run detail。
- “下一步”问题返回 `next_actions` 和建议命令。

后续把 Conversation 接入真实模型时，必须走 runtime policy、预算、approval 和 evidence logging。普通对话默认只使用动态上下文；长期任务状态只在用户询问状态、进展、计划或下一步时挂载。

## 7. 安全边界

Studio 必须默认排除：

- `.env`、`.env.*`
- `secrets/`
- `.git/`
- `*.pem`、`*.key`
- `model.routes.local.ps1`
- `model.routes.local.json`
- 任意包含 `api_key`、`token`、`authorization`、`password`、`secret` 的字段值

前端只显示：

- key 是否 present。
- provider / model / base_url。
- route latency 和调用结果。

## 8. 体验目标

Studio 第一屏应该回答：

- 现在能不能进入内测？
- 如果不能，卡在 gate、validation、route、promotion、plugin、环境还是证据缺口？
- 我在哪里和智能体继续对话、确认权限、看执行反馈？
- 我下一步应该运行哪个动作？
- 我不用背 CLI，能不能直接从界面触发安全动作？
- 生成了哪些文件、证据或报告，能不能直接预览？
- 最近一次真实 run 是成功、失败、blocked 还是需要人工决策？
- strong / medium provider 是慢、超时、失败，还是当前网络环境差？
- 我前面问过什么，系统当时依据哪些证据给出判断？

这比漂亮图表更重要。
