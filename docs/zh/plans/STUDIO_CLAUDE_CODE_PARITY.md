# Studio × Claude Code 体验对标计划

更新时间：2026-06-06  
状态：**维护态收尾（Phase F1）**  
**执行计划**：[`STUDIO_PARITY_CLOSURE_PLAN.md`](./STUDIO_PARITY_CLOSURE_PLAN.md) · **ACTIVE_SLICE：S51**  
原始 brief：[`benchmarks/reference_briefs/S45-studio-claude-code-parity.md`](../../benchmarks/reference_briefs/S45-studio-claude-code-parity.md)

---

## 为什么要对标

Beta 内测反馈集中在三条：**改完代码看不清 diff**、**长会话不知道 context 剩多少**、**多任务切换 session 不顺**。Claude Code 在这三块已有成熟模式，Asteria 应学机制、落到 `user_progress` 契约上，而不是再造一套 runtime。

**2026-06-06 评估**：三条痛点 **已对齐 CC 机制**；本计划进入 **F1 收尾 → F2 内测** 阶段，见 [`STUDIO_PARITY_CLOSURE_PLAN.md`](./STUDIO_PARITY_CLOSURE_PLAN.md)。

---

## 四块对标地图（实况）

### 1. Git Diff（P0）— ✅ 维护态

| Claude Code | Asteria | 状态 |
| --- | --- | --- |
| `/diff` Current | Inspector Current + git API | ✅ |
| Per-Turn T1/T2 | Tn tab + Thread chip（T1=最新） | ✅ |
| 行号 + 语法色 | DiffPreview | ✅ |
| Side-by-side | Unified / Split toggle | ✅ |
| Staged / Unstaged | diff stage tabs | ✅ |
| 左文件右内容 | DiffReviewPane（S48） | ✅ |
| Accept/Reject（promotion） | git stage/discard | ✅ git 层 · 📋 policy 级 defer |

### 2. 主对话区（P1）— F1 收尾

| Claude Code | Asteria | 状态 |
| --- | --- | --- |
| 折叠 tool / 清晰 final | LiveStream → TurnFinal | ✅ |
| diff stats `+12 -1` | aggregate chip | ✅ |
| Side question | S49 Ctrl+; + S50 Composer Quick ask | ✅ |
| Tool 输出限高 + copy | — | 📋 **S52** |
| `/rewind` | — | 📋 **S51** |

### 3. Session 切换（P1）— ✅ 维护态

| Claude Code | Asteria | 状态 |
| --- | --- | --- |
| 侧栏 + 过滤分组 | All/Recent + 日期分组（S47） | ✅ |
| Ctrl+Tab | 快捷键 | ✅ |
| rename + goal 预览 | PATCH session | ✅ |
| ui_state 记忆 | diff scope per session | ✅ |
| 并行 + worktree | — | 📋 S45p RFC defer |

### 4. Context 分类（P1）— ✅ 维护态

| Claude Code | Asteria | 状态 |
| --- | --- | --- |
| `/context` breakdown | Thread + Inspector 同源 | ✅ |
| MCP / tools / files | context_sections | ✅ |
| 压力警告 | Thread 常驻 warn 条 | ✅ |
| `/compact` | Compact 按钮 + 确认 | ✅ |

---

## 波段进度（S45–S53）

| Wave | 状态 | 说明 |
| --- | --- | --- |
| A0 基础 | ✅ | workspace、git、Tn、file chips |
| A1–A5 S45a–f | ✅ | DiffPreview、staged、split、aggregate、stage/discard |
| B1 S45g/h | ✅ | Markdown + model 元数据 |
| B2 S49–S50 | ✅ | Side chat + Composer Quick ask |
| C1 S45l–o | ✅ | Ctrl+Tab、rename、ui_state |
| D1 S45q–u | ✅ | Context + Compact + 压力条 |
| E1 S46 | ✅ | Focus/Verbose、Inspector 分层、Diff Focus、模块化 |
| E2 S47 | ✅ | Session 侧栏分组 |
| E3 S48 | ✅ | Diff 左文件右内容 |
| **F1 S51–S53** | 🔄 | Rewind · Tool clamp · 对标签字 |
| **F2 内测闭环** | 📋 | dogfood · B6 · friction 分桶 |
| defer | 📋 | worktree、policy accept、pane drag-drop、Terminal、Settings |

---

## Phase F 摘要

详见 [`STUDIO_PARITY_CLOSURE_PLAN.md`](./STUDIO_PARITY_CLOSURE_PLAN.md)。

```text
F1（当前）S51 Rewind → S52 Tool clamp → S53 对标签字 + signoff
F2          Beta dogfood + friction 驱动下一刀
F3（按需）  worktree RFC · policy accept · 长任务 UI 投影
```

---

## 验证

```powershell
python scripts/beta_trial_smoke.py --root .
cd studio && npm run build
node studio/scripts/git-changes-smoke.mjs
node studio/scripts/turn-diff-scope-smoke.mjs
node studio/scripts/side-chat-smoke.mjs
node studio/scripts/composer-side-ask-smoke.mjs
pytest tests/unit/test_documentation_contracts.py -q
```

F1 完成后追加：`node studio/scripts/turn-rewind-smoke.mjs`（S51）

---

## 相关文档

- **收尾计划**：[`STUDIO_PARITY_CLOSURE_PLAN.md`](./STUDIO_PARITY_CLOSURE_PLAN.md)
- Studio 功能表：[`studio/README.md`](../../studio/README.md)
- Beta 试跑：[`Beta试跑清单.md`](../Beta试跑清单.md)
- 稳态节奏：[`稳态迭代节奏.md`](../稳态迭代节奏.md)
