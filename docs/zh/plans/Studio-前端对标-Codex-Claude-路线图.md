# Studio 前端对标 Codex / Claude Code 路线图

> 来源：多智能体 design workflow（understand → 3 方向 design → synthesize，8 agents）。
> 方向定调（用户 2026-06-28）：后端是内核（已证明可用），**前端才是交互**；UI 比命令行更适合
> 大众，命令行适合专业开发者；接轨市场是常见做法。前端要**对标当前最火的 Codex 与 Claude Code**
> ——它们是行业最优秀的产品设计者。

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
| 3 | 内联折叠工具卡（tool_use↔tool_result，展开进 Inspector） | `LiveStream.tsx` + 新 ToolCallCard | CC/Codex 工具披露 | 排队 |
| 4 | **loop-health 面板**：在 Inspector RunStatusPanel 露出 `loop_quality` SLO（warn/severity/窗口/reason） | `EvidenceExplorer.tsx` | Codex/CC 按需深证据 | ✅ 已落地 |
| 5 | 工作区 diff 评审作为主线 gate（chip→同 Inspector diff scope，Accept 前只读评审） | `ConversationTurn.tsx` ↔ `DiffReviewPane.tsx` | Codex diff/approve | 排队 |
| 6 | 跟随相关 turn 的逐事件建议动作 chip（非顶部固定） | `ConversationTurn.tsx` / `RuntimeSnapshot.tsx` | CC 内联建议 | 排队 |
| 7 | 校验结果矩阵（结构化 pass/fail，替换 `<pre>` dump） | `EvidenceExplorer.tsx` | 信任可扫读 | 排队 |
| 8 | Runtime 背书的 approve/accept gate（提升权限预览保真，绝不伪造完成） | `RuntimeSnapshot.tsx` / `PermissionCard.tsx` | Codex approve | 排队 |

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
