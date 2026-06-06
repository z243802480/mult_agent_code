# Slice S45 — Studio × Claude Code 体验对标

更新时间：2026-06-06  
状态：**已交付 · 2026-06-06**  
依赖：S14–S15 Beta 路径、Workspace switcher、Diff review 初版（2026-06）

## 1. 对标原则

```text
学机制，不抄形态；学结论，不抄专有实现。
Studio 仍是 Runtime 的「用户叙事客户端」，不是第二套 agent runtime。
```

| Claude Code 能力 | Asteria 映射策略 |
| --- | --- |
| CLI `/diff`、Desktop diff pane | Inspector **Diff review** + Thread file chips |
| Per-turn 来自 tool 记录 | `user_progress` 的 `file_changes` / `file_changed`（非纯 git） |
| `/context` 分类占用 | `runtime_progress.cost` 的 `context_sections` 投影 |
| 并行 session + worktree | **defer**：需 harness git worktree 策略；先做 session UX |
| Accept/reject 单文件 | 需 `runtime_policy` + promotion 链；Phase 2 稳态后接 |

**竞品参考（2026-06）**

- [Claude Code `/diff`](https://blog.vincentqiao.com/en/posts/claude-code-diff/) — Current vs Per-Turn、最新消息优先
- [Claude Code Desktop](https://code.claude.com/docs/en/desktop) — 并行 session、可视化 diff、pane 布局
- [Diff viewer 对比](https://www.lotharschulz.info/2026/04/17/claude-code-desktop-diff-viewer-vs-claude-code-cli-vs-git-diff-a-hands-on-comparison/) — side-by-side、行号、语法高亮

---

## 2. 现状快照（2026-06-06）

| 区域 | Claude Code | Asteria Studio | 差距 |
| --- | --- | --- | --- |
| **Git diff** | Current + T1/T2…、行号、高亮、side-by-side | Current + Tn tabs、unified text preview | 行号/高亮/并排、Tn 排序、staged 分栏 |
| **Per-turn diff 数据源** | FileEdit/FileWrite tool 记录 | events 聚合（✅ 方向对） | 与 git 状态混读时仍可能偏差 |
| **主对话 Thread** | 折叠 tool、diff stats chip、modal 顺序 | LiveStream + TurnMiddle + TurnFinal | 缺 aggregate diff chip、markdown 弱 |
| **Session 切换** | 侧栏列表、Ctrl+Tab、worktree 隔离 | 侧栏 create/switch/delete | 无快捷键、无 rename、无 session 元数据 |
| **Context 分类** | `/context` 全分类 + MCP/tools/files | Thread 底部 popover + Inspector 简版 | Thread 无完整 breakdown；无 MCP 行 |

---

## 3. 波段计划（S45a–S45f）

### Wave A — Git Diff 完善（**P0 · 先做**）

| ID | 交付 | CC 对标点 | green_checks |
| --- | --- | --- | --- |
| **S45a** | `DiffPreview`：unified diff 行号 + +/- 着色 | CLI diff TUI | `npm run build` · preview 快照 smoke |
| **S45b** | Staged / Unstaged 分栏（单文件） | `git diff` vs `git diff --cached` | `git-changes-smoke.mjs` 扩展 |
| **S45c** | Side-by-side 切换（同文件） | Desktop diff pane | 手工 demo + smoke 契约 |
| **S45d** | Turn tab **最新优先**（T1=最近一轮） | `/diff` Per-Turn 排序 | `turn-diff-scope-smoke.mjs` |
| **S45e** | Thread 顶/turn 级 **aggregate diff chip**（+N -M） | Desktop `+12 -1` 指示器 | Thread smoke |
| **S45f** | Accept/Reject 单文件（只读 preview → policy hook） | CLI `y/n/e` | runtime_policy 测试 + Studio smoke |

**非 git 工作区**：Turn scope 仍走 event 文件列表 + `previewFile`；Current 显示「无 git」说明。

### Wave B — 主对话区（**P1**）

| ID | 交付 | CC 对标点 |
| --- | --- | --- |
| **S45g** | TurnFinal **Markdown 渲染**（标题/列表/代码块） | Desktop 回复区 |
| **S45h** | 回复卡 **model + token 元数据**（provider/model/latency） | CLI 会话元信息 |
| **S45i** | Tool 输出 **行内可展开**（stdout 限高 + copy） | CLI tool 结果 code block |
| **S45j** | **Side ask**：Composer 子模式「附带 context 但不新开 turn」 | Desktop side chat |
| **S45k** | Turn **rewind 入口**（链到 runtime resume/replan 决策） | `/rewind` |

### Wave C — Session 对话切换（**P1**）

| ID | 交付 | CC 对标点 |
| --- | --- | --- |
| **S45l** | **Ctrl+Tab / Ctrl+Shift+Tab** 切换 session | Desktop 快捷键 |
| **S45m** | Session **重命名** + 自动生成标题（首条 goal 摘要） | 侧栏 session 标题 |
| **S45n** | Session 行展示：**workspace 名 · 最后 goal 预览 · live 徽章** | Desktop 并行 session 列表 |
| **S45o** | 切换 session 时 **保留 Inspector diff scope**（按 session 记忆） | 多 session 不串状态 |
| **S45p** | Git worktree 并行 session | Desktop worktree 隔离 — **defer RFC** |

### Wave D — Context 分类查看（**P1**）

| ID | 交付 | CC 对标点 |
| --- | --- | --- |
| **S45q** | Thread **Context 面板**完整 breakdown（与 Inspector 同源） | `/context` |
| **S45r** | 分类：**System / Messages / Tools / Files / MCP / Free** | CC context 维度 |
| **S45s** | 点击分类 → Inspector 展开对应 evidence 列表 | 可 drill-down |
| **S45t** | **Compact** 操作入口（触发 runtime compact，带确认） | `/compact` |
| **S45u** | Context 压力 **≥0.75 警告条**（Thread 常驻，非仅 popover） | 预算护栏可视化 |

**数据真源**：`runDetail.runtime_progress.cost` · `latest_context_sections` · `context_window_ratio`（已有 schema，Studio 只投影）。

---

## 4. 实施顺序（推荐）

```text
S45a → S45b → S45d → S45e   # Git diff 闭环（2–3 会话）
S45q → S45r → S45u          # Context 可见（1–2 会话）
S45l → S45m → S45n          # Session UX（1 会话）
S45g → S45h                 # 主对话 polish（1 会话）
S45c, S45f, S45j, S45p      # 需 policy / 布局 / RFC，排后
```

维护者脉搏（每波结束）：

```powershell
python scripts/beta_trial_smoke.py --root .
npm run build --prefix studio
```

---

## 5. do_not_copy

- Claude Desktop 像素级 pane 拖拽布局
- 专有 worktree 路径 `/.claude/worktrees/`
- CLI TUI 键盘驱动 diff 导航（Web 用 click/scroll）
- 无 policy 的「一键 accept 写盘」

---

## 6. 文档同步

每完成一波，更新：

- `studio/README.md` § UI alignment 表
- `docs/zh/当前状态与路线.md` § 轨道 A′
- `docs/zh/Beta试跑清单.md`（若影响测试者路径）

---

## 7. 签字过门（S45 波段关闭）

- [x] Wave A green_checks 全绿
- [x] 至少 1 项 Wave B + 1 项 Wave C + 1 项 Wave D 交付
- [x] `beta_trial_smoke.py` 绿
- [ ] 维护者 5min demo：换 session → 看 context 分类 → T1 diff → staged 文件
