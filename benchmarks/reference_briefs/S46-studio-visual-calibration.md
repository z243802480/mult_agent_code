# Slice S46 — Studio 视觉校准与信息架构

更新时间：2026-06-06  
状态：**已完成 · Wave 2**  
依赖：S45 Claude Code parity、Focus Layout（S45-F）

## 1. 对标结论（2026-06 调研）

### Claude Code Desktop（2026-04 重构）

| 机制 | 用户心流作用 | Asteria 差距 |
| --- | --- | --- |
| **Pane 即视图** | Chat / Diff / Terminal 各自独立，用户只打开需要的 | 右栏一次性堆叠 Diff+Context+Ops+Evidence+Routes+Files |
| **Ctrl+\\ 关 pane** | 对话可占满屏 | ✅ 已有 panel 折叠 |
| **Diff 左文件右内容** | 单一任务：审改动 | 文件列表与 preview 分离、Files 区重复 |
| **+12 -1 点进 diff** | Thread 只留一个入口 | Thread 同时有 aggregate chip、file chips、Tn diff 按钮 |
| **Verbose / Normal / Summary** | 过程信息分级 | 无视图模式，maintainer 与用户 UI 混在一起 |
| **Side chat (Ctrl+;)** | 主线程不被打断 | defer |
| **Session 侧栏过滤/分组** | 多任务不晕 | 仅有扁平列表 |

### Codex TUI / IDE

| 机制 | 用户心流作用 | Asteria 差距 |
| --- | --- | --- |
| **HistoryCell 提交后折叠** | 过程变一行摘要 | TurnMiddle 可展开但 chip 仍偏多 |
| **BottomPane 单一输入区** | 输入+状态在一带 | Composer 模式/权限仍占第二行 |
| **Status line 一行** | 模型/策略不占主区 | 顶栏 + phase dots + runtime banner 叠加 |
| **Clamped tool output** | 输出默认可扫读 | ✅ ClampedOutput（S45-F2） |
| **Transcript overlay (Ctrl+T)** | 全历史按需打开 | Inspector 默认暴露 raw evidence |

### 根因：「乱」从哪来

1. **双轨 UI 未分离**：用户叙事（Goal→Reply→Diff）与 maintainer 观测（Evidence/Routes/Gates）同屏竞争。
2. **右栏信息层级扁平**：10+ section 纵向堆叠，无 primary/secondary。
3. **Thread 控件重复**：同一轮改动有 3 种入口（chips / aggregate / Tn diff）。
4. **视觉 dialect 过多**：opsIntro 渐变、debug 卡片、event 卡片、git 面板各自一套边框/间距。
5. **缺少默认 Focus 态**：新用户打开即「开发者控制台」而非「对话 + 改动审查」。

## 2. 设计原则（校准后）

```text
默认 Focus：对话 + 改动 + 必要 action；其余进 Advanced。
单一入口：Thread 每轮改动 → 一个 aggregate chip → 右栏 Diff。
Pane 分层：Primary（Changes + Context） / Advanced（Evidence & Debug）。
视图三档：Focus · Normal · Verbose（localStorage 记忆）。
```

## 3. Wave 计划

| ID | 交付 | green_checks |
| --- | --- | --- |
| **S46a** | `useViewMode` + 顶栏 Focus/Normal/Verbose 切换 | build · homepage smoke |
| **S46b** | Inspector Primary（Diff+Preview+Context）/ Advanced `<details>` | manual · s45-parity |
| **S46c** | Thread Focus：隐藏 process 控件、合并 file 入口 | build |
| **S46d** | Design tokens（surface/text/border/radius） | build |
| **S46e** | 调研 brief + 计划文档更新 | ✅ |
| **S46f** | Diff Focus（Ctrl+Shift+D）+ 模块化拆分 + LiveStream 降噪 | build · smoke |
| **S47** | Session 侧栏 All/Recent + 日期分组 | → [`S47-studio-session-sidebar.md`](S47-studio-session-sidebar.md) |
| defer | Side chat、Pane drag-drop | RFC |

## 5. 模块结构（Wave 2）

```text
studio/src/
├── hooks/              useViewMode, useDiffFocus, usePaneLayout, useStudioKeyboard
├── session/            useStudioBootstrap, useSessionEvents, useRunEvidence, useWorkspaceReview
├── layout/             MissionPaneHeader
├── features/thread/    Thread, LiveStream, ConversationTurn, RuntimeSnapshot, runtimeNarrative
└── features/inspector/ Inspector, InspectorAdvanced, EvidenceExplorer, DiffPreviewSection
```

## 6. 验收清单

- [x] 默认 Focus 下右栏仅 Changes + Context（Advanced 折叠）
- [x] Thread 每轮最多 1 个 diff 入口（aggregate chip；Focus 隐藏 process badge / file chips / Tn 按钮）
- [x] 顶栏可切换 Verbose 恢复 maintainer 面板
- [x] Diff Focus（Ctrl+Shift+D）自动展开右栏并加宽
- [x] npm run build + homepage-copy-smoke + s45-parity-smoke
