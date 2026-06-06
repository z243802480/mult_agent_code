# Slice S33 — Beta Friction Convergence

## observed_pattern

- S16 摩擦：status 推荐 `replan` 时 Studio 须映射为 `resume/continue`（session_agent 路径）。
- B6 阈值：decide/debug/resume ≤2。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `studio/server.mjs` | `runtimeActionFor`: replan → continue |
| `status_command.py` | observation route replan → resume（session_agent） |
| `friction_contract.py` | B6 摩擦计数契约 |
| `phase4_friction_gate.json` | Phase 4 稳态闸门扩展 |

## green_checks

```bash
pytest tests/unit/test_friction_contract.py -q
node studio/scripts/s33-friction-contract-smoke.mjs
```

## discipline

- 不 refactor execute/run
- 完整 B6 仍 optional（maintainer sign-off）
