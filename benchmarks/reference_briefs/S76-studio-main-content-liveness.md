# S76 — Studio 主内容区「活起来」里程碑（流式诚实 + 过程可见 + 长任务不崩前置）

- ACTIVE_PHASE：Post-S73 Beta convergence · ACTIVE_SLICE：S76（承接 S75）
- 触发（真实 friction · 逐字）：用户在真跑一个贪吃蛇任务后：「前面 thinking 了半天，没崩一个字。到最后了弹了一个 review 啥的。你到底是不是大模型驱动的循环。怎么感觉还是状态机那一套」；随后：「流式渲染肯定要做。但前端主窗口可不止是流渲染……主窗口内容区是需要详细的做设计的……长任务下前端打开随时不崩溃。session 还能备份和还原。」
- 用户拍板（AskUserQuestion）：起步范围 = **P1+P1b+P2 一个「活起来」里程碑**；完成后思考默认 = **折叠成「思考 Xs」可展开芯片**。

## 1. 事实基线（3 路 workflow 审计 + 本人复核，非猜测）

后端**是真·大模型循环**:真调用 minimax/glm，产出可玩 `snake-game.html`,`user_progress.jsonl` 有 96 个真 token delta（含 `<think>`）。观感崩在**前端主内容区渲染选择**:

- **主根因 · coarse 回退**：[Thread.tsx:68-72](../../studio/src/features/thread/Thread.tsx) 在 `mainEvents` 非空但其 `run_id` 不匹配 `runDetail.run_id` 时,改渲染 `runtimeSessionEvents`(粗事件);而 [runtimeNarrative.ts:94](../../studio/src/features/thread/runtimeNarrative.ts) `if (!event.transcript_kind) return null` **丢掉所有 token delta**,只留「Thinking/Planning/Checking the work」标签 + final → 正是「没一个字然后弹 review」。
- **次因 · 完成即删思考**：[ConversationTurn.tsx:213-216](../../studio/src/features/thread/ConversationTurn.tsx) `hideCompletedModelStream` 在 final_answer 落地瞬间把思考步从主区外科式移除,塞进默认折叠的 `TurnMiddle`「Ran N」徽章。
- **过程内容折叠**：完成后 tool/diff/plan 全进 `TurnMiddle` 关闭态,主区只剩结论卡。
- **linkage bug**：`session.json`（[server.mjs createSession](../../studio/server.mjs)）不存 run_id/status → sessions 列表元数据 null,且喂饱上面的 coarse 回退误判。

## 2. 里程碑范围（本切片做的）

| 修 | 目标 | 文件 | 触 DO_NOT_TOUCH |
|---|---|---|---|
| **A 选择优先自有富事件** | 会话有自己的富事件（model/tool/final）时优先渲染,不因 run_id 不匹配退化为 coarse；保留「空会话=空」「不渲染他会话的 run」两条既有护栏 | Thread.tsx | 否 |
| **B 思考常驻芯片** | 停删思考流 → 完成后折成「思考 Xs」可原地展开芯片；chat 阶段思考==final 仍去重不双显；`<think>` 清洗 | ConversationTurn.tsx / turnHelpers.ts / 新 ThinkingBlock | 否 |
| **C 过程卡常驻** | 完成后工具卡/diff/plan 作为可见块常驻主区（非仅 collapsed 徽章）；诚实错误卡 | ConversationTurn.tsx / LiveStream 复用 | 否 |
| **D linkage + 乱码** | 会话事件/`session.json` 落 run_id + status（修 sessions null）；中文乱码根因定位（子进程 argv/env 或写 sink 编码；server 读写已 utf8）与修复或诚实标注 | server.mjs | 否 |

## 3. 冻结/边界对齐

- 全部落在 Studio 前端 + server.mjs（**非** DO_NOT_TOUCH:execute/run/gate/acceptance 未触）。
- 冻结「无真实 friction 证据的 Studio 新功能」→ 本切片有用户直接 friction 证据,且属**诚实化+既有数据可见化**（复用 ToolCallCard/FileChangeChips/AggregateDiffChip/EventCard 折叠）为主,新增仅 ThinkingBlock/ErrorCard 两个薄壳,不新增运行时能力,不 fabricate。
- 诚实第一:不显示未发生的状态/token;`思考 Xs` 用真事件时间戳,token 数仅在有真 telemetry 时显示。

## 4. 后续（本切片不做,已与用户对齐分阶段）

P3 长任务加固（滑窗+虚拟化+memo+尾读懒加载）、P4 SSE 重连回填、P5 备份/还原、P6 context 表+stop/追问。虚拟化库、备份格式等岔口到对应阶段再定。

## 5. 完成标准（DoD）

真跑一个 run,主对话区**逐字流出**模型输出;完成后**留下**可展开思考芯片 + 常驻工具/diff/plan 卡 + 诚实结论(done≠verified);sessions 列表不再 null;`studio tsc/build` 绿 + preview live 冒烟确认流式可见。遵守 [[keep-docs-aligned-no-drift]]、[[convergence-direction]]、[[truly-complete-system-goal]]。
