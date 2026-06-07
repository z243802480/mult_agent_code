# Studio 对标收尾与内测闭环计划（Phase F）

更新时间：2026-06-06  
状态：**active · F1 已签字**  
前置：**S45–S53 已交付**  
**ACTIVE_SLICE**：**S56**（轨道 P）  
**并行**：F2/S54 · S55 ✅ — 见 [`TRIPLE_TRACK_MAINT_PLAN.md`](./TRIPLE_TRACK_MAINT_PLAN.md)

---

## 1. 评估结论（2026-06-06）

Beta 内测三条痛点与 Claude Code 对标状态：

| 痛点 | CC 参考机制 | Asteria 映射 | 完成度 |
| --- | --- | --- | --- |
| 改完看不清 diff | `/diff` + Desktop 双栏 | DiffReviewPane、Diff Focus、staged/split | **~95%** |
| 长会话不知 context 剩多少 | `/context` + 压力提示 | Thread/Inspector breakdown、压力条、Compact | **~90%** |
| 多任务 session 不顺 | 侧栏 + Ctrl+Tab | All/Recent 分组、rename、ui_state | **~80%** |

**结论**：Studio × CC **Beta 关键路径已对齐**；不宜继续无边界扩功能。下一波段目标：

```text
F1 收尾 polish（S51–S53）→ F2 内测闭环 → F3 harness 深集成（按需）
```

**原则**（与 [`AGENTS.md`](../../AGENTS.md) 一致）：

- Studio 仍是 runtime 的**用户叙事客户端**，不造第二 loop  
- 学 CC **机制**，不抄 Desktop **形态**  
- 新 Studio surface 需 brief + smoke；无 friction 证据不开 F3  

---

## 2. 对标总表（四块 · 实况）

### 2.1 Git Diff（P0）

| CC | 状态 | 证据 |
| --- | --- | --- |
| Current + Tn scope | ✅ | S45a–d、S48 |
| 行号 / 着色 / split | ✅ | DiffPreview |
| staged / unstaged | ✅ | S45b |
| aggregate `+N -M` | ✅ | S45e |
| stage / discard | ✅ | S45f（git 层） |
| 左文件右内容 | ✅ | S48 |
| policy 级单文件 accept | 📋 defer | 需 promotion 链 |

### 2.2 主对话（P1）

| CC | 状态 | 证据 |
| --- | --- | --- |
| 折叠 process + Markdown final | ✅ | S45g、S46c |
| model 元数据 | ✅ | S45h |
| side question | ✅ | S49、S50 |
| tool 输出限高 + copy | ✅ | S52 |
| `/rewind` | ✅ | S51 |

### 2.3 Session（P1）

| CC | 状态 | 证据 |
| --- | --- | --- |
| 侧栏 + 分组 | ✅ | S47 |
| Ctrl+Tab | ✅ | S45l |
| rename + goal 预览 | ✅ | S45m–n |
| ui_state 记忆 | ✅ | S45o |
| worktree 并行 | 📋 defer RFC | S45p |

### 2.4 Context（P1）

| CC | 状态 | 证据 |
| --- | --- | --- |
| 分类 breakdown | ✅ | S45q–r |
| drill-down | ✅ | S45s |
| Compact | ✅ | S45t |
| 压力警告条 | ✅ | S45u |

### 2.5 信息架构（S46–S50）

| CC | 状态 | 证据 |
| --- | --- | --- |
| Focus / Normal / Verbose | ✅ | S46a |
| Inspector Primary / Advanced | ✅ | S46b |
| Diff Focus | ✅ | S46f |
| Side chat + Composer Quick ask | ✅ | S49、S50 |
| Pane drag-drop | 📋 defer | S46 遗留 |

---

## 3. Phase F 三阶段

```mermaid
flowchart LR
  F1[F1 收尾 S51-S53] --> F2[F2 内测闭环]
  F2 --> F3[F3 Harness 按需]
  F3 --> Maint[维护态]
```

### Phase F1 — 对标收尾 — **✅ 已签字**

| Slice | 交付 | Brief | 状态 |
| --- | --- | --- | --- |
| **S51** | Turn Rewind | [`S51-turn-rewind-entry.md`](../../benchmarks/reference_briefs/S51-turn-rewind-entry.md) | ✅ |
| **S52** | ClampedOutput | [`S52-tool-output-clamp.md`](../../benchmarks/reference_briefs/S52-tool-output-clamp.md) | ✅ |
| **S53** | 对标签字 + signoff | [`S53-studio-parity-signoff.md`](../../benchmarks/reference_briefs/S53-studio-parity-signoff.md) | ✅ |

**F1 过门**：[`S45-S50-studio-parity-signoff-20260606.md`](../reports/S45-S50-studio-parity-signoff-20260606.md) ✅

### Phase F2 — 内测闭环（**当前 · S54**）

| # | 工作 | 成功标准 |
| --- | --- | --- |
| F2-1 | Beta dogfood（5–10 人） | Goal→Review→Accept 全路径可走 |
| F2-2 | B6 + Studio 开着 diff/context | `small_code_change` ≥0.8；friction 可控 |
| F2-3 | 摩擦分桶 | `beta_friction_aggregate.py` 按 diff/context/session/side_ask |
| F2-4 | 试跑清单更新 | [`Beta试跑清单.md`](../Beta试跑清单.md) 含 S48–S52 步骤 |

**Brief**：[`S54-studio-f2-beta-baseline.md`](../../benchmarks/reference_briefs/S54-studio-f2-beta-baseline.md)  
**基线报告**：[`S54-f2-friction-baseline-20260606.md`](../reports/S54-f2-friction-baseline-20260606.md)（桶空 → **defer** 下一刀）

**F2 规则**：新 Studio feature **必须**对应 friction 桶 top 项；否则进 defer。

### 文档维护约定

代码或 Studio slice 合并后，**同一 PR/会话内**同步更新：`studio/README.md` · `STUDIO_CLAUDE_CODE_PARITY.md` · `当前状态与路线.md` §4；F1 签字后以 **friction 报告**驱动文档「下一刀」列，避免计划与实现漂移。

### Phase F3 — Harness 深集成（按需 · 非默认）

| 项 | 触发条件 | 产出 |
| --- | --- | --- |
| S45p Worktree | 并行改同一 repo 成高频诉求 | [`deferred/`](../deferred/) RFC + harness spike |
| Policy 单文件 accept | 用户要 promotion 级 accept | runtime_policy 测试 |
| North Star Studio 投影 | 长任务 UI 诉求 | goal queue / handoff 只读投影 |
| Terminal / Settings 面板 | 内测明确要求 | 独立 slice |

---

## 4. Defer 清单（冻结边界）

| ID | 内容 | 解除条件 |
| --- | --- | --- |
| S45p | Git worktree 并行 session | RFC + harness 策略签字 |
| Policy accept | 单文件 accept → promotion | runtime_policy slice |
| Pane drag-drop | 拖 pane 切视图 | F2 无 P0 friction 且有人力 |
| Terminal 面板 | README 🔲 | F2 需求票 |
| Settings UI | README 🔲 | F2 需求票 |
| CC 像素级布局 | — | **永不**（非目标） |

---

## 5. 验证 bundle

**每个 Studio Slice（S51+）**：

```powershell
cd studio && npm run build
node studio/scripts/s45-parity-smoke.mjs
node studio/scripts/turn-diff-scope-smoke.mjs
node studio/scripts/side-chat-smoke.mjs
node studio/scripts/composer-side-ask-smoke.mjs
node studio/scripts/homepage-copy-smoke.mjs
pytest tests/unit/test_documentation_contracts.py -q
```

**F1 签字前额外**：

```powershell
python scripts/beta_trial_smoke.py --root .
node studio/scripts/git-changes-smoke.mjs
```

**F2 周脉搏**（与轨道 A 合并）：

```powershell
python scripts/steady_iteration_check.py --root . --skip-b6
python scripts/beta_friction_aggregate.py --root .
```

---

## 6. 与主计划关系

| 层级 | 关系 |
| --- | --- |
| Phase 8 S41–S44 | ✅ 已闭合；Studio 只消费投影 |
| Phase 5 蜂群 | ✅ 已闭合；不扩 swarm UI |
| 轨道 A 稳态 | ongoing；F2 并行 |
| **轨道 F（本文）** | **Studio 对标维护态收尾 → 内测驱动** |

---

## 7. 相关文档

- 对标滚动表：[`STUDIO_CLAUDE_CODE_PARITY.md`](./STUDIO_CLAUDE_CODE_PARITY.md)
- S45 原始 brief：[`benchmarks/reference_briefs/S45-studio-claude-code-parity.md`](../../benchmarks/reference_briefs/S45-studio-claude-code-parity.md)
- Studio 功能表：[`studio/README.md`](../../studio/README.md)
- 稳态节奏：[`稳态迭代节奏.md`](../稳态迭代节奏.md)
