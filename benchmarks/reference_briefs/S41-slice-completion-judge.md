# Slice S41 — ML-Assisted Slice Completion Judge

## observed_pattern

- Claude Code `/goal` 在 turn 结束时有 **独立 completion judge**（小模型），不替代 verify/review，可 veto「看起来完成但未达 milestone」。
- S37 规则型 evaluator 为 MVP；Phase 8 叠加 **可选 model judge**，规则仍为先决条件。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `slice_completion_judge.py` | `purpose=slice_completion_judge` · medium tier |
| `north_star.slice_completion_policy` | `enable_model_judge` · `model_judge_tier` |
| accept 收尾 | 规则通过后调用 judge；model 仅可 **veto**，不可 bypass |
| `slice_completion_eval.json` | 新增 `model_judge` 字段 |
| `phase8a_slice_completion_judge_gate.json` | Phase 8 wave 1 闸门 |

## do_not_copy

- 不用 model judge 替代 accept/review
- 不 silent auto-complete

## green_checks

```bash
pytest tests/integration/test_phase8a_slice_completion_judge_gate.py -q
pytest tests/unit/test_slice_completion_judge.py -q
pytest tests/unit/test_long_horizon_completion.py -q
```

## discipline

- DO_NOT_TOUCH execute/run 大 refactor
- fake provider 可离线验收
