# Slice S66 — L3 Dynamic Orchestration Runner（CC Workflows 机制）

更新时间：2026-06-07  
状态：**Wave 6 实现中**  
依赖：S65 Wave 5 L2 生产路径 ✅  

**参考对齐**：[`docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md`](../../docs/zh/reports/S64-W4-W5-reference-alignment-20260607.md)  
**CC 文档**：Claude Code Dynamic Workflows（plan in script, state in variables, ≤16 concurrent）

## observed_pattern（CC Dynamic Workflows）

- 模型写 **可执行编排**（CC 为 JS）；runtime 执行，**中间态在 script variables**
- 计划 **不进主 AgentLoop context**；主 loop 仅触发/监控
- 并发上限（16 concurrent / 1000 agents per run）；可 resume
- 与 L1 subagent 区别：**脚本/manifest 持计划**，非每 turn 模型编排

## asteria_mapping（L3）

| CC 机制 | Asteria Wave 6 |
| --- | --- |
| `.js` workflow script | `orchestration_manifest.json` + `orchestration_dynamic_runner.py` |
| script variables | `orchestration_runner_state.jsonl` under run_dir |
| 16 concurrent cap | policy `max_parallel_workers_per_run`（default 16） |
| resume workflow | runner 读 JSONL checkpoint，跳过 completed steps |
| 不进主 context | `manifest.context_footprint_hint()` 仅事件摘要 |

## 政策键

- `orchestration_dynamic_workflows_gray` — default **false**；Wave 6 probe 后 maintainer 可 true
- `max_parallel_workers_per_run` — default **16**
- **禁止**用 `parallel_writes=true` 代替 L3

## 前置

- Wave 5 `isolated_parallel_write_production_path=true`
- DecisionPoint `decision-orchestration-parallel-0005`

## do_not_copy

- CC JS runtime / Ultracode 专有 API
- 将完整 manifest 注入 AgentLoop system prompt
- keyword 触发 L3 workflow

## green_checks

```powershell
pytest tests/unit/test_orchestration_dynamic_runner.py tests/unit/test_orchestration_parallel_gray.py -q
python scripts/orchestration_wave6_dynamic_probe.py --root .
```

## defer

- Live worker 执行（非 dry_run）与 adversarial subagents in script
- Studio `/workflows` 监控 UI（≈ CC workflows 面板）
- CLI 默认 `parallel_writes` true
