# Slice S36 — Design Intelligence Research Bridge

## observed_pattern

- S35 已在 plan 契约持久化 pilot `research_type`（documentation / creative / research）。
- 现有 `/research --type` 栈（product / architecture / competitive 等）与 plan 路径尚未对齐。
- 设计情报文档要求 research 输出进入 goal_spec / task_plan / user_progress，而非孤立 report。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `/research --type` → plan `research_type` 映射 | 与 `design_intel_contract` 扩展或并存 |
| `research_report` 进 plan 上下文 | plan_command / RequirementPlanner 可选挂载 |
| `phase6b_design_intel_research_gate.json` | Phase 6 wave 2 闸门 |
| validation matrix `profile:research` | 与 research 主路径对齐 |

## do_not_copy

- 不复制 proprietary research 产品 UI
- 不把 `/research` 变成每个 goal 的强制前置

## green_checks（规划 · 实现后）

```bash
pytest tests/integration/test_phase6b_design_intel_research_gate.py -q
pytest tests/unit/test_documentation_contracts.py -q
```

## discipline

- 不替换 session_agent Beta 默认路径
- 不引入 12 Agent 新类
- 先 brief → 小 diff → demo → 三源同步

---

## 实现记录（2026-06-06）

| 交付 | 路径 |
| --- | --- |
| research bridge 模块 | `src/asteria_runtime/core/design_intel_research_bridge.py` |
| CLI→plan 映射 | `design_intel_contract.map_research_cli_type_to_plan_type` |
| plan 桥接 | `plan_command`：`run_id` 复用 + `research_report_ref` + user_progress |
| task_kind=research | 有 `research_cli_type` 时首 task 设 research 并 pop execution_profile |
| matrix 证据 | `profile:research` 接受 `design_intel_research_band` |
| 闸门 | `phase6b_design_intel_research_gate.json` |

签字：`docs/zh/reports/S36-design-intel-research-bridge-signoff-20260606.md`
