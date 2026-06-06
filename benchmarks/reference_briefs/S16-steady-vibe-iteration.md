# Slice S16 — 稳态 Vibe 迭代

## observed_pattern

- Slice 签字后容易「继续扩张」而不是「继续验证」——走偏来自缺少轻量回环，不是缺新功能。
- Vibe coding 要稳定：模型每次会话应落在 **brief → 小 diff → green_checks → 用户路径 demo** 上，而不是重新发明路线。
- Studio Beta 路径的主要摩擦来自 **runtime_request decide 链** 与 **debug 循环**，不是缺新命令。

## asteria_mapping

| 交付 | 行为 | 状态 |
| --- | --- | --- |
| 迭代节奏文档 | [`docs/zh/稳态迭代节奏.md`](../../docs/zh/稳态迭代节奏.md) | ✅ |
| 健康脉搏脚本 | `scripts/steady_iteration_check.py` | ✅ |
| 契约 | `benchmarks/phase4_steady_iteration_gate.json` | ✅ |
| 三源文档同步 | AGENTS · 研发总计划 · 当前状态 · vibe_slices | ✅（持续） |
| Studio 摩擦 | 低风险 request 自动放行；decide→resume；B6 `friction` | ⏳ |
| 摩擦观察 | B6 / doc_update 的 decide、debug、resume 次数 | ⏳ |

## focus（本 Slice 精力投向）

1. **Studio 优先**：`small_code_change` 可重复到 accept（B6 或真人路径）
2. 文档跟着代码走：研发总计划 §8–§9 与 `vibe_slices.json` 一致
3. 全库 pytest 保持绿（签字前 `pytest -q`）

## green_checks

**日常**：

- `python scripts/steady_iteration_check.py --root . --skip-b6`
- `pytest tests/unit/test_documentation_contracts.py -q`

**签字 / 每周**：

- `python scripts/steady_iteration_check.py --root .`（含 B6）
- `pytest -q`

## 退出条件（S16 → 维护态签字）

- B6 连续 2 次绿（或等价 maintainer 试跑记录）
- `friction.debug` 中位数可接受（目标 ≤2）
- 三源文档与 gate json 无漂移
