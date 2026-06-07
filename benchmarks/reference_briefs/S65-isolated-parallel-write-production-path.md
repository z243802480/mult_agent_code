# Slice S65 — Isolated Parallel Write Production Path (Wave 5 / L2)

更新时间：2026-06-07  
状态：**active — L2 生产路径 gate**  
依赖：Wave 4 ✅ · S23/S34 蜂群栈 · [参考对齐报告](../docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md)

## observed_pattern（Cursor / CC / Codex · L2）

| 参考 | 机制 | Asteria 映射 |
| --- | --- | --- |
| CC worktree | subagent `isolation: worktree` | `CandidateWorkspace` isolated_copy / git_worktree |
| Cursor Background | 独立分支 + PR 合并 | candidate export + merge gate dry-run |
| Codex | 显式 spawn + sandbox/worktree | **显式** `--parallel-disjoint-writes`；非默认 |

**禁止**：CLI `parallel_writes` 默认 true；同 working copy 无隔离多写者。

## asteria_mapping（Wave 5）

| 交付 | 行为 |
| --- | --- |
| 本仓库 `.asteria/runs/` 跑 **real_disjoint + dual_disjoint execute** | 证据落 `.asteria/validation_runs/` + verification |
| Policy `isolated_parallel_write_production_path: true` | maintainer **显式路径**已验证；默认仍 off |
| DecisionPoint `wave5_isolated_production_path` | 开放 L2 生产路径，**不**改 CLI 默认 |

## 准入

- [x] Wave 4 probe + `orchestration_workflows_gray`
- [x] Wave 3 catalog gray
- [ ] 本仓库 candidate + merge 证据（非 temp-only）
- [ ] `parallel_writes` CLI 默认仍 false
- [ ] `real_disjoint_write_workers` 全局默认仍 false

## green_checks

```powershell
pytest tests/unit/test_orchestration_parallel_gray.py -q
python scripts/orchestration_wave5_production_probe.py --root .
```
