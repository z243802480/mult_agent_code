# S36 Design Intel Research Bridge — Signoff 2026-06-06

## 目标

闭合 Phase 6 **research bridge**：`/research --type` 与 plan `research_type` 对齐；`research_report` 可选进 plan 上下文；`profile:research` matrix 证据；**不**替换 session_agent Beta 默认。

## 交付

| 项 | 证据 |
| --- | --- |
| `design_intel_research_bridge.py` | `load_research_report` · `apply_research_report_bridge` · `run_design_intel_research_band` |
| `design_intel_contract` | `map_research_cli_type_to_plan_type` · `research_cli_type` 传播 |
| `plan_command` | `run_id` 复用 · user_progress「Research report linked to plan」 |
| schema | `research_cli_type` · `research_report_ref` on goal_spec |
| matrix | `profile:research` ← `design_intel_research_band` |
| 闸门 | `phase6b_design_intel_research_gate.json` |

## green_checks

```powershell
pytest tests/integration/test_phase6b_design_intel_research_gate.py -q
pytest tests/unit/test_design_intel_contract.py -q
pytest -q
```

## 纪律确认

- Beta 默认 **session_agent** 未变
- CLI **`parallel_writes` 默认 false**
- 未引入 12 Agent 新类

## 下一波段

**S37** — Long Horizon Completion Contract（见 `docs/zh/plans/asteria-holistic-S37-S40.md`）
