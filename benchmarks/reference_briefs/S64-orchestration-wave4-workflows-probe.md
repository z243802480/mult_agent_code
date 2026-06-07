# Slice S64-W4 — Orchestration Workflows Gray Probe

更新时间：2026-06-07  
状态：**active — Wave 4 maintainer probe**  
依赖：Wave 3 catalog gray ✅ · S23 real_disjoint probe · S62/S63 eval  

**调研**：[`docs/zh/reports/S64-parallel-rollout-research-20260607.md`](../../docs/zh/reports/S64-parallel-rollout-research-20260607.md)

## observed_pattern（CC Dynamic Workflows = L3，本 slice = L2）

> **命名澄清**：本 brief 的 Wave 4 是 **L2 maintainer real_disjoint 资格门**，不是 Claude Code [Dynamic Workflows](https://code.claude.com/docs/en/workflows)（L3 脚本编排）。对照见 `docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md`。

| CC | Asteria Wave 4 |
| --- | --- |
| 脚本编排 16 并发 / 1000 run | maintainer **workflows gray** + 隔离 real_disjoint probe |
| 不进主 context | 证据写 `.asteria/verification/`，policy 键 `orchestration_workflows_gray` |
| 仍非默认 | CLI `parallel_writes` **仍 false**；`real_disjoint_write_workers` 默认仍 false |

## asteria_mapping

| Wave | 内容 | 状态 |
| --- | --- | --- |
| 4 | workflows gray + 隔离 real_disjoint + route 回归 | 🔄 本 slice |
| 5（defer） | CLI `parallel_writes` 生产默认 | 须 Wave 4 + validation-run + DecisionPoint |

## 准入（Wave 4）

- [x] Wave 3 probe + DecisionPoint `wave3_catalog_gray`
- [x] S62/S63 real eval
- [x] Wave 2 isolated probe
- [ ] 隔离 workspace `run_maintainer_real_disjoint_probe` ok
- [ ] route 回归（小改不 parallel + catalog 仍可用）
- [ ] DecisionPoint `wave4_workflows_gray`

## green_checks

```powershell
pytest tests/unit/test_orchestration_parallel_gray.py -q
python scripts/orchestration_wave4_workflows_probe.py --root .
```
