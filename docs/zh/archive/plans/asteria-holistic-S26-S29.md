> **非当前依据（archive）** — 见 `archive/plans/README.md` 与现行 `plans/LONG_TASK_GOAL_FRAMEWORK.md`.

# Asteria 整体推进计划（S26–S29）

**日期**：2026-06-06  
**定位**：在 **North Star（长任务 Harness）** 与 **Phase 5（蜂群 sandbox）** 之间对齐，避免只堆 maintainer 脚本或只修 Studio 局部。

---

## 1. 整体坐标（现在在哪）

```text
产品主体（已证明）     Goal → Plan → Execute → Verify → Review/Accept
Beta 默认层（S17）     session_agent — 单会话 CC 级 loop
Harness 层（S18–S25）  worker spawn → candidate → merge dry-run → maintainer probe
仍缺的一环             orchestrator 计划 **进入主链证据** + Studio **可读调度语义**
```

**North Star 对齐**：用户给目标 → harness 分解/委托 → 可审计证据 → 合并/晋升 — wave2 只在 maintainer 隔离目录证明了后半段；**主 run 里还看不到 swarm 计划**。

**非目标（本波段不碰）**：12 Agent 新类、CLI 默认 parallel_writes、execute/run 重构、无 brief 新命令。

---

## 2. 双轨并行（避免走偏）

| 轨道 | 目标 | 本波段 Slice | 精力占比 |
| --- | --- | --- | --- |
| **A — Beta 稳态** | 内测用户路径可靠 | S29 friction 收敛（decide→resume 已部分修复） | 30% |
| **B — Phase 5 蜂群** | sandbox 证据进主链 | S26–S28 | 70% |

**纪律**：每个 Slice 必须回答 — 「这对 Goal→Verify 主链或蜂群 merge 链增加了什么可审计能力？」否则不做。

---

## 3. Slice 分解（S26–S29）

| ID | 名称 | 交付 | 整体意义 |
| --- | --- | --- | --- |
| **S26** | Agent loop 证据接入 | `swarm_execution_plans.jsonl` + `persist_swarm_execution_plan` 挂接 `persist_subagent_child_plan_for_execution` | orchestrator 计划进入 **真实 run 证据**，非孤立 maintainer 脚本 |
| **S27** | Studio 调度语义 | worker_summary 暴露 `scheduling_mode` / `fake_path`；WorkerProgressBar 徽章 | 用户/维护者 **一眼区分 fake_serial vs parallel**，不误导为「已真并行」 |
| **S28** | 主链集成测试 | agent loop disjoint 场景 → swarm_execution_plans + audit | 证明 Layer0 loop 与 Layer1 harness **同 run_dir 共存** |
| **S29** | Wave3 签字 + 稳态脉搏 | `phase5c_swarm_integration_gate.json`；更新综合路线图 | 关闭「只有 maintainer 孤岛」阶段 |

**依赖**：S25 → S26 → S27 → S28 → S29

---

## 4. 仍 defer（S31+）

- real provider 双 worker 编程 case（非 synthetic）
- 生产 `real_disjoint_write_workers` 打开 + 自动 merge
- Design Intelligence Phase 6

## 4b. S30（execute policy 透传）✅

- `execute_command` append-only：`policy=context.policy`
- `subagent_planner` 透传 policy → spawn hints
- 集成测试：`test_execute_swarm_policy_passthrough.py`

---

## 5. 维护者脉搏（wave3 起）

```powershell
python scripts/steady_iteration_check.py --root . --skip-b6
python scripts/swarm_flag_rollout_check.py --root . --skip-probe
python scripts/swarm_integration_check.py --root .    # S28 新增
```

---

## 6. 成功标准（S29 退出）

1. 任意 agent loop subagent 分解产生 `swarm_execution_plans.jsonl`  
2. Studio run-detail 显示 scheduling 徽章（fake_serial / parallel / serial）  
3. phase5c 闸门 + 三源 ACTIVE_SLICE 同步  
4. Beta 主路径仍为 session_agent（回归 smoke 绿）
