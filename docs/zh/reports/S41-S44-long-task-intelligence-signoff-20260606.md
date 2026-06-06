# Phase 8 Long Task Intelligence（S41–S44）— Band Signoff 2026-06-06

## 目标

闭合 Phase 8 **长任务智能** 波段：completion judge · handoff compact · remote background stub · maintainer pulse。

## 交付

| Slice | 交付 | 闸门 |
| --- | --- | --- |
| S41 | ML slice completion judge | `phase8a_*` |
| S42 | Long horizon handoff compact | `phase8b_*` |
| S43 | Remote background adapter (stub) | `phase8c_*` |
| S44 | Band signoff + smoke | `phase8_long_task_intelligence_gate.json` |

## 框架

[`LONG_TASK_GOAL_FRAMEWORK.md`](../plans/LONG_TASK_GOAL_FRAMEWORK.md)

## green_checks

```powershell
python scripts/phase8_maintainer_smoke.py --root .
pytest -q
```

## 仍 defer

- 真 cloud VM 编排
- 每 turn completion evaluator（非 accept 后）

## 纪律

- North Star 不 silent auto execute
- DO_NOT_TOUCH execute/run 大 refactor
