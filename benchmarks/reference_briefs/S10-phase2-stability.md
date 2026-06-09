# Slice S10 — Phase 2 稳态指标审计

## observed_pattern（行业已验证）

- **历史说明，已被 ADR-0010 校正**：scoped smoke 矩阵记录 model calls 与 repair 次数，用作产品 SLO、回归趋势和 release DecisionPoint 输入；它们不是所有任务统一的 Runtime 硬停止条件。
- **OpenCode**：CI 契约用 fake；real provider 签字用 matrix_summary 归档。

## asteria_mapping（我们怎么做）

- 文件：`phase2_stability_audit.py`、`benchmarks/phase2_stability_gate.json`
- 历史 S10 目标：`reviewed_auto` scoped — median model calls ≤ 5，repair ≤ 1。该目标仅用于当时 scoped 样本的性能签字，不约束复杂任务和长任务。
- 样本：`doc_update`、`single_file_bugfix`（与 Phase 3 rolling 对齐）+ fake CI 契约
- 可选：`evidence-bundle` 归档 S7 workspace

## do_not_copy（禁止照搬）

- 把 North Star / 蜂群混进稳态 gate
- 用 workspace 全量 run 污染 scoped median

## green_checks

- `pytest tests/integration/test_phase2_stability_gate.py -q`
- `pytest tests/unit/test_phase2_stability_audit.py -q`
