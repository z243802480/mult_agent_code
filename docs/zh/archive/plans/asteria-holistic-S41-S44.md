# Asteria 整体推进计划（S41–S44 — Phase 8 Long Task Intelligence）

**日期**：2026-06-06  
**前置**：Phase 6 Long Horizon S37–S40 已闭合

> **命名说明**：研发总计划中的 **Phase 7 = Beta 用户路径（已关闭）**。本波段为 **Phase 8**，承接 S37 signoff 中 defer 的 ML judge 与 S40 defer 的 remote background。

---

## 1. 全局坐标

**长任务目标框架**（North Star / slice / task 三层）：[`LONG_TASK_GOAL_FRAMEWORK.md`](./LONG_TASK_GOAL_FRAMEWORK.md)

```text
已闭合
  S0–S40  Harness · Beta · 蜂群 · Long Horizon

本波段（S41–S44）
  ① S41  ML-Assisted Slice Completion Judge — 规则 + 可选 model veto
  ② S42  Long Horizon Handoff Compact — session 级 handoff 压缩投影
  ③ S43  Remote Background Run Adapter — cloud VM 接口层（真 VM defer）
  ④ S44  Phase 8 band signoff + maintainer pulse

仍 defer
  12 Agent 独立类
  CLI 默认 parallel_writes
  真 cloud VM 实例编排
```

---

## 2. Slice 分解

| ID | 名称 | 核心交付 | 状态 |
| --- | --- | --- | --- |
| **S41** | ML slice completion judge | `slice_completion_judge.py` · policy flags · accept 集成 | ✅ |
| **S42** | Long horizon handoff compact | `long_horizon_handoff.json` · status 投影 · Studio | ✅ |
| **S43** | Remote background adapter | `--remote` stub · registry deferred | ✅ |
| **S44** | Phase 8 band signoff | `phase8_maintainer_smoke.py` | ✅ |

---

## 3. S41 任务清单

1. [x] brief + `phase8a_slice_completion_judge_gate.json`
2. [x] `slice_completion_judge.py` + fake purpose
3. [x] `north_star.slice_completion_policy.enable_model_judge`
4. [x] accept 收尾集成 + `model_judge` 持久化
5. [x] integration + unit tests 全绿

---

## 6. S42 任务清单

1. [x] brief + `phase8b_long_horizon_handoff_gate.json`
2. [x] `long_horizon_handoff.py` + schema
3. [x] accept 收尾 persist + `long_horizon.handoff_compact`
4. [x] Studio Inspector 展示

---

## 7. S43 任务清单

1. [x] brief + `phase8c_remote_background_adapter_gate.json`
2. [x] `remote_background_adapter.py` + `--remote` CLI
3. [x] registry `deferred` + projection capabilities

---

## 8. S44 任务清单

1. [x] `phase8_long_task_intelligence_gate.json`
2. [x] `scripts/phase8_maintainer_smoke.py`
3. [x] band signoff 文档

| 机制 | Asteria slice |
| --- | --- |
| Claude completion judge（小模型） | S41 |
| compact / handoff 摘要 | S42 |
| Gateway 异步 background RPC | S43 |

---

## 10. 验证

```powershell
python scripts/phase8_maintainer_smoke.py --root .
pytest tests/integration/test_phase8a_slice_completion_judge_gate.py -q
pytest tests/integration/test_phase8b_long_horizon_handoff_gate.py -q
pytest tests/integration/test_phase8c_remote_background_adapter_gate.py -q
pytest -q
```
