# Asteria 整体推进计划（S31–S33）

**日期**：2026-06-06  
**原则**：每个 Slice 必须闭合 **North Star 主链** 或 **全局闸门/验证矩阵** 的一环；禁止孤立 maintainer 脚本或单文件 patch。

---

## 1. 全局坐标（S30 之后）

```text
已闭合
  S0–S7   MVP Harness + Studio
  S8–S17  续作 / North Star / session_agent / 稳态
  S18–S30 蜂群 sandbox 链 → execute policy 透传

仍缺（Phase 5 出口）
  ① 两条 harness 路径的统一场景证明（execute 并行 vs subagent 计划）
  ② 与 runtime_validation_matrix / 维护者脉搏 对齐（非第三套脚本）
  ③ real provider 签字位（optional，走既有 validation-run 栈）
  ④ 生产 gray DecisionPoint（S32）
  ⑤ Beta friction 收敛（S33，轨道 A）
```

---

## 2. Slice 分解

| ID | 名称 | 全局挂钩 | 交付 |
| --- | --- | --- | --- |
| **S31** | 统一场景闸门 | `runtime_validation_matrix` + `phase5d` + `swarm_holistic_check` | `swarm_scenario_audit.py`、场景 json、一条维护者脉搏 |
| **S32** | Gray DecisionPoint | `validation-run` / flag rollout 栈 | DecisionPoint 模板 + rollback 演练契约 |
| **S33** | Beta friction | Phase 4 稳态 / B6 | decide→resume 链收敛 |

**S31 不做**：新 CLI、默认打开 parallel_writes、fake-only 新测试文件堆叠。

---

## 3. Phase 5 两条路径（S31 核心模型）

| 路径 | 触发 | 证据 |
| --- | --- | --- |
| **execute_parallel_disjoint** | `ExecuteCommand(parallel_writes=True)` | `parallel_safe_batch_selection`、candidates、agent_run_graph |
| **subagent_swarm_planning** | subagent 分解 | `swarm_execution_plans.jsonl` + `subagent_child_plans.jsonl` |

`swarm_scenario_audit` 对 run_dir **识别路径并审计**，供 gate-status / validation 摘要复用。

---

## 4. 维护者脉搏（S31 起 · 一条命令）

```powershell
python scripts/swarm_holistic_check.py --root . --skip-studio
```

内含：steady（skip-b6）→ phase5d 场景 → integration → rollout（skip-probe）。

real provider 签字：**optional**，见 `phase5d_swarm_scenario_gate.json` → `real_provider_signoff`。

---

## 5. 成功标准

- [x] `runtime_validation_matrix` 含 `swarm_disjoint_evidence`
- [x] execute 并行 + subagent 路径均过 `swarm_scenario_audit`
- [x] 三源 ACTIVE_SLICE 同步
- [x] Beta 默认 session_agent 不变
- [x] S32 gray DecisionPoint + rollback drill（`phase5e`）
- [x] S33 friction 契约 + Studio replan→continue
