# S54 F2 Beta friction 基线 — 2026-06-06

状态：**基线已建立 · 待真人 dogfood**  
计划：[`STUDIO_PARITY_CLOSURE_PLAN.md`](../plans/STUDIO_PARITY_CLOSURE_PLAN.md) § F2  
Brief：[`S54-studio-f2-beta-baseline.md`](../../benchmarks/reference_briefs/S54-studio-f2-beta-baseline.md)

---

## 交付摘要

| # | 工作 | 状态 | 证据 |
| --- | --- | --- | --- |
| F2-1 | Beta dogfood（5–10 人） | 📋 **待招募** | 材料：[`Beta试跑清单.md`](../Beta试跑清单.md)、[`Beta内测邀请.md`](../Beta内测邀请.md) |
| F2-2 | B6 + Studio diff/context | ✅ 工程路径 | S17 连续 2 绿；`b6-restricted-user-sim.mjs` |
| F2-3 | 摩擦分桶 | ✅ | `beta_friction_aggregate.py` → diff/context/session/side_ask/other |
| F2-4 | 试跑清单 S48–S52 | ✅ | 清单 §D spot-check + trial 模板 §5.1 |

---

## Friction 汇总（2026-06-06）

```powershell
python scripts/beta_friction_aggregate.py --root . --markdown
```

| 指标 | 值 |
| --- | --- |
| 试跑报告数 | 2（均为维护者 / 模拟，**非 B6 签字**） |
| 非维护者报告 | **0** |
| A/B/C 全通过 | 1（maintainer-smoke CLI 路径） |

### Studio friction 桶（当前）

| 桶 | 分数 | 说明 |
| --- | --- | --- |
| diff | 0 | 无真人 diff 摩擦记录 |
| context | 0 | |
| session | 0 | |
| side_ask | 0 | |
| other | 2 | maintainer-smoke：repair 偏多、文档偏差（非 Studio 桶） |

**Top bucket**：**(none)**  
**下一刀规则**：**defer** — 无 friction top 项；不开新 Studio feature，直至 ≥1 名非维护者试跑并填 §5.1 分桶。

---

## F2 下一刀（冻结至有数据）

```text
1. 招募 1 名非维护者按 Beta试跑清单 A–D 试跑
2. 归档 S14-beta-user-trial-<date>-<id>.md（含 Studio friction 行）
3. 重跑 beta_friction_aggregate.py；若 top_bucket 有值 → 开对应 brief
4. 否则继续 defer（worktree / Terminal / Settings 仍不进 F2）
```

---

## 验证（本 slice）

```powershell
pytest tests/unit/test_beta_friction_aggregate.py tests/unit/test_documentation_contracts.py -q
python scripts/beta_friction_aggregate.py --root .
python scripts/beta_trial_smoke.py --root .
```
