# Studio IDE-shell 重设计方案

状态：`in-progress`（Phase A + Phase B 全量已落地并推送 · Phase C 收口待启动）

更新时间：2026-06-28

来源：design-review workflow（4 路并行审计 shell/IA · 视觉 · 排版密度 · 组件词汇 → 综合）。
配套真源：[Studio 交互界面工程设计](../Studio%20交互界面工程设计.md) · [前端对标路线图](./Studio-前端对标-Codex-Claude-路线图.md)。

> 本方案是「主线对话流已对标完成（CV-A…C）」之后的**下一层**：把承载对话的**外壳/布局/视觉语言**从「居中聊天仪表盘」改造成「agent IDE 工作区」。
> 用户 friction（2026-06-28）：「现在的风格和布局，跟主流的 codex/claude code 的 IDE 差距太大。」

## 0. 根因诊断（一句话）

Studio 当前是**按居中聊天产品布局+装饰的**，再把代码界面硬塞进去：唯一的头部漂浮在 768px 居中列内部、工作面是带空白边距的窄居中列、diff 是 300–520px 抽屉、满屏药丸+渐变头像+卡片套卡片、且**凡是 code/路径/命令/ID 的地方都没有 monospace**。骨架（surface 阶梯、单一 accent、diff 里已有的 mono 栈）是好的——所以这是纯 token+布局+CSS 工作，**不碰后端/runtime，也不动已完成的对话流诚实工作**。

## 1. 已锁定的方向决策（用户 2026-06-28）

| # | 决策 | 选择 | 含义 |
| --- | --- | --- | --- |
| Q1 布局 | **全幅 IDE 工作区 + 全局头部** | 工作面满铺无空白边距；全局头部横跨所有面板；diff 升为对等评审面 |
| Q2 品牌/头像 | **完全扁平化** | 删渐变圆头像→安静方形标记；删除 `--brand-gradient-*` token |
| Q3 左栏 | **左栏保持"会话列表"不变**（用户更正）| 项目/分支切换 → 移到**全局头部**；文件/改动 → 放到**评审/diff 面**（不在左栏做文件树）|
| Q4 时机 | **先敲定完整方案再动代码** | 本方案签字后才进入实现 |

> Q3 的更正很关键并优化了方案：Codex 左侧是 task/thread 列表、Claude Code 复用宿主 IDE 的树——**agent 产品左栏本就是对话**。故原审计里"把左栏改成文件树（effort L、风险最高）"一项**直接取消**，改为「项目切换进头部 + 改动文件进评审面」，既更对标又更省。

## 2. 目标信息架构（4 个区，IDE 骨架）

```text
┌─────────────────────────────────────────────────────────┐
│ 全局头部：project ▸ branch · 运行/agent 状态 · 视图切换    │  ← 新增，横跨全宽
├──────────┬───────────────────────────────┬──────────────┤
│ 会话栏    │   工作面（满铺、左对齐）          │ 评审/diff 面  │
│（保持：   │   对话流 / agent 输出即工作面      │（对等、加宽）  │
│  sessions │                               │  改动文件 +   │
│  + 健康）  │                               │  diff 在这里  │
└──────────┴───────────────────────────────┴──────────────┘
```

- **全局头部**（新增）：横跨全宽；承载 project/repo 切换 + branch + 运行/agent 状态 + 视图切换。不再把"goal 句子"当头部；goal 回到工作面顶部作为会话上下文。
- **会话栏**（保持语义）：sessions + 可选健康卡；仅做扁平化/密度收紧，**不**改成文件树。
- **工作面**（满铺）：去掉 `--thread-max` 居中与空白边距；对话/工作内容左对齐填充（仅 prose 块保留 ~70ch 可读测宽）。
- **评审/diff 面**（升级为对等）：`PANEL_MAX` 从 520 提到 ~视口 50%；Diff/Review 成为真正的分栏而非把工作面挤到 ~520px；**改动文件列表**落在这里（Codex/CC 的"另一个区域"）。

## 3. 实现阶段（全部纯前端 · token 优先）

### Phase A — 表层快赢（token + 少量组件，低风险，观感提升最大）

| ID | 改动 | 主要文件 | effort/风险 |
| --- | --- | --- | --- |
| A1 | 新增 `--font-mono` token + `--mono-xs/sm/base` 子阶；收编 diff 里两处硬编码 mono 栈 | `tokens.css`、`inspector-diff.css:136,385` | S / low |
| A2 | 把 mono 应用到所有"机器文本"：命令行、tool label/status、tool `<pre>`、行内 `<code>`、git 路径、`permissionScopeTags code`、evidence dump、workspaceChip——**模型 prose 仍用 Inter** | `thread-turn.css`、`inspector-evidence.css`、`components.css` 等 | M / low |
| A3 | 头像扁平化为安静方标；删除 `--brand-gradient-*` | `TurnFinal.tsx:21`、`thread-turn.css`、`Sidebar.tsx:66` | S / low |
| A4 | 去药丸：加 `--radius-control:6px`，收紧 `--radius-md 9→6`、`--radius-lg 14→10`，把约 7 处功能控件从 `--radius-pill` 换走（pill 仅留真正的圆点/live 徽章）| `tokens.css` + 约 7 处选择器 | S / low |
| A5 | 数字用 `font-variant-numeric: tabular-nums`（metric/计数/delta）| `tokens.css` 工具类 | S / low |
| A6 | 收掉装饰渐变：composer mode 渐变→扁平面+顶边色；蓝→红渐变 context 条→按阈值切换的纯 accent；对称聊天气泡圆角 | `composer.css`、`thread-turn.css` | S / low |
| A7 | 抬升只留给浮层：去掉 in-flow 卡片（`.turnUserBubble`/`.turnFinal`）的 box-shadow，菜单/弹层保留 | `thread-turn.css` | S / low |
| A8 | 微标签排版归一：`--label-size/-tracking/-weight`，9–10px 实例提到 11px | `tokens.css` + 标签处 | S / low |
| A9 | "New task" Sparkles→Plus；空状态改左对齐紧凑 ghost 行 | `Sidebar.tsx`、`EmptyState.tsx` | S / low |

> **状态左缘**（审计 Top #4）：把 `.signalCard`/`.narrativeStep`/`.eventCard`/`.metric`/`.runReport` 的整圈彩色边框→中性边框 + 2px `border-left` 着色（复用已存在的 `.vmRow` 模式）。归到 Phase A 尾（A10），干掉"红绿灯仪表盘"观感。

### Phase A — 实现前校准（audit 2026-06-29 · verdict: ready_with_corrections）

5 路并行 audit 对照真实代码逐条核验，结论：方案成立、可实现，下列校准已并入（实现以此为准）：

- **A1**：`--font-mono` 插在 `--leading`（tokens.css）之后，值与现有栈逐字一致：`ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`；收编的两处硬编码 mono 栈在 inspector-diff.css **136 / 385**（精确行，非「约」），子单元格继承、无需另改。
- **A2 纠偏**：命令行真源是 `.toolCardLabel`（thread-turn.css:464），`.commandLine` 是**死选择器**（零 TSX 引用），不动它。"evidence dump"实为 **6+ 个 `<pre>`**（evidenceBlock/detail/refList/preview/studioCrash/workerTopology/workflowMonitor/promotionPreview）。git 路径选择器：`.gitChangePath/.diffPreviewPath/.gitBranchLine`。**Prose 陷阱**：mono 只加到 `.turnFinalText code/pre` 后代，**绝不**加到 `.turnFinalText` 本体（否则模型 prose 也变 mono）；`.liveModelText/.chatStreamPreview/.deltaText/.messageText` 保持 Inter。`.toolCardStatus` 不做 mono（大写字距状态徽章，归 A8）。
- **A3 纠偏**：渐变在 **CSS thread-turn.css:804**（非 TurnFinal.tsx:21），全仓唯一消费者（3 次命中=2 定义+1 使用）。`Sidebar.tsx:66` 是折叠态品牌按钮、**不用**该 token、无需改。顺序：**先改头像（thread-turn）再删 token**，免悬空 var()。替换：`background → var(--surface-3)`、`border-radius 50% → var(--radius-sm)`、保留字形与 20px。
- **A4 纠偏 + 决策**：实为 **~13 个功能控件**（非 7）用 `--radius-pill`：composerModeSummary/modeGroup select/sideAskToggle/advancedModeDetails summary、turnDiffButton/turnRewindButton/suggestedActionChip、examplePrompts button、routePill、viewModeButton/debugAgentHints button、diffScopeTab。**保持 pill**（真圆点/live 徽章）：stepIcon(24px 真圆)、contextHealth/contextUsageBar、runtimeStatus、vmStatus、sessionLiveBadge、status、workerProgressTrack；borderline（workspaceChip/aggregateDiffChip/eventFacts span/**composerPermissionPill**）**默认保持 pill**。**token 决策**（避免三 token 撞 6px + ~50 callsite 涟漪）：新增 `--radius-control: 6px`；`--radius-lg 14→10`（收紧气泡，独立值）；**`--radius-md` 保持 9**（不降到 6）。
- **A5 纠偏**：直接在已知数字选择器的 CSS 规则上加 `font-variant-numeric: tabular-nums`（.liveFileDelta/.deltaAdd/.deltaDel/.diffScopeCount/.gitChangeDelta/.metric strong），并提供 `.tabular-nums` util；**不**改 TSX className（纯 CSS 落地）。
- **A6 纠偏**：context 条**只做扁平化**（thread-turn.css:211 渐变→`var(--accent)`）；阈值变色需 JS（ContextPanel 不发 health 类、那段 CSS 已死），不在纯 CSS Phase A 内。composer mode 渐变→`var(--surface-1)`+顶边色；扁平后 grep `--composer-auto-from/-tint-to/-sideask-from` 若 orphan 则删。
- **A7 决策（已签字）**：移除 `.turnUserBubble`/`.turnFinal` 的 in-flow `box-shadow`——**有意覆盖** 2 个 commit 前的 DS-3（`34825da`「depth polish」）：IDE 外壳原则是"抬升只给浮层"，in-flow 内容靠边框定义即可。**保留**浮层阴影（composer/contextWindowPanel/contextWindowTrigger/side-chat）。
- **A8 纠偏**：size→11px 只作用于 **5 个真·大写微标签**（toolCardStatus/sideTitle/sessionGroupLabel/permissionScopeGroup>small/vmStatus），用 `--label-size/-tracking/-weight`（canonical weight=700, tracking=0.04em）；**不**动数字 delta/计数/头像首字母/compact override。已是 11–12px 的标签（turnFinalLabel/livePhaseLabel）顺手 tokenize 以统一权重。
- **A9 纠偏**：`Plus` 未 import（须新增），`Sparkles` 出现 3 次：74 + 119 是 New task（换 Plus），**131 是健康卡图标（保留）**——不可盲目 find/replace。空状态真源是 thread-narrative.css:112（components.css 的同名块是死代码）。
- **A10 纠偏**：`.narrativeStep/.runReport` 基础边框在 **thread-shell.css:558**（非 thread-narrative）；镜像 `.vmRow`（inspector-evidence.css:698）的 `border + border-left:2px`。`.eventCard` **无 ok 态**：状态态(running/failed)与 model_delta 改 border-left，**`.selected` 保留整圈**（选中是 affordance，不是状态）。

> **气泡几何统一（A6 延伸决策）**：把所有会话面（turnUserBubble/turnWaiting/liveStream/chatStreamPreview/turnFinal）的「带尾巴」非对称圆角统一为对称 `var(--radius-lg)`，整体去掉聊天气泡观感（只改半径，低风险）。

### Phase A — 落地记录（2026-06-29 · 已实现于工作树，待提交）

按上述校准全量实现，纯 token + CSS + 2 处图标，未碰后端/runtime/schema：

- **tokens.css**：+`--font-mono`、+`--radius-control:6`、`--radius-lg 14→10`、+`--label-size/-tracking/-weight`、+`.tabular-nums` util；删 `--brand-gradient-*` 与已 orphan 的 `--composer-auto-from/-tint-to/-sideask-from`（`--user-bubble-bg` 仍被引用，保留）。
- **A1/A2 mono**：收编 inspector-diff 两处硬编码 mono 栈；mono 落到 toolCardLabel、tool `<pre>`、git 路径、permissionScopeTags code、6+ evidence/shell `<pre>`、workspaceChip、turnFinalText **code/pre 后代**（prose 本体保持 Inter）。
- **A3**：头像 → `surface-3` 方块（`radius-sm`），全仓 0 处 brand-gradient。
- **A4 de-pill**：13 功能控件 + 广义 `.topActions button`（原 `radius-md` 以更高特指度覆盖了 `.viewModeButton`，一并收成 `radius-control`，工具条半径统一 6px）→ `radius-control`；真圆点 / live 徽章 / track 保持 pill。
- **A5**：liveFileDelta / diffScopeCount / gitChangeDelta / metric strong 加 `tabular-nums`（纯 CSS，未改 TSX）。
- **A6**：context 条与 composer mode 渐变扁平化（顶边色保留）。
- **A7（签字覆盖 DS-3 `34825da`）**：移除 turnUserBubble / turnFinal in-flow 阴影；浮层阴影保留。会话面圆角统一对称 `radius-lg`。
- **A8**：5 微标签 + turnFinalLabel / livePhaseLabel / sideTitle / sessionGroupLabel 统一到 `--label-*`（11px / 700 / 0.04em）。
- **A9**：New task 图标 Sparkles→Plus（健康卡 Sparkles 保留）；空状态左对齐 ghost 列。
- **A10**：signalCard / metric / narrativeStep / runReport / eventCard 整圈彩边 → 中性边 + 2px 左缘着色（镜像 `.vmRow`）；eventCard `.selected` 保留整圈选中环（affordance 非状态）。

**验证**：`tsc --noEmit` + `vite build` 干净（1766 模块）；`session-main-path-contract` 绿；`styles/*.css`（除 tokens.css 定义）raw-hex 归零；无 orphan token；预览 reload 后计算样式核验（头像 6px 方块无渐变、工具条统一 6px、sideTitle 11/700、in-flow 无阴影、`--brand/-composer` token 已删）、console 0 错误。（`preview_screenshot` 因 Studio `setInterval` 重渲染挂起 → 既有现象，非回归；改用计算样式+console 取证。）

### Phase B — IDE 骨架（结构，中风险；已按 Q1/Q3 定型）

| ID | 改动 | 主要文件 |
| --- | --- | --- |
| B1 | **持久全局头部行**：shell 改 `grid-template-rows: var(--header-height) 1fr`，头部横跨所有列；承载 project/branch 切换 + 运行/agent 状态；workspaceChip 上移；goal 回工作面顶 | `shell.css:1-14`、`MissionPaneHeader.tsx`、新建 header 组件、`layout.css:9-18`、`tokens.css` |
| B2 | **工作面满铺**：停止把 `.thread > *`/composer 居中到 `--thread-max`；左对齐填充列（仅 prose 块留可读 max）| `thread-shell.css:18-22`、`composer.css:13-19`、`useThreadColumnWidth.ts` |
| B3 | **评审/diff 升为对等面**：`PANEL_MAX 520→~50%vw`，加 `--panel-width-wide`；Diff/Review 改成真正分栏；**改动文件列表**进此面 | `usePaneLayout.ts:8`、`inspector-panel.css:118-131` |
| B4 | **头部控件按语义分两组**：左=面切换（Chat / Diff）、右=工具开关（panel/refresh/verbosity 收进 overflow）；视图切换合成一个 segmented | `MissionPaneHeader.tsx`、`inspector-panel.css` |
| B5 | composer 的 `<details>` 弹层 + 原生 `<select>` 换成**已存在但未用的 `.segmented`** 控件（mode）+ 小 segmented/ghost（permission）| `composer.css`（`.segmented` 已有）、`Composer.tsx` |

> 注：原"左栏文件树"(旧 B4) 已按 Q3 取消；项目切换并入 B1，改动文件并入 B3。

### Phase B — 增量 1（B1+B2）落地记录（2026-06-29 · 已实现于工作树）

按 recon synthesis（`ready_with_notes`，4 路架构 map + 综合）实现「全局头部 + 全幅工作面」增量，纯 IA+token+CSS+轻组件组合，未碰后端/runtime/schema：

- **B1a 壳网格**：`.appShell` 加 `grid-template-rows: var(--header-height) 1fr`；`.appShell > *` 钉到 row 2、`.appShell > .globalHeader` 占 row 1 全宽（`grid-column:1/-1`）——按 universal/class 钉而非 nth-child，条件渲染的 splitter 不漏入头部行。
- **B1b 全局头部**：`MissionPaneHeader` 从 `.missionPane` 内提升为 `.appShell` 首个子节点；root class `topBar compact`→`globalHeader`，去掉 `align-self:center`+`max-width:var(--thread-max)`，改为全宽 flex + 底边发丝线 + `surface-0`；`--header-height` 从 min-height 升为精确行高（48px 容纳 title+chip+status+5 控件，已核）。退役全部 `.topBar*` 死规则。
- **B1c 运行状态**：头部加 `isRunning` pill（复用 `sessionEvents.isRunning`，无新 fetch/schema）。
- **B2 全幅工作面**：`.thread` 改 `align-items:stretch`（`.emptyThread` 仍 center 保留 hero）；拆分 `.thread>*` 与 `.emptyThread>*` 的 cap——thread 项 `max-width:none`，empty 项保留 cap；清掉 5 处 `--thread-max` cap（conversationTurn / threadProcessControls / runtimeSnapshot.compact / composer.compact / `.thread>*`）；删 JS 宽度驱动 `useThreadColumnWidth`（+ missionPaneRef + `--thread-max` 内联样式，hook 文件已删）；prose 可读性改由静态 70ch（turnFinalText 已有 + liveModelText + chatStream prose，`min(70ch,100%)` 无 margin auto → 左对齐）；contextWindowDock `right:356px`→`calc(var(--panel-width,320px)+var(--space-4))`。
- **响应式收口（recon Top 风险 #1/#5）**：@820 的 `grid-template-columns:1fr` 是死规则（被 @1240 的 `.appShell.panelOpen{…!important}` 以更高特指度压过），窄屏工作列被挤成 4px——改为匹配特指度的 `.appShell,.appShell.panelOpen,.appShell.panelCollapsed{1fr !important}` + 隐藏 sidebarSplitter，窄屏单列全幅修正。

**决策（已采纳推荐，尊重 freeze）**：①头部只放 session title + workspace chip + 运行状态，**不**引入持久 goal 句（goal 留在 thread）；②**branch 切换移出 Phase B**（payload 无 branch 字段，接它要动后端）。

**待 B3/B4/B5 决策**（不阻塞本增量）：③头部 view 控件 = Chat|Diff 真分栏 vs 现有 verbosity cycle；④评审面对等比例（~50vw + 工作列 min 360px 地板）；⑤composer 7 模式是否全做成 segmented 段（还是精简主集）。

**验证**：`tsc --noEmit`+`vite build` 干净（1765 模块）；`session-main-path-contract` 绿；预览计算样式核验——globalHeader 跨 1280 全宽 48px、grid-rows `48px 1fr`、工作列全幅（conversationTurn 710、maxW none）、prose 70ch（575px）、status pill "Running"、窄屏 768 单列全幅修正、console 0 错误。

### B3/B4/B5 决策（reference-first · 2026-06-29）

来源：3 路主流产品对标调研（header/view-switch · diff/review pane · composer modes，覆盖 Cursor / VS Code+Copilot / Claude Code / Codex / Windsurf / Zed / Cline）+ 综合。原则「学机制不抄形态」，严守 §4 冻结（纯 IA+token+CSS+轻组件，不碰后端/runtime/schema，复用 App scope 的 `gitStatus / files / isRunning / diffFocus`，左栏保持会话列表）。

**B4 头部视图控件 → 选 A（语义分两组），否决 Chat|Diff 二态 segmented。**
主流收敛：顶栏不是视图切换器——Cursor 已移除标题栏 agents/editor toggle，Copilot/Codex 把 mode 放在输入框旁；评审是「进入再离开的目的地」（Zed Review Changes、Codex/Cursor diffs view），不是常驻二态半屏；verbosity 控件极罕见且几乎不在头部（Claude Code 用 Ctrl+O 键盘切换）。**零产品**在顶栏放常驻 Chat|Diff segmented 或 3 态段按钮。
落地：头部 `.topActions` 分两组——左「面」组 = 单个 `Diff` 评审面 toggle（panel-toggle 语义 + 改动计数 badge，镜像 Zed/Cursor）；右「工具」组 = panel 显隐 / refresh / 保留的 verbosity cycle（+ Ask）。对话常驻，评审叠加进来。

**B3 评审/diff 面 → 选 A（聚焦评审时升为对等 ~50vw），抽屉降为静息态。**
主流收敛：改动文件列表贴近对话，但 diff 在「进入评审」时升为对等/主导面占主画布——Cursor/Copilot/Codex/Zed/JetBrains 一致；inline-in-chat 仅小改动 fallback，被诟病窄而无上下文（Cursor「panes I can't even see」）。
落地：静息 ~520px（预览 + 小改动 inline fallback）；聚焦评审（`diffFocus`）升为对等 `clamp(520px, 50vw, 960px)`，会话列保 360px 地板（可继续 steering）。改动文件列表落评审面 header（复用 App scope 的 files/gitStatus，无新 fetch）。

**B5 composer 模式 → 选 B（少量主模式 inline + overflow）+ 归类精简 7 模式。**
主流收敛：主模式只 2–3 个（Cursor/Copilot/Claude Code/Codex/Windsurf/Zed/Cline 全在此区间），控件是 dropdown/二态 toggle/键盘 cycle，**从不是全部模式的扁平多段行**；超 ~3 一律收进 overflow dropdown；autonomy/permission 是独立轴（Codex `/approvals`）。
落地：inline `.segmented` 只放 3 个意图主模式 **Chat / Plan / Run**（不换行）；`review / accept / resume` 是生命周期动作进 overflow `…` 菜单（同时满足「主线不暴露 maintainer 词汇」）；`permission`（auto-approve）作独立 footer 控件，不并入 mode。`onSend(message, mode, permission)` 字符串集合与签名零改动。

> 实施顺序：B4（头部分组+badge，最小）→ B3（对等评审面+改动文件入面）→ B5（composer 三段+overflow+permission 分离）；每项一组提交，过 tsc/build/契约/预览。

### Phase B — 增量 2/3（B3/B4/B5）落地记录（2026-06-29 · 已实现并推送）

按上述 reference-first 决策实现，纯前端、`onSend`/MODES/schema 零改动：

- **B4**（`3e4bde1`）：头部 `.topActions` 分两组——左 = 单 `Diff` 评审 toggle（带改动计数 badge），右 = 工具组（verbosity cycle + Ask + panel + refresh），发丝线分隔；放宽 `.globalHeader .topActions button`（`width:30px`→`min-width:30px;width:auto`）让带标签/badge 的按钮不被裁成方块。
- **B3**（`e3bc625`）：新增 `--panel-width-wide: clamp(520px,50vw,960px)`；`.appShell.diffFocus.panelOpen` grid 覆盖把评审面升为对等（实测 1440 视口下 720px = 50vw，会话列 492 > 360 地板），静息仍 ~520 抽屉；删除 grid 下本就 inert 的 `.missionPane/.inspector` flex 规则，保留 `.thread/.composer` opacity:0.92 评审弱化。
- **B5**（`e3e3c45`）：composer 模式从 7 项 `<details>` 弹层改为 inline `.segmented`（Auto/Chat/Plan/Goal 四意图）+ overflow `…`（Review/Resume/Accept 生命周期，同时把 maintainer 味动作移出主行）；permission 仍为独立 footer `<select>`；overflow summary 回显当前生命周期模式、选后自动收起。

验证：每项 `tsc`+`vite build` 干净、`session-main-path-contract` 绿、预览计算样式/交互核验、console 0 错误。**Phase B（IDE 骨架）全量完成**；剩 Phase C（原语统一 / 去卡片 / 密度收口）。

### Phase C — 收口打磨（一致性/密度/去死代码）

| ID | 改动 |
| --- | --- |
| C1 | 去嵌套卡片：内层容器（`inspectorDiffPreview`/`inspectorEventPeek`/`reportLead`/`reportSection`）透明无边；`surface-2` 填充只留给 hover/选中/可交互 |
| C2 | 栏/inspector chrome 扁平化为发丝线分节；卡片只留给真正抬升内容（decision/permission）|
| C3 | 降低逐行边框密度：一个有边框容器内的无边框行 + 发丝分隔/hover 填充；去冗余内部 `border-top` |
| C4 | 收紧工作面节奏：`--leading`/thread padding 向 IDE 密度靠（prose 仍 70ch）|
| C5 | 一个 `.btn` 原语（高 ~28–30px、`--radius-control`、weight 600 之外用 500/600 一致化）：`-primary`/`-ghost`/`-danger`；重构 `composerSend`/`permissionAllow/Deny`/`runtimeActionButton`/`topActions button`；折叠 `--action-solid-*` |
| C6 | 一个 `.badge` 状态原语（dot+label+tone）：tool 状态、runtime 状态、`<Status>`、`SignalCard` 头共用 |
| C7 | Permission/Decision 改成行内 notice：`surface-1` + 2px 左缘 accent（替代饱和填充）、收紧 padding、`--radius-control`、scope/code 用 mono |
| C8 | 编辑器级控件密度 token（~28px）替换头/栏里的 34px 药丸按钮 |

## 4. 冻结 / 边界（必须遵守）

**不得改**：
- **对话流诚实不变量**（刚发的 CV-A…C / narrative / recap 真实性）：可重新着色/重排，但**不改变 thread 声称发生了什么、不伪造/占位数据、不假完成**。
- **`tokens.css` 仍是单一设计真源**：新值（mono / radius-control / label / header-height / panel-width-wide / badge tones）全部进 token，无逐组件硬编码；并把现存两处硬编码 mono 栈收编。
- **不动后端/runtime/schema**：B3/B4 复用已传入 Inspector 的 `files`/`gitStatus`；纯 IA+token+CSS。遵守 master plan 冻结（无新编排 Wave / 全局 parallel_writes / 非 friction 驱动的新功能）与 DO_NOT_TOUCH（execute/run/gate/acceptance/real_model）。
- **不在主线暴露 maintainer gate 词汇**。

## 5. 验证口径（每个 Phase）

`tsc --noEmit` 干净 → `vite build` 干净 → 预览 reload 无 console 错误 → 相关 smoke（含 `session-main-path-contract.mjs`）绿 →（涉及主路径渲染时）`interactive-main-path.spec.mjs` 绿。
设计层附加：迁移后 `styles/*.css`（除 tokens.css 定义）raw hex 仍归零；预览 eval 抽查关键区域（头部存在、工作面满铺无 `--thread-max` 居中、mono 已应用、无渐变头像）。

## 6. 建议实施顺序

1. **Phase A 全量**（A1–A10）：一轮提交，预览验证——单这一轮就翻掉大部分"像网页"的信号。
2. **Phase B**（B1→B2→B3→B4→B5）：结构改造，分小步提交，每步过 smoke + 主路径 spec。
3. **Phase C**：原语统一 + 去卡片 + 密度收口。

每个 Phase 一组提交；涉及结构的 B 阶段按子项提交，便于回滚。文档随实现更新（路线图 + 本文 + 工程设计 §6）。
