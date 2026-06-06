# Phase 5 第二波：真实并行写灰度（S22–S25）

**日期**：2026-06-06  
**前提**：S18–S21 蜂群入口已签字（`phase5_swarm_gate.json`）  
**原则**：Beta 默认仍为 `session_agent`；真实并行仅 **maintainer 灰度**；不 refactor `execute_command.py` / `run_command.py`

---

## 1. 目标

在 **不打开 CLI 默认 `parallel_writes`** 的前提下，完成：

1. `real_disjoint_write_workers` 的 **就绪评估 → 启用演练 → 回滚审计** 闭环  
2. maintainer 隔离环境下的 **真实 parallel disjoint probe**（2 worker + candidate + dry-run）  
3. orchestrator **薄层 hook**（child_plan → spawn → coordinator），供后续 execute 层接入  
4. Phase 5 wave2 闸门签字

---

## 2. Slice 分解

| ID | 名称 | 交付 | 用户/demo | green_checks |
| --- | --- | --- | --- | --- |
| **S22** | Flag rollout 契约 | `swarm_flag_rollout.py`、rollback 审计、`phase5b_swarm_rollout_gate.json` | 维护者评估 flag 可否启用/回滚 | `test_swarm_flag_rollout.py`、`swarm_flag_rollout_check.py` |
| **S23** | Real disjoint probe | `run_maintainer_real_disjoint_probe` | 2 worker **parallel**（非 fake_serial）+ export + dry-run | `test_phase5b_swarm_rollout_gate.py` |
| **S24** | Orchestrator hook | `swarm_orchestrator.py` | child_plan → spawn plan → coordinator 选择 | `test_swarm_orchestrator.py` |
| **S25** | Wave2 签字 | signoff 报告、RFC 更新 | maintainer 一键 bundle | `swarm_flag_rollout_check.py` 全绿 |

**依赖链**：S21 → S22 → S23 → S24 → S25

---

## 3. 仍关闭（wave2 不突破）

| 项 | 状态 |
| --- | --- |
| CLI `parallel_writes` 默认 | `false` |
| Beta 主路径 | `session_agent` |
| `execute_command.py` refactor | 禁止 |
| 12 Agent 新类 | defer Phase 6+ |
| 生产 workspace 自动 merge | 需 DecisionPoint + 真人签字 |

---

## 4. 维护者脉搏（wave2 日常）

```powershell
# 日常（无 Studio）
python scripts/swarm_flag_rollout_check.py --root . --skip-probe

# 签字前（含 real disjoint probe）
python scripts/swarm_flag_rollout_check.py --root .
python scripts/swarm_maintainer_gray_check.py --root . --skip-studio
pytest tests/integration/test_phase5b_swarm_rollout_gate.py -q
```

---

## 5. 退出条件（S25）

- [ ] flag rollout 就绪/回滚审计有单元 + 集成测试  
- [ ] maintainer real disjoint probe：`scheduling_mode=parallel`、`fake_path=false`  
- [ ] orchestrator hook 可消费 subagent child_plan  
- [ ] `phase5b_swarm_rollout_gate.json` wired + signoff  
- [ ] 三源 `ACTIVE_SLICE` 同步  

---

## 6. 下一波段（S26+，defer）

- execute 层 **append-only** 接入 orchestrator（不 refactor DO_NOT_TOUCH）  
- real provider 2-worker 编程 case（非 synthetic gray）  
- Studio：parallel worker 时间线区分 fake vs real  
- S16 friction 收敛（decide→resume）并行轨道  
