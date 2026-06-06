# Runtime Session Agent RFC

**状态**：accepted — 2026-06-06  
**Slice**：S17  
**相关 ADR**：[0008 Fast Path](../adr/0008-fast-path-tiered-review-and-context-slimming.md)

## 问题

Asteria 把 Phase 5 Harness 的默认路径（多 task、blocked→Debug→Replan→repair_limit）放进了 Beta 用户路径，导致 `small_code_change` 等任务慢、脆、摩擦高。Claude Code 等产品在 **单 Agent 会话** 内用 tool error 回流解决长任务；Harness 审计应在 **蜂群/多写者** 层叠加。

## 决策

### 两层产品单位

```text
Runtime（默认）  ≈  CC 级 session agent：单任务、会话内 retry、证据异步落盘
Harness（显式）  ≈  多 task 图 + replan lineage + repair_limit + promotion
```

### execution_profile

| profile | 何时 | Plan | Run 失败 |
| --- | --- | --- | --- |
| `session_agent` | 默认；单写者；非 high_risk | 合并为 task-0001 | debug → 同任务 requeue；**不** ReplanCommand |
| `harness` | `force_harness` / `parallel_writes` / high_risk | 现有多 task 行为 | debug → replan lineage |

持久化：`run_config.json` 的 `execution_profile` + `fast_path`。

### 硬规则

> 不涉及第二写者或晋升主工作区的流程，**禁止**默认引入 replan lineage 与 repair_limit DecisionPoint。

### 蜂群（Phase 5 defer）

蜂群 worker 使用 `harness` profile；证据机制、candidate、merge gate 在 worker 层启用。Runtime 单 Agent 不删减这些能力，只是 **默认不激活**。

## 实现清单（S17）

- [x] `src/asteria_runtime/core/execution_profile.py`
- [x] `run_config` schema 扩展
- [x] `RequirementPlanner._session_agent_unified_task`
- [x] `AgentLoopProfileRegistry.session_agent`
- [x] `RunCommand` session_agent requeue + skip replan
- [x] `runtime_request.status=auto_applied` schema + benign `context_request` 自动合并
- [ ] B6 连续 2 绿（maintainer 复验）

## 非目标（S17）

- 不启动 Phase 5 蜂群真实 parallel
- 不删除 ReplanCommand / repair_limit（maintainer harness 仍用）
- 不重构 `execute_command.py` / `run_command.py` 整体结构

## 验证

```bash
pytest tests/unit/test_execution_profile.py tests/unit/test_planner.py::test_session_agent_unified_task_collapses_beta_coding_goal -q
pytest tests/integration/test_run_command.py::test_run_command_replans_when_debug_cannot_repair -q
```
