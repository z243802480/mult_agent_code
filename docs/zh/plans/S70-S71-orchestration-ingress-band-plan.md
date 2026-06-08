# S70–S71 编排入口带综合计划

**日期**：2026-06-07  
**状态**：**closed · S70–S73 已签字，后续以 S74 Beta convergence 为执行入口**
**前置**：S69 adversarial verifier ✅ · L3 全链路 maintainer 带 ✅  
**依据**：[`S64-W4-W5-reference-alignment-20260607.md`](../reports/S64-W4-W5-reference-alignment-20260607.md) 综合评估结论

---

## 1. 目标

闭合 CC 对齐评估中的三条 P0/P1 缺口：

| Slice | 目标 | 验收 |
| --- | --- | --- |
| **S70** | Strong ingress：`run_dynamic_orchestration` catalog + real-model eval | hit_rate ≥ 0.8 / 8 cases |
| **S71** | Thread 主路径 workflow 可观测性（紧凑卡片） | smoke + 单测 |
| **S72–S73** | live provider worker · Beta `parallel_writes` DecisionPoint | ✅ 已签字 |

**硬约束不变**：`parallel_writes` 默认 false；L3 ingress 仅 maintainer gray 可用。

---

## 2. S70 设计

### 2.1 Catalog

新增 capability `run_dynamic_orchestration`：

- **available** 当 `orchestration_dynamic_workflows_gray=true` 且 workspace initialized
- **layer** `L3_orchestrator`
- **studio_mode** `orchestration`（maintainer band；Studio 保留 route 证据）

### 2.2 Router

- strong prompt + `catalog_selection_guidance` 补充 L3 选用原则
- 小改/单 scope → `cold_goal_execute` / `session_continue_execute`
- 多 phase manifest + checkpoint/resume → `run_dynamic_orchestration`

### 2.3 Eval

- `benchmarks/orchestration_dynamic_ingress_gate.json`
- `scripts/orchestration_dynamic_ingress_pulse.py --real`
- CI：`tests/unit/test_orchestration_dynamic_ingress.py`（fake strong router）

---

## 3. S71 设计

- `WorkflowMonitorCompact` 嵌入 Thread（RuntimeSnapshot 下方）
- 显示 steps / merge / verifier / checkpoint 一行摘要
- Inspector 保留完整 `WorkflowMonitorPanel`

---

## 4. 后续交付（S72–S73 已完成）

| 项 | 说明 |
| --- | --- |
| Live provider worker | ✅ `orchestration_dynamic_live` 接真实 model |
| Studio orchestration 执行 | ✅ CLI `orchestration run --manifest` |
| DecisionPoint 0007 | ✅ `parallel_writes` 显式 opt-in |
| North Star swarm | S7 gate 后 Phase 3+ |

---

## 5. 验证命令

```powershell
pytest tests/unit/test_orchestration_dynamic_ingress.py tests/unit/test_orchestration_router.py -q
node studio/scripts/s71-thread-workflow-smoke.mjs
python scripts/orchestration_dynamic_ingress_pulse.py --root .
python scripts/orchestration_dynamic_ingress_pulse.py --root . --real
```
