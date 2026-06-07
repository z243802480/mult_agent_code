# Slice S63 — CC Loop Convergence（编排收敛）

更新时间：2026-06-07  
状态：**S63-1/2/3 ✅ · S62-4/5 ✅ · §5 eval 通过 · parallel gray 仍 off**  
依赖：S62 strong route ✅  

**政策真源**：[`docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md`](../../docs/zh/plans/ORCHESTRATION_DECISION_POLICY.md)  
**调研**：[`docs/zh/plans/CC_ORCHESTRATION_ALIGNMENT.md`](../../docs/zh/plans/CC_ORCHESTRATION_ALIGNMENT.md) · [`docs/zh/reports/S63-spawn-decision-research-20260607.md`](../../docs/zh/reports/S63-spawn-decision-research-20260607.md)  
**代码单点**：`src/asteria_runtime/core/orchestration_spawn_policy.py`

## observed_pattern（CC）

- 主 loop turn-by-turn：模型选 tool / subagent，无入口 keyword route
- Subagent：`description` + when_to_use；**strong 语义**决定是否 spawn
- 1–3 并行 subagent 在 loop 内；10+ 才 workflows（defer）

## asteria_mapping

| 交付 | 状态 |
| --- | --- |
| S63-1 SPAWN_DECISION_POLICY + manifest when_to_use | ✅ |
| S63-1 ORCHESTRATION_DECISION_POLICY.md | ✅ |
| S63-1 S63-spawn-decision-research 报告 | ✅ |
| S63-2 route prompt 携带 policy JSON | ✅ |
| S63-3 real-model spawn golden | CI fake ✅ · real 95.7% / 23 cases ✅ |
| S62-5 chat→execute handoff | ✅ |
| defer | 入口 mechanical 多 worker · cheap route |

## 原则

```text
抉择 → strong + capability 描述（见 ORCHESTRATION_DECISION_POLICY）
spawn → loop 内 subagent；不 keyword / 不计数拆 worker
parallel_writes → gray + 调研放量条件（报告 §5）
```

## do_not_copy

- 文件数/task 数阈值 spawn
- keyword 入口路由
- cheap orchestration/spawn

## green_checks

```powershell
pytest tests/unit/test_orchestration_spawn_policy.py tests/unit/test_orchestration_spawn_eval.py tests/unit/test_agent_harness.py -q
pytest tests/unit/test_orchestration_router.py -q
python scripts/orchestration_route_pulse.py --root .
python scripts/orchestration_spawn_pulse.py --root .
# maintainer + provider:
python scripts/orchestration_route_pulse.py --root . --real
python scripts/orchestration_spawn_pulse.py --root . --real
node studio/scripts/chat-execute-handoff-smoke.mjs
```
