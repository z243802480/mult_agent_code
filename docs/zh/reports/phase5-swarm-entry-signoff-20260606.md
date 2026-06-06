# Phase 5 蜂群入口签字（S18–S21）

**日期**：2026-06-06  
**闸门**：`benchmarks/phase5_swarm_gate.json`

## 交付摘要

| Slice | 交付 | 证据 |
| --- | --- | --- |
| S18 | worker_spawn + harness 强制 | `test_worker_spawn.py` |
| S19 | candidate_export + merge dry-run | `test_candidate_export_merge_dry_run.py` |
| S20 | Studio 进度条 + promotion preview | `s20-worker-promotion-smoke.mjs` |
| S21 | maintainer gray path + gate audit | `swarm_maintainer_gray_check.py` |

## 验证

```text
python scripts/swarm_maintainer_gray_check.py --root .
→ ok: true（contract tests + Studio smokes）
```

## 边界（仍关闭）

- `real_disjoint_write_workers`：false
- CLI `parallel_writes` 默认：false
- Beta 主路径：session_agent（S17）

## 下一维护脉搏

- 每周：`swarm_maintainer_gray_check.py --skip-studio`（日常）+ 含 Studio（签字前）
- 真实 disjoint-write 灰度：需单独 DecisionPoint + flag 演练（Phase 5+）
