# Slice S18 — Worker Spawn + Harness Profile

## observed_pattern

- 蜂群 worker 不是改 Runtime 默认路径；写路径 worker 必须强制 `execution_profile=harness`。
- `real_disjoint_write_workers` 默认关 → 多写者走 **fake_serial** 契约（记录 spawn 证据，不放量真实并行）。
- 只读 fanout 保持 `session_agent`；disjoint write 走 harness + merge gate 预备。

## asteria_mapping

| 交付 | 行为 | 状态 |
| --- | --- | --- |
| `worker_spawn.py` | spawn 契约、fake_path、spawn 事件 | ✅ |
| `resolve_worker_execution_profile` | 写→harness；只读→session_agent | ✅ |
| `worker_invocation.execution_profile_id` | schema + recorder 持久化 | ✅ |
| `subagent_planner` enrich | child task 带 execution_profile | ✅ |
| SWARM RFC §6 S18 | 对齐里程碑 | ✅ |

## focus

1. **契约先行**：`WorkerSpawnPlan` + `worker_spawn_planned` 事件
2. **Harness 强制**：写 worker 不得落 session_agent
3. **Fake path**：flag 关 → `fake_serial`；flag 开 → `parallel`
4. 不扩 execute_command 真实 parallel（KEEP_PLACEHOLDER）

## green_checks

```bash
pytest tests/unit/test_worker_spawn.py tests/unit/test_worker_recorder.py -q
pytest tests/unit/test_subagent_planner.py -q
python scripts/steady_iteration_check.py --root . --skip-b6
pytest tests/unit/test_documentation_contracts.py -q
```

## 退出条件

- worker spawn 单元测试绿
- worker_invocation 含 execution_profile_id
- 三源 ACTIVE_SLICE=S18
- S19：candidate export + merge gate dry-run（下一 Slice）
