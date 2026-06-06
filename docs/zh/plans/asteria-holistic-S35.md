# Asteria 整体推进计划（S35 — Phase 6 入口）

**日期**：2026-06-06  
**前置**：S34 phase5f 已签字（[`S34-production-gray-signoff-20260606.md`](../reports/S34-production-gray-signoff-20260606.md)）

---

## 1. 全局坐标

```text
已闭合
  S0–S34  Harness MVP · Beta · 蜂群 · production gray 出口

本波段（S35）
  ① research_type / goal_type 进 plan 契约（最小字段）
  ② `/research` 或 plan 路径对 doc/creative 类型的可见进度
  ③ phase6 入口闸门 + matrix 对齐

仍 defer
  12 Agent 独立类
  CLI 默认 parallel_writes
  全类型 Design Intel 产品化（S36+）
```

---

## 2. Slice 分解

| ID | 名称 | 交付 |
| --- | --- | --- |
| **S35** | Design Intel pilot | brief · phase6 gate json · 契约测试 · 一条 demo 路径 |

---

## 3. 成功标准

- [ ] `phase6_design_intel_gate.json` 与 ACTIVE_SLICE = S35
- [ ] plan/goal_spec 可持久化 `research_type`（schema 向后兼容）
- [ ] 至少一条 fake-provider doc/creative 场景进 user_progress 主路径
- [ ] doc contracts 三源同步

---

## 4. 验证

```powershell
pytest tests/integration/test_phase6_design_intel_gate.py -q
python scripts/steady_iteration_check.py --root . --skip-b6
```
