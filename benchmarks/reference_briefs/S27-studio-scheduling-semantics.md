# Slice S27 — Studio Scheduling Semantics

## observed_pattern

- 用户应能区分 **fake_serial 预览** 与 **真实 parallel**，避免误以为 Beta 已开蜂群。

## asteria_mapping

| 交付 | 行为 |
| --- | --- |
| `server.mjs` | 读 `swarm_execution_plans.jsonl` → `worker_summary.scheduling_mode` |
| `WorkerProgressBar.tsx` | scheduling 徽章 |

## green_checks

```bash
node studio/scripts/s20-worker-promotion-smoke.mjs
```
