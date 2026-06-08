# Slice S54 — F2 Beta friction 基线

更新时间：2026-06-06  
状态：**✅ 基线已交付 · F2 dogfood 待招募**  
依赖：S53 parity signoff  
计划：[`docs/zh/Asteria Studio 产品设计.md`](../../docs/zh/Asteria%20Studio%20产品设计.md) § Phase F2

## 1. 目标

F1 对标 band 已闭合；F2 不再默认加 Studio feature，用 **friction 数据**定下一刀。

| # | 工作 | 成功标准 |
| --- | --- | --- |
| F2-1 | Beta dogfood（5–10 人） | Goal→Review→Accept 全路径 |
| F2-2 | B6 + Studio diff/context 开着 | `small_code_change` ≥0.8 |
| F2-3 | 摩擦分桶 | `beta_friction_aggregate.py` 按 diff/context/session/side_ask |
| F2-4 | 试跑清单 | [`Beta试跑清单.md`](../../docs/zh/Beta试跑清单.md) 含 S48–S52 步骤 |

## 2. 验收

- [x] friction 汇总报告（或空桶说明）→ [`S54-f2-friction-baseline-20260606.md`](../../docs/zh/reports/S54-f2-friction-baseline-20260606.md)
- [x] 试跑清单更新（§D S48–S52）
- [x] 下一刀仅来自 friction top 项（当前 **defer**）
