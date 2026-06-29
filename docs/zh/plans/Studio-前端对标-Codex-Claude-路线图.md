# Studio 前端对标 Codex / Claude Code 路线图

> 来源：多智能体 design workflow（understand → 3 方向 design → synthesize，8 agents）。
> 方向定调（用户 2026-06-28）：后端是内核（已证明可用），**前端才是交互**；UI 比命令行更适合
> 大众，命令行适合专业开发者；接轨市场是常见做法。前端要**对标当前最火的 Codex 与 Claude Code**
> ——它们是行业最优秀的产品设计者。

## 落地状态（2026-06-28 · 全部完成）

本路线图三条轨已全部落地并合并 main：

- **诚实化功能 slice #1–#8**：✅ #1 诚实流式 · #2 干净终卡 · #3 内联工具卡 · #4 loop-health 面板 ·
  #5 diff 评审 gate · #6 内联建议 chip · #7 校验矩阵 · #8 权限 scope 保真。
- **设计系统轨 DS-0…DS-3**：✅ token 基线 + 全表面迁移 + 语义色归一（raw hex 归零）+ 会话线深度打磨。
- **主线对话流 CV-A…CV-C**：✅ server 停止 clobber · 终卡 lead/折叠 · runtime 模型撰写对话式复盘（根治）。

**下一层（Phase A + Phase B 全量已落地 · Phase C 收口待启动）**：对话流对标完成后，下一层是承载对话的**外壳/布局/视觉语言**——
用户 friction（2026-06-28）「风格和布局跟 codex/claude code 的 IDE 差距太大」。经 design-review workflow
（4 路审计 + 综合）+ 用户决策锁定 + 5 路实现前 audit 校准，方案见 [Studio-IDE-shell-重设计方案](./Studio-IDE-shell-%E9%87%8D%E8%AE%BE%E8%AE%A1%E6%96%B9%E6%A1%88.md)
（全幅 IDE 工作区 + 全局头部；会话栏保持；改动文件进评审面；纯 token/CSS，不碰后端与对话流诚实工作）。
**Phase A（表层快赢）已实现于工作树**：mono 机器文本、头像扁平化、去药丸（`--radius-control`）、去装饰渐变、抬升仅留浮层（覆盖 DS-3 in-flow 阴影）、微标签归一、状态左缘、New task 图标——`tsc`+`vite build` 干净、main-path 契约绿、raw-hex 归零。
**Phase B 增量 1（B1+B2）已实现于工作树**：经 4 路架构 recon，全局头部行（`grid-template-rows`，`MissionPaneHeader` 提升为壳首子、跨全宽、带运行状态 pill）+ 全幅工作面（清 5 处 `--thread-max` cap、删 `useThreadColumnWidth` JS 驱动、prose 改静态 70ch、dock 偏移改 `calc(--panel-width)`）+ 窄屏单列全幅（修 @820 被 @1240 `!important` 压过的死规则）——`tsc`+`vite build` 干净、契约绿、桌面/窄屏预览核验、console 0 错误。B3/B4/B5 经 3 路 reference-first 调研锁定决策后全部落地（B4 头部分组+Diff badge `3e4bde1`、B3 评审面 diffFocus 对等 ~50vw `e3bc625`、B5 composer 三意图 segmented + overflow `e3e3c45`）。**Phase B 全量完成**；剩 Phase C（原语统一 `.btn`/`.badge` / 去卡片 / 密度收口）。

其余 Studio 改动仍以**真实 Beta friction 证据**驱动（见末尾 defer 集）；无新 friction 不再加 Studio 新功能。

## 核心洞察（为什么这条路同时合规又对标市场）

Studio 现状最伤体验的几处，恰恰不是"缺功能"，而是**前端在造假**：

- `ConversationTurn.tsx` 用 `useSmoothText` 客户端打字机（28 字/28ms）在 8s 轮询之上**伪造**流式——
  内容先爆发到达、再被人为地"打"出来，明显不像 Codex/CC 的真实 token 流。
- `TurnFinal.tsx` 在缺数据时**编造** "No verification summary was recorded" / "No immediate next action"
  之类的占位结构，把每条回答（哪怕一句话）强行重构成 Result/Verification/Risk 模板。

这两处既**违反 ADR-0012**（主线只渲染 `display_level=main` 的真实事件，禁止重构叙事、禁止编造最终答案），
又是最不像成熟 agent 产品的地方。**删假**不是"新功能 Slice"，因此**不受 freeze 限制**，反而是 MAP-D §4
要求优先做的去噪。于是"对标 Codex/Claude"与"收敛/诚实"在这里是**同一个方向**。

## 方向评分（design workflow）

| 方向 | ADR | Grounded | UX 价值 | 低成本 | 合计 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| D1 会话优先（Claude Code 式诚实流式/干净终卡） | 5 | 5 | 5 | 4 | **19** | 主线，先删假去噪 |
| D3 证据与信任（Inspector-forward：loop_quality/校验/成本） | 5 | 5 | 3 | 5 | 18 | 零风险，扩既有面板 |
| D2 Agent 工作台（Codex 云式 plan/diff/approve） | 3 | 4 | 5 | 3 | 15 | 价值最高但最贴 ADR-0012 红线，部分 defer |

## 优先级 slice 路线图

| # | Slice | 组件 | 对标模式 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | **诚实流式**：删打字机，真实 content_delta 到即渲染 | `ConversationTurn.tsx` | CC 实时 delta | ✅ 已落地 |
| 2 | 干净终答卡：渲染真实 Runtime 内容，停止编造 Result/Verification/Risk 占位 | `TurnFinal.tsx` | CC 终答卡 | ✅ 已落地 |
| 3 | 内联折叠工具卡（tool_use↔tool_result，默认折叠，原始全量留 Inspector） | `LiveStream.tsx` + `ToolCallCard.tsx` | CC/Codex 工具披露 | ✅ 已落地（live 视图）|
| 4 | **loop-health 面板**：在 Inspector RunStatusPanel 露出 `loop_quality` SLO（warn/severity/窗口/reason） | `EvidenceExplorer.tsx` | Codex/CC 按需深证据 | ✅ 已落地 |
| 5 | 工作区 diff 评审作为主线 gate（chip→同 Inspector diff scope，Accept 前只读评审） | `RuntimeSnapshot.tsx` | Codex diff/approve | ✅ 已落地（`c9adf28`）|
| 6 | 跟随相关 turn 的逐事件建议动作 chip（非顶部固定） | `SuggestedActions.tsx` + `ConversationTurn.tsx` | CC 内联建议 | ✅ 已落地（`c9adf28`）|
| 7 | 校验结果矩阵（结构化 pass/fail，替换 `<pre>` dump） | `VerificationMatrix.tsx` + `EvidenceExplorer.tsx` | 信任可扫读 | ✅ 已落地（`c9adf28`）|
| 8 | Runtime 背书的 approve/accept gate（提升权限预览保真，绝不伪造完成） | `PermissionCard.tsx`（scope_detail） | Codex approve | ✅ 已落地（`c9adf28`）|

## 设计系统对标轨（产品级一致性 · 用户 2026-06-28 friction：「前端跟产品级对标差很远」）

功能 slice（上表 1–8）让主线**诚实**；但产品级观感的真正短板是**设计不一致**：组件绕过
`tokens.css` 硬编码颜色（accent 蓝出现过 5 种）、圆角漂移、间距局促——这才是「不像成熟产品」。
故新增一条与功能 slice 并行的**设计系统轨**：把 `styles/tokens.css` 做成被真正消费的单一真源，
再把所有表面迁移上来。原则：**组件消费 token，禁止硬编码颜色**（见 [工程设计](../Studio%20交互界面工程设计.md) §2）。

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| DS-0 | tokens v2 基线：accent 单链 + surface 阶梯 + 间距/字阶/圆角/阴影 + 全局焦点环/滚动条/选区 | ✅ 已落地（`a76ad4a`）|
| DS-1 | 高频表面迁移：thread-turn / composer / sidebar / components | ✅ 已落地（`a76ad4a`）|
| DS-2 | 剩余表面迁移（消除全部漂移）：inspector ×4 / layout / shell / side-chat / thread-shell / thread-narrative / session-list + 补齐 DS-1 残留（thread-turn / composer / components） | ✅ 已落地（`2cf8971` + 本提交）|
| DS-2c | 语义独色升级为 token（permission 紫 / chat-teal / brand 渐变 / solid action / composer mode 微染 / scrollbar）→ raw hex 归零 | ✅ 已落地（`058eeab`）|
| DS-3 | 深度打磨（会话线做到 Codex 级）：turn 节奏 + 终卡抬升阴影 + 70ch 阅读宽度 + markdown 排版节奏 + 减动效友好 | ✅ 已落地（`34825da`）|

> DS-2c 完成后**全仓 raw hex 已归零**：`styles/*.css`（除 `tokens.css` 定义外）独立 grep `#[0-9a-fA-F]{3,8}` 无命中。
> 语义独色（permission / chat-teal / brand 渐变 / solid action / composer mode 微染）全部升级为命名 token；
> 一次 fan-out 迁移还顺带收掉了原审计漏掉的漂移（composer mode 渐变、sideAsk 边框、user-message 气泡、scrollbar、sidebar 图标）。

迁移规则（每个表面照此，**不改布局/行为/选择器**，仅把颜色/圆角值换 token）：
- 背景：最深→`--surface-0`；面板→`--surface-1`；卡片/输入→`--surface-2`；抬升/hover→`--surface-3`
- 边框：`--border-subtle`/`--border-strong`；文本：`--text-primary/secondary/muted`
- accent（任何作主色/选中/active 的蓝）→`--accent` 系；状态绿/黄/红→`--ok`/`--warn`/`--bad`(+`-subtle`)
- 圆角 6→sm、7–9→md、12–14→lg、999→pill
- 语义独色（如 permission 紫）暂留色相，但邻近中性也 token 化，并登记为"待补语义 token"

## 主线对话流改造（用户 2026-06-28 friction：「主窗口不是对话流」）

**根因（research workflow `w02hco3zz` 证实）**：`server.mjs` 把助手终答**重写成 `final_report.md` 诊断报告**
（Current State / Todo / Workspace 路径 / Model Selection / Promotion Queue / Verification Evidence / 过程摘要），
三处 clobber：run close-path fallback + 每次 re-read 的 `readSessionEvents` + `enrichFinalAnswerEvent`。这既违反
ADR-0012（诊断进 Inspector），也是「像报告不像对话」的根因。前端骨架本就正确（user→折叠过程→内联终答；文件卡→Inspector 已接好）。

对标依据：Codex = 流式过程→折叠→综合结论；Claude Code = 完整过程流→末尾内联复盘、不折叠；两者工具调用默认折叠、可实时展开。

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| CV-A | server 停止三处 clobber：终答保留 runtime 真实 `display_level=main` transcript，诊断只留 `artifact_refs` 供 Inspector；无终答时给诚实短句 | ✅ 已落地（`0b2296a`）|
| CV-B | `TurnFinal` 渲染 lead 散文 + 把结构化尾部折叠进默认收起的「运行详情」disclosure；删 slice#2 的 section 脚手架。对存量会话即时生效 | ✅ 已落地 |
| CV-C | **（后端轨/内核）** runtime 由**模型撰写**一段对话式复盘结论作为 `final` transcript，Studio 原样显示——最优解、最贴 CC/Codex | ✅ 已落地（`fe70fec`）|

> 关键发现（已解决）：runtime 原本只发**短/结构化** final 片段（如「task-0001 completed with verified evidence」+ 指针），
> 没有模型撰写的对话式复盘。CV-C 落地方式（见下）：在 `run_command.continue_run` 收尾、写 final 报告之后，由 `core/run_recap.py`
> 用一次**尽力而为**的模型调用撰写 1–3 句第一人称复盘，写入既有 `conclusion` 事件的 `content_delta`；前端把 `final_report`
> 指针事件从「final」step 降级为流程内「Final report」步骤，于是带复盘的 conclusion 成为渲染的终答。
>
> 合规要点：`run_command.py` 属 DO_NOT_TOUCH（仅允许 append user_progress），本次仅**新增** `_closing_recap_text` 辅助 +
> 给既有 conclusion 事件补 `content_delta`，未重构任何既有发射逻辑；recap 失败时返回 ""，回退到原结构化 summary，运行链不依赖它。
> 用户 2026-06-28「把诊断的未实现都做了」即为本内核改动的裁决授权。

## 冻结合规

active 集（1–8）全部是**去噪/删重构 + 扩既有 Inspector 面板**，不是独立新功能 Slice，故不触 freeze；
1–2 删假、3/6 重排已在主线的数据、4/7 扩既有面板、5 收紧既有 S45/S48 diff、8 深化既有 decision 流。
**无**新编排 Wave / 全局 parallel_writes / maintainer 命令。

**显式 defer（需真实 Beta friction 才解锁）**：D2 的 Plan/Todo 卡（新面 + 最贴 ADR-0012 重构红线，
若做只能源自 `transcript_kind=plan` 的 main 事件，绝不从 `task_plan.json`/`todo.counts` 重构）；
D2 的轮次/exit 计数器（loop 内部遥测）；D1 的流式 stop/interrupt（触子进程桥的新能力）；
D3 的成本面板（近新块，只上一个可展开块、注明 friction，不做 dump 仪表盘）。

## 风险（workflow 提示，落地每个 slice 时核）

- **ADR-0012 重构陷阱**：`task_plan.json`/`runtime_progress.todo.counts` 已进 payload 很诱人，但据其渲染清单 = 复活 WorkflowPhaseStrip，禁止。
- **#4 实现校正**：`agent_loop_run_summary` schema **无 `recovery_chain` 字段**，故 #4 只露出真实存在的 `loop_quality`（缺失时显示 not recorded），不编造 recovery 链；如需 recovery 视图须先在 runtime 落 schema 字段。
- 工具卡（#3）保持默认折叠，原始 stdout/traceback 选中联动 Inspector，不内联全量输出。
- 终卡（#2）缺数据时渲染"未记录/not recorded"，**不得**静默丢节、**不得**在无 final|stop 事件时编造终答；改后过 wording smoke。
- 传输仍是 8s 轮询 + best-effort SSE；诚实流式改善观感但不超过轮询节奏；真·逐 token 需 server.mjs 传输改造（更大、friction-gated，不在 #1）。
- approve gate（#8）：文件范围用 `permission_preview.scope_detail` 为准、不前端关键词推断；Accept 只走 runtime_policy，绝不伪造完成。
- 每个 slice 还要保 Playwright 主路径 smoke（`interactive-main-path.spec.mjs`）真实渲染一轮对话为绿，不只看定向 JS smoke。

## 约束真源
- ADR-0012：主线只消费 Session Transcript（`display_level=main`）；诊断进 Inspector；禁止从 runtime_progress/summary 重构会话或编造终答。
- ADR-0015：Studio 是证据客户端，不是第二 Runtime。
