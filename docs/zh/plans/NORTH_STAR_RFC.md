# North Star 长目标 RFC

> **状态：已实现**（S12 North Star v1 + Phase 6 S37–S40 Long Horizon）。  
> **非阻塞**：观察窗与「禁止写 north_star.json」条款已废止。  
> **现行框架**：[`LONG_TASK_GOAL_FRAMEWORK.md`](./LONG_TASK_GOAL_FRAMEWORK.md)

---

## 1. 背景

North Star 是 **跨 run 的远端目标**（OpenCode utw 思路），与当前 run 的 plan/tool/verify 叙事分离。

## 2. 已实现能力

| 能力 | Slice | 证据 |
| --- | --- | --- |
| `north_star.json` 存储与 schema | S12 | `test_north_star_storage.py` |
| status / handoff 投影 | S12 | `test_status_long_horizon.py` |
| accept 链接 milestone | S12 | `test_accept_command.py` |
| Studio Inspector | S12 | `north-star-inspector-smoke.mjs` |
| slice 完成判定 | S37 | `slice_completion_eval.json` |
| goal queue + Continue | S38 | `goal_queue.json` |
| 监督多 slice 循环 | S39 | `--toward-north-star` |
| 本地 background run | S40 | `background_run_registry.json` |
| 可选 model judge | S41 | `slice_completion_judge.py` |

## 3. 仍 out of scope

- 蜂群 parallel 默认开启 → [`deferred/SWARM_SANDBOX_RFC.md`](../deferred/SWARM_SANDBOX_RFC.md)
- silent auto execute
- gate 主屏 North Star dashboard
- SQLite 替代 JSON

## 4. 验证

```powershell
python scripts/long_horizon_maintainer_smoke.py --root .
pytest tests/integration/test_phase6c_long_horizon_completion_gate.py -q
pytest tests/integration/test_status_long_horizon.py -q
```

## 5. 历史

- 2026-06-06：RFC 开启；观察窗至 2026-06-20（门槛已满足，S12 提前实现）
- 2026-06-06：Phase 6 S37–S40 闭合；RFC 升格为已实现摘要
