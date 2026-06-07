# Slice S67 — L3 Dynamic Live Execution（CC Workflow Runtime）

更新时间：2026-06-07  
状态：**Wave 7 实现中**  
依赖：S66 Wave 6 L3 dry-run runner ✅  

**参考对齐**：[`docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md`](../../docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md)  
**CC 文档**：Dynamic Workflows — runtime 执行 agent，中间态在 script variables

## observed_pattern（CC）

- Workflow **真执行** subagent/worker，不是只 plan
- 结果写入 **script variables**（不进主 context）
- 写路径仍 **隔离**（worktree / sandbox）
- `/workflows` 可监控 step 状态（Studio defer → S68）

## asteria_mapping（Wave 7）

| CC | Asteria |
|---|---|
| workflow runtime spawn | `orchestration_dynamic_live.py` |
| script variables | `RunnerStepRecord.variables` + JSONL |
| readonly parallel explore | `execute_readonly_fanout_live` → `workers.jsonl` |
| isolated parallel write | `execute_disjoint_write_fanout_live` → candidate + merge |
| merge checkpoint | `execute_merge_checkpoint_live` |

## 政策键

- `orchestration_dynamic_live_execution_gray` — default **false**
- 前置：`orchestration_dynamic_workflows_gray=true`
- **禁止** CLI `parallel_writes` 默认 true

## do_not_copy

- CC JS runtime
- 无隔离 live 写
- 把 manifest 注入 AgentLoop

## green_checks

```powershell
pytest tests/unit/test_orchestration_dynamic_live.py tests/unit/test_orchestration_dynamic_runner.py tests/unit/test_orchestration_parallel_gray.py -q
python scripts/orchestration_wave7_live_probe.py --root .
```

## defer

- S68 Studio workflow monitor
- S69 adversarial manifest steps
- real-model provider 全路径（maintainer band 先用 evidence worker）
