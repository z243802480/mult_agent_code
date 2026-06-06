# Slice S16 — 稳态 Vibe 迭代

## observed_pattern

- Slice 签字后容易「继续扩张」而不是「继续验证」——走偏来自缺少轻量回环，不是缺新功能。
- Vibe coding 要稳定：模型每次会话应落在 **brief → 小 diff → green_checks → 用户路径 demo** 上，而不是重新发明路线。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| 迭代节奏文档 | [`docs/zh/稳态迭代节奏.md`](../../docs/zh/稳态迭代节奏.md) — 会话 / 周 / 阶段三层，正向描述 |
| 健康脉搏脚本 | `scripts/steady_iteration_check.py` — 一条命令跑维护者 bundle |
| 契约 | `benchmarks/phase4_steady_iteration_gate.json` — green_checks 真源 |
| 摩擦观察 | 记录 B6 / doc_update 的 decide、debug 次数（先观察，再小步收敛） |

## focus（本 Slice 精力投向）

- Beta 用户路径：`small_code_change` + `doc_update` 可重复跑通
- 文档三源一致：AGENTS · 研发总计划 §16 · 当前状态 · vibe_slices
- 全库 pytest 保持绿（维护者每周至少一次）

## green_checks

- `python scripts/steady_iteration_check.py --root .`
- `pytest tests/unit/test_documentation_contracts.py -q`
- `pytest -q`（全库，签字前）
