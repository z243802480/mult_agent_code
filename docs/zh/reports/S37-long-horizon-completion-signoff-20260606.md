# S37 Long Horizon Completion Contract — Signoff 2026-06-06

## 目标

闭合 Phase 6 **独立 slice 完成判定**：accept 后与 verify/review 分离的 completion evaluator，支撑长期 North Star 监督。

## 交付

| 项 | 证据 |
| --- | --- |
| `long_horizon_completion.py` | `evaluate_slice_completion` · `slice_completion_eval.json` |
| North Star 策略 | `slice_completion_policy`（含可选 `min_review_score`） |
| accept 收尾 | evaluator + user_progress「本 slice 完成判定」 |
| status 投影 | `long_horizon.last_slice_completion` |
| 闸门 | `phase6c_long_horizon_completion_gate.json` |

## 设计对齐（Claude Code 调研）

- 竞品将 **stop/completion condition** 与 verify/review 分离；Asteria 规则型 evaluator 为合理 MVP，ML judge defer Phase 7+。
- `min_review_score` 读取 `eval_report.json` 的 `overall.score`，与 benchmark 分数闸门一致。

## green_checks

```powershell
pytest tests/integration/test_phase6c_long_horizon_completion_gate.py -q
pytest tests/unit/test_long_horizon_completion.py -q
```

## 纪律确认

- accept 仅追加 evaluator / user_progress，未改 DO_NOT_TOUCH 执行栈
- 无 North Star 时不写入 slice 判定噪音
