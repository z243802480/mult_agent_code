# Slice S56 — Beta 任务包脉搏（轨道 P）

更新时间：2026-06-06  
状态：**进行中**  
依赖：S54 · S15  
计划：[`docs/zh/plans/TRIPLE_TRACK_MAINT_PLAN.md`](../../docs/zh/plans/TRIPLE_TRACK_MAINT_PLAN.md)

## 1. 目标

内测任务 1–3 在文档与脚本层 **可重复验证**，不依赖单次 maintainer 记忆。

| # | 交付 | 成功标准 |
| --- | --- | --- |
| P1 | `beta_task_pack_check.py` | 校验 `beta_user_tasks.json` + 入门/清单引用 |
| P2 | doc_update dogfood | `s16_doc_update_dogfood.py` 文档化于 pack check |
| P3 | wheel 路径 | s15 smoke 纳入 pack check |

## 2. green_checks

```powershell
python scripts/beta_task_pack_check.py --root .
python scripts/triple_track_pulse.py --root . --skip-b6
```

## 3. 验收

- [x] pack check 绿
- [x] Beta试跑清单 提及任务 2/3 可选路径
