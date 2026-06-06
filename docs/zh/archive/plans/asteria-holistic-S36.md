> **非当前依据（archive）** — 见 `archive/plans/README.md` 与现行 `plans/LONG_TASK_GOAL_FRAMEWORK.md`.

# Asteria 整体推进计划（S36 — Phase 6 Research Bridge）

**日期**：2026-06-06  
**状态**：✅ 已签字 — [`S36-design-intel-research-bridge-signoff-20260606.md`](../reports/S36-design-intel-research-bridge-signoff-20260606.md)  
**下一波段**：[`asteria-holistic-S37-S40.md`](./asteria-holistic-S37-S40.md)

---

## 1. 全局坐标

```text
已闭合
  S0–S35  Harness · Beta · 蜂群 · production gray · Design Intel pilot

本波段（S36）
  ① /research --type 与 plan research_type 映射
  ② research_report 可选进 plan 上下文
  ③ phase6b 闸门 + matrix profile:research

仍 defer
  12 Agent 独立类
  CLI 默认 parallel_writes
  全量 Design Intel Studio 产品面（S37+）
```

---

## 2. Slice 分解

| ID | 名称 | 交付 |
| --- | --- | --- |
| **S36** | Design Intel research bridge | brief · phase6b gate · 契约测试 · 一条 demo 路径 |

---

## 3. 成功标准

- [x] `phase6b_design_intel_research_gate.json` 与 ACTIVE_SLICE = S36
- [x] `/research --type` 输出可映射到 plan 契约（与 S35 pilot 类型并存或扩展）
- [x] 至少一条 fake-provider research → plan 场景进 user_progress
- [x] doc contracts 三源同步

---

## 4. 验证

```powershell
pytest tests/integration/test_phase6b_design_intel_research_gate.py -q
python scripts/steady_iteration_check.py --root . --skip-b6
```
