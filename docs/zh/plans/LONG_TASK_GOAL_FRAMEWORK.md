# 长任务目标框架（Long Task Goal Framework）

**版本**：1.0.0  
**状态**：current — 与 Phase 6–8 实现对齐  
**日期**：2026-06-06

本文定义 Asteria **长任务 / North Star** 的产品目标与工程映射，对标 Claude Code `/goal`、OpenCode utw、行业「planner / worker / judge」分层，**不复制专有 UI 或实现**。

---

## 1. 三层目标（不要混写）

| 层 | 用户说什么 | Asteria 持久化 | 谁决定「完成」 |
| --- | --- | --- | --- |
| **North Star** | 季度/年度方向 | `.asteria/north_star.json` | milestone + slice 契约 |
| **Run / Slice** | 一次可验收的增量 | `.asteria/runs/{id}/` | accept + slice_completion_eval |
| **Task** | plan 内单步 | `task_plan.json` | verify + task completion_contract |

**纪律**：

- North Star **不 silent auto execute**；队列只给 Continue 提示（S38）。
- Run 级完成 ≠ verify 通过 ≠ review pass ≠ accept；S37 独立 evaluator。
- Task 级完成仍走 `task_contract.check_completion_contract`（execute 内）。

---

## 2. 对标 Claude Code / 主流做法

| 机制 | Claude Code / 行业 | Asteria 映射 | 状态 |
| --- | --- | --- | --- |
| 可测试完成条件 | `/goal` + Stop hook + 小模型 evaluator | `slice_completion_policy` + S41 model judge | S37 ✅ · S41 ✅ |
| 规则优先、模型 veto | evaluator 与 worker 分离 | 规则未过不调 model；规则过 model 可 veto | S41 ✅ |
| 每 turn 后判定 | 每 turn 后 Haiku 判 condition | accept 后 slice 判定 + supervised loop 每 slice accept | S37/S39 ✅ |
| 用户显式继续 | 非每步打断，milestone 级询问 | goal_queue Continue + `--toward-north-star` | S38/S39 ✅ |
| 中断 / kill | `/goal clear`、权限 | `.asteria/STOP` + budget hard-stop | S39 ✅ |
| 后台长跑 | durable run / workflow | local background + remote stub（S43） | S40/S43 ✅ |
| 上下文压缩 / handoff | compact、CLAUDE.md、PLAN.md | `long_horizon_handoff.json` + active_goal_memory | S42 ✅ |
| 动态 workflow / 蜂群 | parallel subagents + 外部编排 | Phase 5 swarm（maintainer gray，CLI 默认 off） | S18–S34 ✅ |

**不照搬**：Claude 的 `/goal` 每 turn 自动续跑；Asteria 默认 **监督式**（accept/review  per slice），与 `reviewed_auto` 产品边界一致。

---

## 3. 完成判定栈（从外到内）

```text
North Star milestone
  └─ slice_completion_eval（S37）
       ├─ requires_accepted_run
       ├─ requires_review_pass
       ├─ requires_all_tasks_done（可选）
       ├─ min_review_score ← eval_report.overall.score
       └─ enable_model_judge（S41，可选 veto）
  └─ goal_queue mark_done + Continue 提示（S38）

Run accept
  └─ review pass + promotion settled

Execute / verify
  └─ task completion_contract per task
```

**user_progress 叙事**：accept 后必须有「本 slice 完成判定」事件（有 North Star 时）；无 North Star 时不写噪音。

---

## 4. 推荐 North Star 策略（维护者模板）

```json
{
  "slice_completion_policy": {
    "requires_accepted_run": true,
    "requires_review_pass": true,
    "requires_all_tasks_done": false,
    "min_review_score": 0.8,
    "enable_model_judge": false,
    "model_judge_tier": "medium"
  }
}
```

- **默认**：仅规则（`enable_model_judge: false`），零额外 model 成本。
- **长周期 / 易漂移**：开启 `enable_model_judge`，用于 milestone 级 veto。
- **编程 slice**：可开 `min_review_score`，与 benchmark 分数对齐。

---

## 5. 用户路径（长任务）

```text
init [--north-star-title …]
  → goal "本 slice 目标" [--toward-north-star --max-slices N]
  → review → accept
  → status / Studio：last_slice_completion + Continue 提示
  → 可选：goal --background · asteria background status
  → 监督循环：.asteria/STOP 中断
```

Maintainer 脉搏：

```powershell
python scripts/long_horizon_maintainer_smoke.py --root .
python scripts/steady_iteration_check.py --root . --skip-b6
```

---

## 6. Phase 8 补全项（相对 Claude 仍缺）

| 缺口 | 计划 Slice | 说明 |
| --- | --- | --- |
| handoff / compact 投影 | S42 | 跨 session 摘要，减 goal drift | ✅ |
| remote background | S43 | registry stub；真 VM defer | ✅ |
| 每 turn evaluator（非 accept 后） | defer | 与 supervised loop 成本权衡；非 MVP |

---

## 7. 文档与代码真源

| 用途 | 路径 |
| --- | --- |
| 执行计划 | [`研发总计划.md`](../研发总计划.md) |
| 短快照 | [`当前状态与路线.md`](../当前状态与路线.md) |
| North Star 数据 | [`schemas/north_star.schema.json`](../../schemas/north_star.schema.json) |
| Slice briefs | [`benchmarks/reference_briefs/S37–S41*.md`](../../benchmarks/reference_briefs/) |
| 活跃波段计划 | [`asteria-holistic-S41-S44.md`](./asteria-holistic-S41-S44.md) |
| 历史 RFC | [`NORTH_STAR_RFC.md`](./NORTH_STAR_RFC.md)（已实现，只追溯） |
