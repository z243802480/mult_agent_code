# Slice S35 — Design Intelligence Pilot (Phase 6 入口)

## observed_pattern

- Phase 5 出口（S34 production gray）已闭合；下一 North Star 能力为 **Design Intelligence 产品化**。
- MVP 阶段用 per-slice brief 代替全类型 `/research`；S35 做 **最小可验证试点**。

## asteria_mapping

| 交付 | 全局挂钩 |
| --- | --- |
| `research_type` 契约扩展 | plan / goal_spec 可声明 creative/doc/research 类型 |
| `phase6_design_intel_gate.json` | Phase 6 入口闸门（pilot scope） |
| validation matrix `profile:research` 深化 | 与 `/research --type` 路径对齐 |

## green_checks（规划 · 实现后）

```bash
pytest tests/integration/test_phase6_design_intel_gate.py -q
pytest tests/unit/test_documentation_contracts.py -q
```

## discipline

- 不替换 session_agent Beta 默认路径
- 不引入 12 Agent 新类
- 先 brief → 小 diff → demo → 三源同步
