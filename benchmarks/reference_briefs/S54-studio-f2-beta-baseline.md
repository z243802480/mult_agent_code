# Slice S54 — F2 Beta friction 基线

更新时间：2026-06-06  
状态：**待执行**  
依赖：S53 parity signoff  
计划：[`docs/zh/plans/STUDIO_PARITY_CLOSURE_PLAN.md`](../../docs/zh/plans/STUDIO_PARITY_CLOSURE_PLAN.md) § Phase F2

## 1. 目标

F1 对标 band 已闭合；F2 不再默认加 Studio feature，用 **friction 数据**定下一刀。

| # | 工作 | 成功标准 |
| --- | --- | --- |
| F2-1 | Beta dogfood（5–10 人） | Goal→Review→Accept 全路径 |
| F2-2 | B6 + Studio diff/context 开着 | `small_code_change` ≥0.8 |
| F2-3 | 摩擦分桶 | `beta_friction_aggregate.py` 按 diff/context/session/side_ask |
| F2-4 | 试跑清单 | [`Beta试跑清单.md`](../../docs/zh/Beta试跑清单.md) 含 S48–S52 步骤 |

## 2. 验收

- [ ] friction 汇总报告（或空桶说明）
- [ ] 试跑清单更新
- [ ] 下一刀仅来自 friction top 项（否则 defer）
