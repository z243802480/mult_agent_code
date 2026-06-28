# Studio IDE-shell 重设计方案

状态：`plan`（已定稿 · 用户决策已锁定 · 待实现启动）

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

### Phase B — IDE 骨架（结构，中风险；已按 Q1/Q3 定型）

| ID | 改动 | 主要文件 |
| --- | --- | --- |
| B1 | **持久全局头部行**：shell 改 `grid-template-rows: var(--header-height) 1fr`，头部横跨所有列；承载 project/branch 切换 + 运行/agent 状态；workspaceChip 上移；goal 回工作面顶 | `shell.css:1-14`、`MissionPaneHeader.tsx`、新建 header 组件、`layout.css:9-18`、`tokens.css` |
| B2 | **工作面满铺**：停止把 `.thread > *`/composer 居中到 `--thread-max`；左对齐填充列（仅 prose 块留可读 max）| `thread-shell.css:18-22`、`composer.css:13-19`、`useThreadColumnWidth.ts` |
| B3 | **评审/diff 升为对等面**：`PANEL_MAX 520→~50%vw`，加 `--panel-width-wide`；Diff/Review 改成真正分栏；**改动文件列表**进此面 | `usePaneLayout.ts:8`、`inspector-panel.css:118-131` |
| B4 | **头部控件按语义分两组**：左=面切换（Chat / Diff）、右=工具开关（panel/refresh/verbosity 收进 overflow）；视图切换合成一个 segmented | `MissionPaneHeader.tsx`、`inspector-panel.css` |
| B5 | composer 的 `<details>` 弹层 + 原生 `<select>` 换成**已存在但未用的 `.segmented`** 控件（mode）+ 小 segmented/ghost（permission）| `composer.css`（`.segmented` 已有）、`Composer.tsx` |

> 注：原"左栏文件树"(旧 B4) 已按 Q3 取消；项目切换并入 B1，改动文件并入 B3。

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
