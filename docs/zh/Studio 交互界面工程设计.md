# Studio 交互界面工程设计

状态：`design`

更新时间：2026-07-02

本文是 Asteria 交互界面（Studio 前端）的**工程设计真源**，与后端的 [Asteria 模型主导运行时设计](./Asteria%20模型主导运行时设计.md) 互为对偶：一篇讲 Runtime 内核怎么实现，本篇讲交互面怎么实现。

与既有 Studio 文档的分工（不重复，互补）：

| 文档 | 回答的问题 | 层级 |
| --- | --- | --- |
| [Asteria Studio 产品设计](./Asteria%20Studio%20产品设计.md) | Studio 是什么、为谁、信息架构、非目标 | 产品 |
| [Studio 会话与上下文设计准则](./Studio%20会话与上下文设计准则.md) | 什么进主会话、什么进 Inspector、session/context 规则 | 体验约束 |
| [用户交互模型](./用户交互模型.md) | CLI 侧 Goal/Plan/Ask、权限三档 | 命令交互 |
| **本文** | **前端怎么搭：技术栈、进程、数据流、构建、测试、诚实不变量** | **工程实现** |

定调（用户 2026-06-28）：**后端是内核（已证明可用），前端才是交互**；UI 比命令行更适合大众，命令行适合专业开发者。前端**对标当前最火的 Codex 与 Claude Code**——它们是行业最优秀的产品设计者。落地路线见 [前端产品化路线](./前端产品化路线.md)。

## 1. 架构定位

```text
Studio = Runtime 证据的本地客户端（ADR-0015），不是第二个 Runtime。
前端只读取 .asteria/ 下已落盘的证据 + 通过 server.mjs 向 Runtime 提交动作，
绝不在前端复算任务状态、重建叙事、或编造最终答案（ADR-0012）。
```

两条硬约束贯穿整个前端，每个组件落地前都要回到这两条：

- **ADR-0012**：主会话只消费 Session Transcript（`display_level=main` 的真实事件）；诊断进 Inspector；禁止从 `runtime_progress` / summary 重建会话过程或编造终答。
- **ADR-0015**：Studio 是证据客户端；状态由 Runtime 拥有，前端是投影，不是权威。

## 2. 技术栈与仓库布局

| 维度 | 选型 |
| --- | --- |
| UI 框架 | React 19 + TypeScript（ES modules） |
| 构建 | Vite 7（`@vitejs/plugin-react`） |
| 图标 | `lucide-react` |
| 服务端 | 纯 Node `http`（无框架），`studio/server.mjs` |
| 传输 | SSE 主推 + 轮询回退 |
| 持久化 | 无独立 DB；一切以 `.asteria/` 文件证据为真源 |
| 设计系统 | `styles/tokens.css` 单一真源（调色板/间距/圆角/字阶/阴影/焦点/滚动条/焦点环）；组件**消费 token，禁止硬编码颜色**——产品级一致性的前提 |

仓库布局（`studio/`）：

```text
server.mjs            # Node API + 静态托管；读 .asteria 证据、广播 SSE、转交 Runtime 动作
vite.config.ts       # dev 代理 /api → 127.0.0.1:8787
start-studio.ps1     # 启动器：拉起 server.mjs + vite dev
dist/                # 构建产物（gitignore，按需 build）
scripts/             # smoke / contract / Playwright 测试
src/
  features/
    thread/          # 主会话：ConversationTurn / TurnFinal / SuggestedActions / LiveStream / ToolCallCard / Thread / RuntimeSnapshot
    inspector/       # 诊断：EvidenceExplorer / VerificationMatrix / DiffReviewPane / SelectedStepPanel
    sidebar/         # SessionRail / SessionList（会话与 workspace）
    sidechat/        # SideChatPanel（display_level=side 旁路问答）
  components/        # 共享 UI：NarrativeStep / PermissionCard（含 scope_detail 披露）/ Composer / Clamped/Diff chips /
                     # SettingsPanel（统一 Settings 入口）/ ToastViewport+toast.ts（确认系统）/ Skeleton（首屏加载态）
  capability.ts      # MCP/Skill 能力面（mcp__server__tool / skill__name 主线程实名化）
  permissionTiers.ts # 权限档词表归一（ask/reviewed_auto/auto）
  hooks/             # useViewMode / usePaneLayout / useDiffFocus / useStudioKeyboard …
  session/           # 取数与合并：useSessionEvents / useRunEvidence / useStudioBootstrap
  layout/ styles/    # 顶层布局与样式
```

## 3. 进程与启动模型

`asteria studio` 通过 `start-studio.ps1` 拉起两段进程：

1. **API 后端**：`node server.mjs --workspace <path> --runtime-root <path> --port <p> --python <cmd>`，默认端口 **8787**。
2. **UI dev**：`npm run dev`（Vite，默认 **5174**），`/api/*` 经 `vite.config.ts` 代理到 8787。

两种形态：

- **开发**：Vite 跑 5174 出 UI、热更新；API 在 8787。
- **打包/演示**：`npm run build` 出 `dist/`，由 `server.mjs` 同进程静态托管 + 提供 API（单端口）。本机 Beta 证据回放即此形态（如 `validation_small_cli` workspace）。

端口由 `--port` 决定，不写死；前端永远走相对 `/api`，不硬编码端口。

## 4. 服务端契约（server.mjs）

`server.mjs` 是**无状态的会话/证据中转**：不拥有任务状态，只做「读 `.asteria` 证据 + 转交 Runtime 动作 + 广播」。主要路由：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 + workspace/runtime 配置回显 |
| GET/POST | `/api/studio/sessions[/{id}]` | session CRUD（id 形如 `session-<ts>-<rand>`） |
| GET | `/api/studio/sessions/{id}/events` | 取会话事件（JSONL） |
| GET | `/api/studio/sessions/{id}/events/stream` | SSE（15s ping），新事件即推 |
| POST | `/api/studio/sessions/{id}/messages` | 提交 Goal（mode / permission / channel） |
| POST | `/api/studio/sessions/{id}/runtime-actions` | 执行下一步动作（Continue / Debug …，转交 Runtime） |
| POST | `/api/studio/sessions/{id}/decisions/resolve` | 裁决 DecisionPoint |
| PATCH | `/api/studio/sessions/{id}/jobs/{jobId}/permission` | allow/deny 权限请求 |
| GET | `/api/runs/{runId}` | run 详情（goal_spec / task_plan / user_progress / summary） |
| GET | `/api/overview` | 诊断：gate / route / background runs |
| GET | `/api/studio/git/*` | workspace git status / diff / stage / discard |

证据读取（事件如何成为前端能消费的流）：

1. `readSessionEvents(sessionId)` 读 `sessions/{id}/events.jsonl`，脱敏；对 `type=final_answer` 且 `phase≠chat` 的事件，用 run 产物补全。
2. `readRuntimeUserProgressEvents(runId)` 读 `.asteria/runs/{runId}/user_progress.jsonl`，把 user_progress 转成 `StudioEvent`，**只放行 `display_level` 为空或 `main`** 的条目。
3. `mergeSessionAndRuntimeEvents()` 按时间戳交织 session 与 runtime 事件。

run 级产物：`user_progress.jsonl`（主时间线）、`final_report.md`、`goal_spec.json`、`task_plan.json`、`eval_report.json`、`cost_report.json`、`agent_loop_run_summary.json`（含 `loop_quality`）。

传输：SSE 为主（15s keepalive）；SSE 不可用时轮询回退（常态 ~8s，降级 ~1.2s）。**前端体验诚实地跟随该传输节奏，不靠前端定时器伪造更快的流**（见 §6）。

## 5. 客户端数据流

一条会话从原始事件到渲染的管线：

```text
useSessionEvents()                # 轮询 /events + 订阅 SSE
  → StudioEvent[]                 # session + runtime 事件，按 display_level 过滤
  → toNarrativeEvents()           # 合并 model_start→delta→end 为单个 model_delta
  → buildRunNarrative()           # 归一为 RunNarrative{ steps: NarrativeStep[], report }
  → splitIntoTurns()              # 按用户回合边界切成 Turn（NarrativeStep[] 组）
  → ConversationTurn × N          # 每个 Turn 渲染：用户消息 + 过程 + 终答
```

关键转换文件：

- `narrative.ts` — `toNarrativeEvents()`（折叠流式三段）、`narrativeKind()`（事件 → step 类型：goal/thinking/plan/tool/final…）。
  - **终答选择（CV-C）**：run 模式收尾会发两个 `transcript_kind=final` 事件——`conclusion`（event_type=`message`，承载模型撰写的复盘 `content_delta`）与 `final_report`（event_type=`final_report`，仅是产物指针）。`narrativeKind()` 把 `runtime_event_type==='final_report'` 降级为流程内 `result` step（标签「Final report」），于是带复盘的 `conclusion` 成为 `ConversationTurn` 渲染的终答（`TurnFinal`）。产物指针属诊断（ADR-0012），artifact_refs 仍进 Inspector。
- `turnDiff.ts` — `splitIntoTurns()`（回合切分）。
- `turnHelpers.ts` — `middleRepresentativeEvent()` / `middleSummary()`（折叠回合的代表事件与摘要标签）。
- `runtimeNarrative.ts` — `runtimeSessionEvents()`：`.asteria/runs/{id}/user_progress.jsonl` → 带 `display_level=main` 的 `StudioEvent[]`；保留事件真实 `content_delta`（如 CV-C 复盘），仅在无对话文本时回退到 summary 投影。

`StudioEvent` / `NarrativeStep` 的类型定义在 `src/types.ts`，是前端与服务端事件契约的单一形状真源。

### 5.1 模型撰写的对话式复盘（CV-C，后端对偶）

主线读什么取决于 Runtime 发什么。为让终答像「一句话回复」而非状态行，后端 `core/run_recap.py` 在 `run_command.continue_run` 收尾用一次**尽力而为**的模型调用撰写 1–3 句第一人称复盘（上下文 = goal + 状态 + 校验结论 + 改动文件 + loop steps），写入既有 `conclusion` 事件的 `content_delta`。失败或无模型时返回 `""`，回退原结构化 summary，运行链不依赖它。前端不做任何合成——只把这段真实文本原样渲染（ADR-0012）。`run_command.py` 属 DO_NOT_TOUCH（仅 append user_progress），故只**新增**辅助方法、不重构既有发射。

## 6. 主线 vs Inspector 分层（ADR-0012 / 0015 落到组件）

| 层 | 数据 | 组件 |
| --- | --- | --- |
| **主会话**（只 `display_level=main`） | 用户消息、模型思考、工具过程、权限卡（含 scope_detail）、文件变化、终答、内联建议 chip | `Thread` · `ConversationTurn` · `TurnFinal` · `SuggestedActions` · `LiveStream` · `ChatStreamPreview` · `RuntimeSnapshot`（diff 评审 gate）|
| **Inspector**（全量、诊断） | 原始 JSON、cost、route、worker graph、agent_loop_run_summary、校验矩阵、loop_quality、逐步遥测、diff | `EvidenceExplorer` · `VerificationMatrix` · `SelectedStepPanel` · `DiffReviewPane` |
| **旁路**（`display_level=side`） | 不打断主线的问答 | `SideChatPanel` |

不对称是有意的：主线为用户给**干净叙事**（在 `runtimeNarrative` 过滤），Inspector 为工程师给**全量证据**。两者消费同一套 Runtime 证据，但默认不混进一个主线程。

## 7. 诚实工程不变量（每个前端 slice 必守）

这是 Studio 前端区别于「演示玩具」的核心，也是 ADR-0012 在前端的具体化。任何新组件落地前对照：

1. **不伪造流式**：模型输出按 `content_delta` 到达即渲染，禁止客户端打字机/人工定时逐字。
   - 现状：`ConversationTurn.tsx` 的 `useSmoothText` 打字机**已删除**（slice #1，commit `80477c5`），`ChatStreamPreview` 直接渲染真实 delta。
2. **不编造终答**：终答只能是 Runtime 真实 transcript 文本。
   - 现状链路：server **不再**把终答重写成 `final_report.md` 诊断报告（CV-A，三处 clobber 已删）；`TurnFinal.tsx` 渲染 lead 散文 + 把结构化尾部折叠进默认收起的「运行详情」disclosure（CV-B），缺文本时给诚实短句而非编造 `"Done."`；终答的对话语气由后端**模型撰写**的复盘提供（CV-C，见 §5.1），前端原样显示、零合成。slice #2 的 `finalSections`/Result/Verification/Risk 脚手架已删除。
3. **不重建叙事**：`task_plan.json` / `runtime_progress.todo.counts` 已进 payload 很诱人，但据其在前端渲染清单 = 复活被否决的 WorkflowPhaseStrip，**禁止**。要展示计划只能源自 `transcript_kind=plan` 的 main 事件。
4. **不前端推断权限/完成**：文件范围以 `permission_preview.scope_detail` 为准、不靠关键词猜（slice #8：`PermissionCard` 在 allow/deny 前用「Review what this touches」披露 runtime 提供的 read/write/tools/requests，仅在真有该字段时渲染）；Accept 只走 runtime_policy，绝不伪造完成（slice #5：有改动时 Accept 在打开过 diff 评审前禁用）。
5. **工具输出折叠**：工具卡默认折叠，原始 stdout/traceback 选中联动 Inspector，不在主线内联全量输出。
6. **不 dump，给结构**：校验结果以 `VerificationMatrix` 结构化 pass/fail 行 + loop_quality 徽章呈现（slice #7），替换 `<pre>` JSON dump；缺数据显示 not recorded，不编造。

> 经验法则：**当 Runtime 没给某个字段时，正确答案永远是「如实显示缺失」，而不是「编一个合理的占位」。** 删假本身是去噪（不是新功能 Slice），不受 freeze 限制。

## 8. 构建 · 开发 · 验证

| 动作 | 命令 |
| --- | --- |
| 安装 | `cd studio && npm install` |
| 开发 | `npm run dev`（5174）+ `npm run server`（8787），或 `start-studio.ps1` 一并拉起 |
| 类型检查 | `npm run build` 内含 `tsc --noEmit`（或单独 `npx tsc --noEmit`） |
| 构建 | `npm run build` → `dist/` |
| 启动器 | `asteria studio`（经 `start-studio.ps1`） |

测试面（`studio/scripts/`，约 30+ 项）：

- **主路径 e2e**：`interactive-main-path.spec.mjs`（Playwright）——真实渲染一轮对话，覆盖权限解析、DecisionPoint、diff review、动作按钮。需 `@playwright/test` + 浏览器方可运行；每个 slice 应跑它保主路径绿，不只看定向 JS smoke。
- **契约 smoke**：`session-main-path-contract.mjs`（如 Thread 内无 WorkflowMonitor、RuntimeSnapshot 内无 PermissionCard、事件顺序）、`run-detail-smoke.mjs`、`chat-lifecycle-smoke.mjs`、`intent-routing-smoke.mjs`、`plan-output-smoke.mjs`、`user-thread-copy-smoke.mjs`。

**已知红**：`chat-stream-final-smoke.mjs` 当前失败（假后端不发 `final_answer`，与本会话改动无关，clean tree 同样红，已挂独立 chip 跟踪）。改前端时以「该 slice 相关 smoke + 主路径 spec」为验收，不把无关历史红算到本次。

每个前端改动的最小验收口径：`tsc --noEmit` 干净 → `vite build` 干净 → 该 slice 相关 smoke 绿 →（涉及主路径渲染时）`interactive-main-path.spec.mjs` 绿。

## 9. 演进与冻结合规

落地顺序见 [前端产品化路线](./前端产品化路线.md)（8 个 slice + DS 设计系统轨 + CV 对话流轨，源自 design/understand workflow）。**三轨已全部落地**：

- **诚实化 #1–#8**：✅ #1 诚实流式 · #2 干净终卡 · #3 内联工具卡 · #4 loop-health 面板 · #5 diff 评审 gate（`RuntimeSnapshot` Accept 前置评审）· #6 内联建议 chip（`SuggestedActions`）· #7 校验矩阵（`VerificationMatrix` + loop_quality 徽章）· #8 权限 scope 保真（`PermissionCard` scope_detail）。
- **设计系统 DS-0…DS-3**：✅ token 基线 + 全表面迁移 + 语义色归一（raw hex 归零）+ 会话线深度打磨（节奏/抬升/70ch/markdown 排版）。
- **对话流 CV-A…CV-C**：✅ server 停止 clobber · `TurnFinal` lead/折叠 · runtime 模型撰写对话式复盘（§5.1，根治）。

冻结合规：三轨全是**去噪/删重构 + 扩既有面板 + 设计一致性 + 对真实 friction 的根治**，不是独立新功能 Slice，故不触 Studio freeze。**无**新编排 Wave / 全局 parallel_writes / maintainer 命令。CV-C 触内核但仅 append user_progress、不重构既有逻辑，且由用户 2026-06-28「把诊断的未实现都做了」明确裁决授权。需真实 Beta friction 才解锁的 defer 项（Plan/Todo 卡、成本仪表盘、流式 stop/interrupt、逐 token 传输改造）见路线图 §「显式 defer」。

**下一层（已立项 · 待实现）**：对话流对标完成后，外壳/布局/视觉语言的 IDE 化改造已立项——方案见 [plans/Studio-IDE-shell-重设计方案](./plans/Studio-IDE-shell-%E9%87%8D%E8%AE%BE%E8%AE%A1%E6%96%B9%E6%A1%88.md)（全幅 IDE 工作区 + 全局头部 · 会话栏保持 · 改动文件进评审面 · Phase A 表层快赢 → B 骨架 → C 打磨）。同样纯 token/CSS、不碰后端与对话流诚实工作。本文 §6 分层表与 §5.1 在该方案落地后同步更新。

## 10. 约束真源

- ADR：[0012 Session Transcript 主路径](./adr/0012-session-transcript-as-studio-main-path.md) · [0015 会话循环即产品架构](./adr/0015-session-loop-is-product-architecture.md) · [0014 单会话恢复与显式 Review](./adr/0014-single-session-recovery-and-explicit-review.md)
- 产品/体验：[Asteria Studio 产品设计](./Asteria%20Studio%20产品设计.md) · [Studio 会话与上下文设计准则](./Studio%20会话与上下文设计准则.md)
- 后端对偶：[Asteria 模型主导运行时设计](./Asteria%20模型主导运行时设计.md)
- 协议：[用户进展与证据协议](./用户进展与证据协议.md)
- 路线：[前端产品化路线](./前端产品化路线.md)
- 重设计：[plans/Studio-IDE-shell-重设计方案](./plans/Studio-IDE-shell-%E9%87%8D%E8%AE%BE%E8%AE%A1%E6%96%B9%E6%A1%88.md)（外壳/布局 IDE 化，已立项待实现）
