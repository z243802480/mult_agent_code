# Slice S42 — Long Horizon Handoff Compact

## observed_pattern

- Claude Code / 长任务实践：compact + handoff 文件跨 session 续跑，减 goal drift。
- Asteria 已有 run 级 `compact`/`handoff` 与 workspace 级 `active_goal_memory`；缺 **North Star 波段级** 压缩投影。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `long_horizon_handoff.py` | `.asteria/long_horizon_handoff.json` |
| accept 收尾 | North Star 存在时 build + persist |
| `status --json` | `long_horizon.handoff_compact` |
| Studio Inspector | LongHorizonPanel 展示 narrative + Continue |

## do_not_copy

- 不替代 run 级 handoff_package
- 不 silent auto goal

## green_checks

```bash
pytest tests/integration/test_phase8b_long_horizon_handoff_gate.py -q
pytest tests/unit/test_long_horizon_handoff.py -q
```
