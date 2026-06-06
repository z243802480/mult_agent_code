# Asteria 整体推进计划（S37–S40 — Long Horizon 监督续跑）

**日期**：2026-06-06  
**前置**：S36 已签字（[`S36-design-intel-research-bridge-signoff-20260606.md`](../reports/S36-design-intel-research-bridge-signoff-20260606.md)）

---

## 1. 全局坐标

```text
已闭合
  S0–S36  Harness · Beta · 蜂群 · production gray · Design Intel bridge

本波段（S37–S40）
  ① S37  Long Horizon Completion Contract — 独立 slice 完成判定
  ② S38  North Star Goal Queue — bounded 目标队列 + Continue 提示
  ③ S39  Supervised Goal Loop — toward-north-star bounded 续跑
  ④ S40  Local Background Run — 本地 durable subprocess（cloud defer）

仍 defer
  12 Agent 独立类
  CLI 默认 parallel_writes
  真 cloud VM background run
  silent auto execute（须用户 Continue）
```

---

## 2. Slice 分解

| ID | 名称 | 核心交付 | 状态 |
| --- | --- | --- | --- |
| **S37** | Long Horizon Completion Contract | `slice_completion_policy` · `long_horizon_completion.py` · accept 后 evaluator · user_progress | ✅ |
| **S38** | North Star Goal Queue | `goal_queue.json` · seed from milestones · accept Continue 提示 | ✅ |
| **S39** | Supervised Goal Loop | `--toward-north-star --max-slices N` · budget · `.asteria/STOP` | ✅ |
| **S40** | Local Background Run | subprocess durable run · Studio 徽章 | ✅ |

---

## 3. S37 任务清单

1. [x] brief + `phase6c_long_horizon_completion_gate.json`
2. [x] `north_star.schema.json` 可选 `slice_completion_policy`
3. [x] `long_horizon_completion.py`：`evaluate_slice_completion` · persist · status 投影
4. [x] `accept_command` 收尾：evaluator + user_progress「本 slice 完成判定」
5. [ ] 行为测试 `test_phase6c_long_horizon_completion_gate.py` + unit tests

---

## 4. S38 任务清单

1. [x] brief + `phase6d_goal_queue_gate.json`
2. [x] `goal_queue.schema.json` + `GoalQueueStore`
3. [x] accept 后 mark done + Continue 提示（非 silent auto goal）
4. [ ] 行为测试 `test_phase6d_goal_queue_gate.py`

---

## 5. S39 任务清单

1. [x] brief + `phase6e_supervised_goal_loop_gate.json`
2. [x] CLI flag `--toward-north-star --max-slices N` on run/goal entry
3. [x] slice 内 goal→execute→verify→review→accept 链 + kill file
4. [x] budget 硬停与 user_progress 监督叙事

---

## 6. S40 任务清单

1. [x] brief + `phase6f_local_background_run_gate.json`
2. [x] 本地 subprocess wrapper + run 状态持久化
3. [x] Studio 徽章/Inspector 证据（非第二 runtime）
4. [x] 真 cloud VM **defer**

---

## 7. 验证

```powershell
pytest tests/integration/test_phase6c_long_horizon_completion_gate.py -q
pytest tests/integration/test_phase6d_goal_queue_gate.py -q
pytest tests/unit/test_long_horizon_completion.py -q
pytest tests/unit/test_goal_queue.py -q
pytest -q
```

---

## 8. 竞品映射（摘要）

| 机制 | Asteria slice |
| --- | --- |
| 独立 completion evaluator | S37 |
| Planner bounded goal queue | S38 |
| Supervised multi-slice loop | S39 |
| Background durable run | S40 |
