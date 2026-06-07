# Slice S64 — Orchestration Parallel Gray Rollout

更新时间：2026-06-07  
状态：**research + readiness gate**  
依赖：S63 eval ✅ · S32/S34 蜂群 gray 栈  

**调研**：[`docs/zh/reports/S64-parallel-rollout-research-20260607.md`](../../docs/zh/reports/S64-parallel-rollout-research-20260607.md)

## observed_pattern（主流 · 2026）

| 产品 | 默认 | 并行形态 | 硬上限 / 护栏 |
| --- | --- | --- | --- |
| **Claude Code** | 主 loop + 按需 subagent | loop 内 1–3；独立任务并行 | rate limit；workflows **16 并发 / 1000/run** |
| **Cursor** | 前台 Agent + Background Agents | 云端 **≤8 并发**；分支隔离 | delegate-and-review |
| **Asteria** | session_agent + loop subagent | Coordinator gray | merge · DecisionPoint · strong spawn |

## asteria_mapping（Wave）

| Wave | 内容 | 状态 |
| --- | --- | --- |
| 0 | session_agent 单写者 | ✅ Beta 默认 |
| 1 | strong route + spawn policy + eval | ✅ S62/S63 |
| 2 | maintainer `parallel_writes` 隔离 probe | 🔄 S64 gate |
| 3 | `spawn_parallel_workers` catalog | defer |
| 4 | CC workflows 级 | defer |

## green_checks

```powershell
pytest tests/unit/test_orchestration_parallel_gray.py -q
python scripts/orchestration_parallel_gray_pulse.py --root .
```
