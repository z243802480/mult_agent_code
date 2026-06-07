# S65 Wave 5 L2 隔离并行写生产路径签字

**日期**：2026-06-07  
**状态**：signed — 本仓库 L2 生产路径已验证；**CLI 默认仍 off**  
**参考对齐**：[`S64-W4-W5-reference-alignment-20260607.md`](./S64-W4-W5-reference-alignment-20260607.md)  
**Brief**：[`S65-isolated-parallel-write-production-path.md`](../../benchmarks/reference_briefs/S65-isolated-parallel-write-production-path.md)

## 摘要

| 步骤 | 结果 |
| --- | --- |
| DecisionPoint `0004` → `wave5_isolated_production_path` | ✅ |
| 本仓库 candidate + explicit `dual_disjoint` execute | ✅ |
| Policy `isolated_parallel_write_production_path` | **true** |
| validation_run 证据 | `.asteria/validation_runs/validation-wave5-isolated-parallel-*` |
| CLI `parallel_writes` 默认 | **false** |
| `real_disjoint_write_workers` 全局默认 | **false** |

## 主流对齐（L2）

| 参考 | Asteria Wave 5 |
| --- | --- |
| CC worktree 隔离 | `CandidateWorkspace` + merge dry-run |
| Cursor 分支 + PR | candidate export → merge gate |
| Codex 显式 spawn | `--parallel-disjoint-writes` / maintainer 显式路径 |

## 命令

```powershell
python scripts/orchestration_wave5_production_probe.py --root .
pytest tests/unit/test_orchestration_parallel_gray.py -q
```

## maintainer 显式并行写（非默认）

```powershell
asteria execute --parallel-disjoint-writes ...
```

仅当 `isolated_parallel_write_production_path=true` 且 Wave 5 证据存在时，maintainer 应将此视为 **已验证的生产路径**。

## 仍 defer

- CLI `parallel_writes` **Beta 默认 true**（无 DecisionPoint + 产品签字前禁止）
- L3 可复跑编排脚本（≈ CC Dynamic Workflows 机制）→ 独立 slice S66+

## 证据

- `.asteria/verification/orchestration_wave5_production_path.json`
- `.asteria/decisions/decision-orchestration-parallel-0004.json`
