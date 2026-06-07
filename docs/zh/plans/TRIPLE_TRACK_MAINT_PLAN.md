# 三线并行维护计划（Maint-F2+Triple）

更新时间：2026-06-06  
状态：**active**  
全局入口：[`当前状态与路线.md`](../当前状态与路线.md) §4 · [`研发总计划.md`](../研发总计划.md) §16

---

## 1. 为什么三线并行

F1 Studio 对标已签字；**不能**只等内测反馈空转。三条轨道 **同时推进、独立验收**，Studio 新 feature 仍受 F2 friction 规则约束。

```text
轨道 F2  内测反馈（其他 session 归档 trial）     → friction top 桶 → 有条件 Studio slice
轨道 H   Harness 可靠性（ACTIVE_SLICE S55）      → decide/debug/repair ↓
轨道 P   Beta 任务包 + 分发（S56）               → doc_update / wheel 可重复
轨道 A   稳态 gate（ongoing）                    → steady_iteration · pytest · 三源
```

**一条命令看三线脉搏**：

```powershell
python scripts/triple_track_pulse.py --root . --skip-b6
```

---

## 2. 轨道职责

| 轨道 | Slice | 负责人 | 产出 | 不等谁 |
| --- | --- | --- | --- | --- |
| **F2** | S54 ongoing | 产品/维护者 + VM | `S14-beta-user-trial-*.md` · friction 汇总 | — |
| **H** | **S57** | Agent 研发 | accept 回归 · B6 复验 | F2 |
| **P** | **S56** | Agent 研发 | `beta_task_pack_check.py` · 任务 2 材料齐 | F2 |
| **A** | — | 每会话 | doc contracts · wheel smoke | — |

---

## 3. 轨道 H（S55）— Harness friction II

| # | 工作 | 成功标准 |
| --- | --- | --- |
| H1 | Studio 决策卡引导 | runtime_request → Review contract 文案 + 自动 resume（已有 server 链，补 UI hint） |
| H2 | repair 可观测 | status / Thread 对 repair 循环有可读 next step |
| H3 | B6 重复性 | `small_code_change` 3 次抽样 · friction ≤ gate |

Brief：[`S55-harness-friction-ii.md`](../../benchmarks/reference_briefs/S55-harness-friction-ii.md)

---

## 4. 轨道 P（S56）— Beta 任务包

| # | 工作 | 成功标准 |
| --- | --- | --- |
| P1 | 任务包契约 | `beta_user_tasks.json` + 入门/清单交叉引用 |
| P2 | doc_update 路径 | `s16_doc_update_dogfood.py` 可维护者复跑 |
| P3 | wheel | `s15_wheel_install_smoke.py` 纳入 pack check |

Brief：[`S56-beta-task-pack-pulse.md`](../../benchmarks/reference_briefs/S56-beta-task-pack-pulse.md)

---

## 5. 轨道 F2 — 内测（并行输入）

维护者 / VM 试跑后归档 trial；Agent 在其他 session 消费反馈：

```powershell
python scripts/beta_friction_aggregate.py --root . --markdown
```

**规则**：Studio 下一刀 **仅** 当 top 桶有分 **或** Harness P0 死循环。

---

## 6. 渐进放开（2026-06-07）

在 **F2 friction 仍管 Studio 新面板** 前提下，以下 harness 向改进 **不再等待内测**：

| 类别 | 示例 | 轨道 |
| --- | --- | --- |
| 决策链 UX | decisionGuidance · status blocker 文案 | H |
| scope 自动放行 | benign `tests/test_*.py` | H |
| 脉搏脚本 | triple_track · harness_repeatability · pack check | H/P/A |
| Beta 任务 2/3 | doc_update dogfood（`--with-doc-dogfood`） | P |

**仍冻结**：North Star silent execute · 蜂群默认开 · worktree · Terminal/Settings 全面板

---

## 7. 相关文档

- F2 收尾：[`STUDIO_PARITY_CLOSURE_PLAN.md`](./STUDIO_PARITY_CLOSURE_PLAN.md)
- 稳态节奏：[`稳态迭代节奏.md`](../稳态迭代节奏.md)
- S54 基线：[`S54-f2-friction-baseline-20260606.md`](../reports/S54-f2-friction-baseline-20260606.md)
