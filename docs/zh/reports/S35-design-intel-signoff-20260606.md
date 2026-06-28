# S35 Design Intelligence Pilot — Signoff 2026-06-06

## 目标

闭合 Phase 6 **入口试点**：`research_type` 进 plan / goal_spec / task 契约；fake-provider doc/creative 场景走 user_progress 主路径；**不**替换 session_agent Beta 默认。

## 交付

| 项 | 证据 |
| --- | --- |
| `design_intel_contract.py` | 推断 + 传播 `documentation` / `creative` / `research` |
| `goal_spec` / `task` schema | 可选 `research_type`（向后兼容） |
| `plan_command` + `goal_spec_agent` | persist 与 user_progress `data.research_type` |
| `phase6_design_intel_gate.json` | Phase 6 入口闸门 |
| 行为测试 | `test_phase6_design_intel_gate.py` · `test_design_intel_contract.py` |

## green_checks

```powershell
pytest tests/integration/test_phase6_design_intel_gate.py -q
pytest tests/unit/test_design_intel_contract.py -q
pytest tests/unit/test_documentation_contracts.py -q
pytest -q
```

## 纪律确认

- Beta 默认 **session_agent** 未变
- CLI **`parallel_writes` 默认 false**
- 未引入 12 Agent 新类
- `/research --type` 全类型产品化 **defer 至 S36**

## 下一波段

**S36** — Design Intel research bridge（见 `docs/zh/plans/asteria-holistic-S36.md`）
