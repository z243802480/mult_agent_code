# Slice S7 — MVP 终点

## observed_pattern（行业已验证）

- **行业共识**：E2E benchmark + real provider 签字，而非 fake-only 自嗨。
- **OpenCode/Claude/Codex**：小代码改动任务是可重复的 MVP 证明。

## asteria_mapping（我们怎么做）

- 文件：`studio_benchmark_command.py`、`benchmarks/studio_user_tasks.json`
- 行为：`small_code_change` score ≥ 0.8；real provider model-check 通过
- 用户入口：`python -m asteria_runtime studio-benchmark --root . --json`

## do_not_copy（禁止照搬）

- 用 fake provider 冒充 MVP 签字
- 无 evidence bundle 的 benchmark pass

## 实现记录

- date: 2026-06-05
- notes: `benchmarks/fixtures/s7_golden_run/` + `test_s7_golden_benchmark.py`；run 级 `studio-benchmark --run-id` 为 S7 契约验收；real provider 见 `phase2_mvp_gate.json` 与 `docs/zh/reports/S7-mvp-signoff-20260606.md`（signed 2026-06-06）。
