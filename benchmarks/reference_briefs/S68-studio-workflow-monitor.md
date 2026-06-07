# Slice S68 — Studio Workflow Monitor（≈ CC `/workflows`）

更新时间：2026-06-07  
状态：**Wave 8 / S68 实现**  
依赖：S67 L3 live execution ✅  

**参考**：CC Dynamic Workflows `/workflows` · Cursor Agents Window（隔离 id + merge 状态）

## observed_pattern

- 运行中 workflow 的 **step 状态** 可监控
- **隔离单元 id** + **merge 状态** 可见
- 主 Thread 不灌中间态；Inspector 读证据

## asteria_mapping

| 能力 | 实现 |
|---|---|
| runner state 真源 | `orchestration_runner_state.jsonl` |
| 投影 | `orchestration_workflow_monitor.py` + `studio/lib/orchestration-workflow-monitor.mjs` |
| run detail | `payload.orchestration_workflow` |
| Studio UI | `WorkflowMonitorPanel`（Inspector） |
| user_progress | `event_type=workflow_step`, `display_level=inspector` |

## green_checks

```powershell
pytest tests/unit/test_orchestration_workflow_monitor.py -q
node studio/scripts/s68-workflow-monitor-smoke.mjs
```

## defer

- S69 adversarial manifest steps
- Thread 主路径 workflow 卡片（仅 Inspector 先行）
