# Studio × Claude Code 体验对标计划

更新时间：2026-06-06  
**执行 brief**：[`benchmarks/reference_briefs/S45-studio-claude-code-parity.md`](../../benchmarks/reference_briefs/S45-studio-claude-code-parity.md)

---

## 为什么要对标

Beta 内测反馈集中在三条：**改完代码看不清 diff**、**长会话不知道 context 剩多少**、**多任务切换 session 不顺**。Claude Code 在这三块已有成熟模式，Asteria 应学机制、落到 `user_progress` 契约上，而不是再造一套 runtime。

---

## 四块对标地图

### 1. Git Diff（P0）

| Claude Code | 我们已有 | 下一刀 |
| --- | --- | --- |
| `/diff` Current（工作区 vs HEAD） | Inspector **Current** tab + git API | staged/unstaged 分栏 |
| Per-Turn T1/T2（来自 tool 记录） | **Tn** tab + Thread chip | **T1=最新一轮**排序 |
| 行号 + 语法色 | unified text `<pre>` | **DiffPreview** 组件 |
| Side-by-side | 无 | 只读 toggle（S45c） |
| Accept/Reject | 无（整 run accept） | 单文件 hook + policy（S45f） |

### 2. 主对话区（P1）

| Claude Code | 我们已有 | 下一刀 |
| --- | --- | --- |
| 折叠 tool / 清晰 final | LiveStream → TurnMiddle → TurnFinal | Markdown 渲染 |
| diff stats `+12 -1` | 单文件 chip | turn 级 aggregate chip |
| Side question | 无 | Composer side-ask 模式 |
| `/rewind` | runtime resume/replan | Turn 级 rewind 入口 |

### 3. Session 切换（P1）

| Claude Code | 我们已有 | 下一刀 |
| --- | --- | --- |
| 侧栏 session 列表 | Sidebar sessions | 元数据行（goal 预览） |
| Ctrl+Tab 轮换 | 无 | 键盘快捷键 |
| 并行 + worktree | 单 workspace 切换 | **defer** RFC |
| 每 session 独立 cwd | workspace switcher | session 绑定 workspace 记忆 |

### 4. Context 分类（P1）

| Claude Code | 我们已有 | 下一刀 |
| --- | --- | --- |
| `/context` 全分类 | Inspector 简版 + Thread popover | Thread 完整 breakdown |
| MCP / tools / files 分行 | `context_sections` schema | 分类标签对齐 CC |
| 压力警告 | popover 内 ratio | Thread 常驻 warn 条 |
| `/compact` | runtime 支持 | Studio 按钮 + 确认 |

---

## 当前进度（滚动更新）

| Wave | 状态 | 说明 |
| --- | --- | --- |
| A0 基础 | ✅ | workspace switcher、git status/diff、Tn tab、file chips |
| **A1 S45a** | ✅ | DiffPreview 行号着色；Tn **最新优先** |
| **A2–A5** | ✅ | staged/unstaged、split、aggregate chip、stage/discard |
| **B1 S45g/h** | ✅ | Markdown TurnFinal + model 元数据 |
| **C1 S45l–o** | ✅ | Ctrl+Tab、rename、goal 预览、ui_state |
| **D1 S45q–u** | ✅ | Context 分类 + 压力条 + Compact |
| defer | 📋 | side ask (S45j)、worktree (S45p) |

---

## 验证

```powershell
python scripts/beta_trial_smoke.py --root .
cd studio && npm run build
node studio/scripts/git-changes-smoke.mjs
node studio/scripts/turn-diff-scope-smoke.mjs
```

---

## 相关文档

- Studio 功能表：[`studio/README.md`](../../studio/README.md)
- Beta 试跑：[`Beta试跑清单.md`](../Beta试跑清单.md)
- 稳态节奏：[`稳态迭代节奏.md`](../稳态迭代节奏.md)
