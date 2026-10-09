# ADR-0033: L2 任务规划认知化——GoalSpec→tasks 交模型，模板机降 fallback

状态：Accepted（2026-10-09·用户「继续剩下的任务」授权线·续 #8 调研 6298715 / phase B 1.2.161）
调研底稿：docs/zh/reports/planning-cognition-research-20261009.md

## 背景与问题

规划链三层只有 L1 是模型：L1 goal→GoalSpec 由 `GoalSpecAgent`（模型）完成；**L2 GoalSpec→tasks
由 `RequirementPlanner` 零模型模板机完成**（docstring 自认 "Deterministic MVP planner"，按
goal_type 分支模板拼装）；L3 由 `TaskPlanEvaluator` 规则 lint 把关。执行循环已在 RA7b 全模型化
（ADR-0022），L2 是状态机时代最后的模板认知——这是重审计 #8「与 ADR-0016 张力最大」的精确含义。

模板机的真实代价（dogfood 真数据）：

- **中文塌缩**：多 requirement 模板路径把模型产出的 requirement 文本机械再切（".slice-NN"），
  计划文案不流畅；单任务路径透传模型文本所以流畅。
- **任务泛化漏测试文件**：`expected_changed_files` 由正则从 requirement 推导，推不出「补测试」
  应写的测试文件路径（run-20260718）。
- **形状与 goal 脱节**：分几步、每步验收什么，由分支模板决定而非由理解目标的模型决定。

主流对标：Claude Code / Cursor 没有独立 planner——计划就是模型在 plan mode 的直接输出，质量
信号是人看计划。与 ADR-0016 同构：认知归模型，结构合法性归 harness。

## 决定

1. **新增 `PlanAgent`**（`agents/plan_agent.py`）：一次模型调用（`purpose="task_planning"`，
   挂现成 PlannerAgent 角色契约·strong 档）产 task_plan JSON。
2. **harness 只做归一与契约硬化，不做认知**：模型产出经 `RequirementPlanner.finalize_model_tasks`
   归一（规范 task_id/status/priority/task_kind/allowed_tools、重写 depends_on、补默认验收），
   再走模板同款硬化链（`completion_contract`/`verification_policy`/`_apply_runtime_contract`/
   session-agent 写面拓宽）与 schema 校验。分几步、每步做什么写什么验收什么——全是模型的。
3. **`RequirementPlanner` 降为 fallback**：模型不可用（provider 异常）或输出不合法（非 JSON/
   无 tasks/session_agent 档不是恰好一个任务/schema 校验失败）时，回模板分支——保离线与 CI。
   回退发 `task_plan_model_fallback` 事件（event log + Inspector 级进度卡），provider 异常另记
   ModelFailureRecorder 报告；**绝不静默**。
4. **session_agent 档的形状契约**：提示词明确「必须恰好一个任务覆盖整个目标」；模型不守形状 ⇒
   整体回模板（模板有 deliberate 单任务分支）。
5. **L3 原样保留**：`TaskPlanEvaluator` 结构闸照跑（fail 才拦人）——它是模型产出之后的真底线；
   phase B（1.2.161）已让它与 execution_profile 对齐。
6. **顺带清理**：`oversized_acceptance` 的硬编码 `task_id != "task-0001"` 豁免改为语义判定
   「单任务计划豁免」（`unified or len(tasks)==1`）——所有 >4 验收的生产者（targeted repair/
   atomic multifile/single file/session unified）全是单任务计划，同一意图不再靠任务 id 巧合。

## 不做的

- 不删 `RequirementPlanner`（fallback 是离线/CI 的生产路径，不是死代码）。
- 不加「计划评审模型」（best-of-1 评审层是 G13 的事，不混）。
- 不动 L3 的 fail 闸语义（模型化后它更重要，不是更不重要）。

## 后果与回退

- 规划每 run 多一次 strong 档模型调用（延迟 +一次调用；成本计费进 cost_report——测试里
  「规划恰好 1 次模型调用」的计数断言合法地变为 2）。
- 模型计划质量不稳时，L3 结构闸 + quality gate（只 fail 拦）兜底；更差的退化就是回模板，
  与今天等价。
- 回退路径：`plan_command.py` 单一咽喉，把 try/PlanAgent 段删掉即逐字节回到模板路径。
