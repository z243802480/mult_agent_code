# Slice S37 — Long Horizon Completion Contract

## observed_pattern

- 竞品（Claude `/goal`、Codex-rs）在 turn/slice 结束后有**独立 completion judge**，不混同 verify/review/accept。
- Asteria 已有 task 级 `check_completion_contract`，缺 **North Star / run 级 slice 完成判定**。
- accept 后 user_progress 应明确「本 slice 是否达成」，供长期目标监督。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `north_star.slice_completion_policy` | 可选策略：requires_accepted_run / review_pass / tasks_done / **min_review_score** |
| `long_horizon_completion.py` | `evaluate_slice_completion` · `slice_completion_eval.json` |
| accept 收尾 | evaluator + user_progress「本 slice 完成判定」 |
| `status --json long_horizon` | `last_slice_completion` 投影 |
| `phase6c_long_horizon_completion_gate.json` | Phase 6 wave 3 闸门 |

## do_not_copy

- 不复制 proprietary goal/completion UI
- 不把 completion evaluator 变成 silent auto-accept

## green_checks

```bash
pytest tests/integration/test_phase6c_long_horizon_completion_gate.py -q
pytest tests/unit/test_long_horizon_completion.py -q
```

## discipline

- DO_NOT_TOUCH run_command 大 refactor；accept 仅追加 user_progress
- North Star 不 silent auto execute
