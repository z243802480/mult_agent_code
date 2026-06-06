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
