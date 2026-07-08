# ADR-0022：立真身脊梁落地 —— 模型驱动专家集群骨架 + FSM 认知脚手架删除（执行 ADR-0016）

**状态**：Accepted
**日期**：2026-07-08
**关系**：**执行落地** [ADR-0016](0016-model-driven-cognition-conformance.md)（认知归模型 / 边界归状态的可执行判据）；建立在 [ADR-0010](0010-open-agent-loop-and-evaluation-boundaries.md) / [ADR-0015](0015-session-loop-is-product-architecture.md) 之上；与 [ADR-0017](0017-goal-level-replan-ring-within-goal.md)（goal-level replan 环）并存。不 supersede 上述任何一条。

## 背景

ADR-0016 给了"什么算把认知写成状态机"的三分类判据（§1 认知归模型 / §2 边界归状态 / §3 证据不 auto-gate），并钉了"第一刀"——溶解 auto_repair 里的 `repair`/`replan`-as-command。但 ADR-0016 停在**判据 + 单刀**级别：它点名的漂移点（`agent_loop_decision.py:202` 的 `recommended_command_for_next_action`、`execute_command.py` 的 `_handle_auto_repair_round`、`review_agent._overall` 算分 gate）当时**仍在代码里**。

2026-07-07 用户令"彻底重塑体系·用 LLM 能力驱动·参考成熟产品·打破冻结·先骨架再血肉"，经多轮澄清 + 四路代码审计 + 两路外部调研，批准了**模型驱动专家集群**蓝图（计划文件 `.claude/plans/purring-fluttering-beaver.md`），并给出 DecisionPoint：**全授权分阶段删 FSM 核心（含 DO_NOT_TOUCH + ~78 FSM 测试），此授权显式覆盖 Triage Lock 与冻结条款（仅限本重塑）**。

本 ADR 记录该蓝图 **Part A（骨架 + FSM 删除）已 shipped 的落地形态**，把 ADR-0016 的判据从"点名漂移"变成"漂移已删、脊梁是唯一路径"。工作分 RA1–RA7b 分片推进，全程真机验证 + 逐字节可回退（tag `pre-fsm-delete`）。

## 支配原则（重塑定海针，本 ADR 成文固化）

> **要让一件事"可选"，就把它放进「模型的决策空间」（工具 / 技能 / 模式 / 建议），而不是放进「harness 的控制流」（if/else 阶段跳转）。harness 只焊死「边界」——权限、沙箱、预算保险丝、隔离、持久化-resume、人审、done 的对外副作用；其余全部让模型路由。**

删 FSM 不是丢方法论，而是把它**强制**的东西（repair/replan/verify 阶段）搬进"可选形态"（技能 / todo / 建议 / hook 续跑守门），只去强制、不减配。

## 决策：落地的五层架构（全部映射到现存件）

```
① 脊梁      立真身单循环 model→tool→observation→model（唯一控制分支；认知全在模型）
② 方法论层  可选技能(investigate/debug/minimal-change/verify/plan/retrospect) + todo 自组织 + 触发条件式系统提示建议 + 每步 reminder 回灌
③ 专家集群  spawn_subagent(role=…)：主脑运行时按需派专家；专家=profile(人格+方法论技能包+工具面+tier+隔离后端)；只回摘要 observation
④ 护栏      ToolExecutionGateway(权限/沙箱/证据) · candidate/sandbox 隔离 · budget 保险丝 · 并发上限 · merge_gate · 人审 approval-pause · 正确性 gate(证据型 DoD)
            + 控制型 Hook 总线(task/turn-start 预载&reminder · pre_final 续跑守门 · 把②方法论层可靠串起来，自己不做认知)
⑤ 证据/持久 JSONL(task_execution_evidence/validation_results/tool_calls/artifacts) · correctness_eval(真实通过率 DoD) · north_star(集群里程碑·stub) · resume
```

**①②③ 全在模型决策空间（可选、按需）；④⑤ 是 harness 焊死的边界。** 这正是 ADR-0016 §1/§2/§3 三分类的架构落地。

### 落地件（RA1–RA7b，均已推 main）

- **① 脊梁**：`core/model_driven_turn.py::run_model_driven_turn` 是 `execute_command._execute_task` 的**唯一路径**（RA7a 翻默认 → RA7b slice3f 删 `for round_index` 循环本体，立真身转正）。
- **② 方法论层**：`skills/bundled/{investigate,debug,minimal-change,verify,plan,retrospect}` 渐进式披露；`tools/todo_tools.py` 自组织；系统提示改触发条件式建议；弱模型脚手架旋钮做成 tier 参数（RA2）。
- **② 控制型 Hook**：`core/runtime_hooks.py::RuntimeHookManager` 从纯观察型升为控制型（handler 可注入 additionalContext / 阻断 / 强制续跑），接进立真身 `on_event`；`pre_final` 续跑守门只查证据边界（expected_artifacts / verification / scope）、把控制交回模型，不做认知（RA2）。
- **③ 专家集群**：`core/expert_registry.py`（coder/diagnostic/reviewer/researcher profile）+ `_SubagentAwareToolRunner` 拦截 `spawn_subagent` 递归跑有界立真身子循环、只回摘要（RA3）；`core/worker_executor.py` 后端可插拔（LocalExecutor 实 / CloudSessionExecutor stub·云实现留 Part B 直插，RA4）。
- **④ 正确性 gate（证据型 DoD）**：脊梁完成判定复用 `task_contract.check_completion_contract`——契约不满足即 `blocked`（证据边界确定性否决"完成"，像预算保险丝那样覆盖上报状态，不替模型做认知，符合 ADR-0016 §3-允许 + nuance #1，RA7b-4）。
- **④ 人审 approval-pause**：脊梁跑一批工具前先过注入的 `approval_gate`（复用 `create_policy_decision_if_needed`）——命中 shell denylist 且无 `approve_once` 就整批停手、留 pending DecisionPoint，resume 经网关 `context_with_approval` 自动放行（RA7b slice3d）。
- **⑤ 证据**：脊梁作一等证据生产者，落 `task_execution_evidence.jsonl` / `validation_results.jsonl` / `tool_calls.jsonl` / `artifacts.jsonl`，供 review 恢复判定、replan、最终报告、发布 gate 消费（RA7b slice3a/3b/3c）。

### 删除的 FSM 认知脚手架（详见 `已删除与已替代登记.md` §3.2）

探针注入器 → subagent-child 递归循环 → auto-repair/replan 环 → `for round_index` 循环本体 → flag/bridge fixture → runtime-OS 验收子系统（迁脊梁）→ 全部数据结构（`execution_action` / `agent_loop_decision` / `agent_loop_executor` / `agent_loop_observation` / `agent_loop_runner` / `execution_action_preparer`）。**立真身脊梁是唯一执行路径，发布 gate 验证脊梁（生产真身）而非已删 FSM。**

## 后果

- **ADR-0016 的三处漂移点全部消解**：`recommended_command_for_next_action`（agent_loop_decision 已删）、`_handle_auto_repair_round`（round 循环已删，repair 由脊梁涌现式承接）、`review._overall` 算分 gate（随 FSM review 路径退休，正确性判决改由 `correctness_eval` 真实通过率证据 + 显式 review 动作）。**漂移从此是"回归"不是"特性"。**
- **能力不减配**：FSM 四道 done-gate（验证失败 / 缺验证 / 无改动工件 / 越权写无产物）原样进脊梁正确性 gate；repair/replan 由脊梁失败→observation→模型自重试承接；goal-level replan 环（ADR-0017）在 run 层原样保留；人审 scope 归 goal-level replan DecisionPoint（AGENTS.md §11）。
- **DO_NOT_TOUCH 触碰授权**：本 ADR 范围内对 `execute_command.py` / `run_command.py` / `gate_status_command.py` / `real_model_acceptance.py` 的改动，由用户 2026-07-07 重塑解冻显式授权（对应 ADR-0016 §后果 的 DO_NOT_TOUCH 触碰授权延伸）。仅限重塑纠偏，不做无关重构。
- **Part B 仍冻结待用户拍板**：真并发专家（disjoint-write parallel_writes 全局默认）、`CloudSessionExecutor` 实现、高级 scheduler、North Star flesh + 前端侧栏——接口已在 RA4/RA5 焊死留 stub，但放量是自主性/并发策略 DecisionPoint，须用户单独解锁（AGENTS.md §2 冻结条款 + S77 审计 DecisionPoint 不变）。
- **文档与代码不得再把固定状态机、per-action 命令弹射或算分 gate 描述为认知路径**（延续 ADR-0016）。

## 回滚或替代条件

- tag `pre-fsm-delete` 为干净回退点；每 slice 独立提交，可逐字节回退。
- 按 ADR-0010 §4 用 Golden Tasks 配对对比：若脊梁在成功率 / P50-P90 耗时 / 成本 / 恢复一致性上**可测地更差**，重开 ADR 讨论（但 FSM 已删，回退成本高，故 RA7b 落地前已用真 glm/minimax 端到端点火验证达 MVP 端点，见 `flywheel-first-ignition-proven`）。
- 若出现无法用"边界 / 证据"表达、又确需确定性的新场景，进入新 ADR，不得就地在脊梁认知路径加分支。
