# Slice S61 — Runtime 编排对齐（R0–R5 · 多对多调度）

更新时间：2026-06-07  
状态：**active · R0–R5 代码交付**  
计划：[`docs/zh/plans/RUNTIME_ORCHESTRATION_ALIGNMENT_PLAN.md`](../../docs/zh/plans/RUNTIME_ORCHESTRATION_ALIGNMENT_PLAN.md)  
哲学：[`docs/zh/plans/RUNTIME_MULTI_DISPATCH_MODEL.md`](../../docs/zh/plans/RUNTIME_MULTI_DISPATCH_MODEL.md)

## observed_pattern

- **Claude Code**：统一 QueryEngine；CLAUDE.md + prompts；tool_use；无 domain 代码分支
- **Netty 三池**：仅类比 **多对多调度拓扑**（编排 / 协调 / 执行），非 Asteria 产品名词
- **Asteria 既有术语**：Runtime · Harness · Orchestrator · Coordinator · Worker invocation（SWARM RFC · 数据模型 §11）

## asteria_mapping

| 层 | 术语 | 组件 |
| --- | --- | --- |
| 编排面 | Orchestrator / Goal Loop | GoalSpec · Plan · swarm_orchestrator |
| 协调面 | Coordinator | ExecutionCoordinator · TaskGraphScheduler |
| 执行面 | Worker + RuntimeProfile | session_agent · harness · workers.jsonl |
| 两层产品 | Runtime / Harness | S17 RFC Layer 0 / 1 |
| 积累 | prompt_envelope 双 discipline | R3 |

## do_not_copy

- 引入 Boss 作为产品层级
- CC Desktop / 专有 coordinator 实现
- domain runtime 分支 · execute/run 重构

## 五阶段摘要

| 阶段 | 交付 |
| --- | --- |
| R0 | RUNTIME_MULTI_DISPATCH_MODEL + 本 brief |
| R1 | 回滚 S60 定向层 |
| R2 | fast_path → risk_tier（编排面契约） |
| R3 | orchestration + execution discipline |
| R4 | 执行面 tool_use 双轨 ADR |
| R5 | validation_commands 契约化 |

## green_checks（R1）

```powershell
pytest tests/unit/test_fast_path_policy.py tests/unit/test_coder_agent.py -q
python scripts/triple_track_pulse.py --root . --skip-b6
python scripts/swarm_holistic_check.py --root . --skip-studio
```

## 验收

- [x] R0 术语与五阶段计划
- [x] R1 回滚 S60 定向层
- [x] R2 risk_tier
- [x] R3 envelope discipline
- [x] R4 worker_transport
- [x] R5 validation 契约化
