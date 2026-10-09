# 规划认知化调研（重审计残余债 #8 · 2026-10-09）

状态：调研完成，**建议立 ADR 后开工**。本文是 #8 的底稿（现状/归因/方案/路线），供 ADR 引用。
授权线：用户「继续，开 #8 调研」。

## 1. 现状：规划链三层，只有第一层是模型

| 层 | 现状 | 证据 |
|---|---|---|
| L1 goal→GoalSpec | **模型**（GoalSpecAgent·消费 model_client） | plan_command.py:308 |
| L2 GoalSpec→tasks | **零模型模板机**：`RequirementPlanner` docstring 自认 "Deterministic MVP planner"，按 goal_type 分支模板拼装（targeted_repair/single_file/atomic_multifile/session_agent_unified/多 requirement 展开） | planner.py:21-58·plan_command.py:518（构造无 model_client） |
| L3 计划评估 | **规则 lint**（`TaskPlanEvaluator`·evaluation/task_plan_evaluator.py）：结构检查+关键词判定，五维扣分（error -0.25/warning -0.12），`_status`=任一 error 或 score<0.70 ⇒ fail | task_plan_evaluator.py:295-320 |

执行循环已在 RA7b 全模型化（ADR-0022），**规划 L2 是状态机时代最后的模板认知**——这就是审计"与 ADR-0016 张力最大"的精确含义：不是缺评审，是**任务拆解这一步根本没有模型**。

## 2. dogfood 现象归因（真数据）

- **0.98+warn 的两个实例**（run-20260720-0001 / run-20261009-0004）：`oversized_acceptance`（>4 条）与 `under_decomposed_plan`——**lint 与 execution_profile 的设计意图打架**：session_agent unified task 就是**故意的**单任务/整块 acceptance，evaluator 却按多任务理想扣分。F6 那次"0.98 标需留意"的矛盾根源在此。
- ~~**`_is_observable` 语言盲区**~~ **✅ 本报告成文当日复核证伪**：词表实际**双语**（exists/returns/test/file/report + 运行/显示/生成/通过/返回/包含·task_plan_evaluator.py:358-382）——初读只看了词表前半就断言"英文词表"，是 [[lying-audit]] 又一例（验了开头声称了全体）。weak_acceptance 对中文有基本覆盖，非债。
- **中文塌缩（2026-07-18 观察）**：多 requirement 模板拼装路径把模型产出的 requirement 文本机械再切；单任务（session_agent）路径透传模型文本所以流畅。
- **任务泛化漏测试文件**（run-20260718）：expected_changed_files 由模板从 requirement 推导，推断不出"补测试"应写的测试文件路径。

## 3. 消费者与闸面（改动的安全边界）

- `task_plan_quality_gate`：**只有 fail 才拦**（pause+DecisionPoint·可 bypass）；warn 纯展示（F6 已治其矛盾显示）。
- 其他读取方：execute/run/resume（证据/重规划输入）、user_progress_view（展示）。fail 拦截的锋利面 = error 级 issue（缺依赖/自依赖/缺 acceptance/缺写工具等**结构类**）。
- 有 bypass/decision 机制 ⇒ 模型化后保留 fail 闸不增加人的负担。

## 4. 主流对标

Claude Code / Cursor **没有独立 planner/evaluator**：计划 = 模型在 plan mode 的直接输出（模型自己拆解·自己写验收），无外部评分器；质量信号 = 人看计划。与 ADR-0016 同构：认知归模型，结构合法性归 harness。

## 5. 方案

**B（先·小刀）— L3 去噪与 profile 对齐**：
1. `_status` 评分/issue 判定读 `execution_profile`：session_agent unified task 不再触发 `under_decomposed_plan`/`oversized_acceptance`（设计意图非缺陷）。
2. ~~weak_acceptance 词表降级~~ **撤销（词表已双语·复核证伪）**。
3. 结构类 error 检查**原样保留**（语言无关·真底线·fail 闸继续工作）。

**A（后·正解·需 ADR）— L2 认知化**：
GoalSpec→tasks 交模型（新 PlanAgent：一次模型调用产 task_plan JSON·schema 校验兜底），`RequirementPlanner` 降为 fallback（模型不可用/输出不合法时·保离线与 CI）。eval 口径随 B 收窄为结构底线。工作量中大：planner prompt+解析+fallback+FakePlanClient 全家测试迁移（tests 现钉模板产物形状）。

**不做的**：L3 整体删除（结构检查是真底线·模型产出也要过它）；独立"计划评审模型"（best-of-1 评审层——G13 的事，不混）。

## 6. 建议决议点

- B 可自主开工（消费面已核实·warn 从不拦人·零闸变化）。
- A 涉 KEEP_CORE 规划能力的核心替换 + 测试迁移面大 ⇒ 建议立 ADR-00xx（对齐 ADR-0016：认知归模型·模板机降 fallback）后开工，或按用户节奏排。


## 7. B 落地记录（2026-10-09·1.2.161）

- `TaskPlanEvaluator.evaluate` 增 `execution_profile`（默认 "harness"=现状）：session_agent unified
  task 不再触发 `under_decomposed_plan`/`oversized_acceptance`。
- 调用点全透传：plan_command 评规划 + task_plan_quality_gate 两处复评（`_plan_profile_id` 从
  run_config 读·缺失回落 harness）——否则会出现「plan 时 pass、gate 复评又 warn」的矛盾回归。
- ~~weak_acceptance 词表降级~~ **撤销**：复核证伪——词表已双语（运行/显示/生成/通过/返回/包含）。
- 顺带发现（A 方案清理项）：`oversized_acceptance` 带硬编码 `task_id != "task-0001"` 豁免——
  同一意图的旧补丁（第一个任务天然 acceptance 长），该修判定语义而非豁免 id。
- 测试 stub 6 处补 `**kwargs`（evaluate 新 kwarg）；全量 1488 绿。

## 8. A 落地记录（2026-10-09·1.2.162·ADR-0033）

- **PlanAgent**（`agents/plan_agent.py`）：一次模型调用（`purpose="task_planning"`·挂现成
  PlannerAgent 角色契约·strong 档）产 task_plan JSON；`PlanAgentError` 五类失败（非 JSON/无
  tasks/session_agent 档非恰好一个任务/超 16 任务/schema 校验失败）与 provider 异常一律触发
  **RequirementPlanner 模板 fallback**（离线/CI 保底），回退发 `task_plan_model_fallback` 事件
  + Inspector 进度卡，provider 异常另记 ModelFailureRecorder——绝不静默。
- **认知与边界的分界线**：分几步、每步 title/description/acceptance/artifacts/changed files/
  deps 全是模型的；`RequirementPlanner.finalize_model_tasks` 只做归一（规范 id/枚举安全
  kind/priority、dep 别名重写、缺失字段默认）+ 模板同款硬化链（completion_contract/
  verification_policy/_apply_runtime_contract/session-agent 写面拓宽·该块抽成
  `_widen_session_agent_write_surface` 两路共用）。L3 结构闸原样保留（fail 才拦）。
- **硬编码豁免清理**：`oversized_acceptance` 的 `task_id != "task-0001"` 改为语义判定
  「单任务计划豁免」（unified or len(tasks)==1）——所有 >4 验收的生产者全是单任务计划，
  同一意图不再靠 id 巧合。
- **验证**：新单测 7（归一/角色契约/session-agent 形状契约×2/非 JSON/无 tasks/超 cap/schema
  失败）+ 集成 2（模型路径 plan_source=model·回退披露事件）+ evaluator 重钉 3；计数断言诚实
  更新 8 处（规划 1→2 次模型调用：compact 1 处·review 5 处含 token 对·run purpose 序列 1 处·
  goal_spec 重试阶梯 1 处）；**全量 1498 passed, 1 skipped** + ruff 净。
- **真栈活体**（glm-5.2·scratch 工作区）：中文目标「写 greet.py + 补单测」⇒ 模型计划
  （「创建 greet.py 模块并编写单元测试」·逐码点 0 个 U+FFFD），验收含函数签名/两个调用样例/
  tests/test_greet.py 路径/`pytest tests/test_greet.py -v` 命令，**L3 = 1.0/pass/零 issue**，
  model_calls 记账 `[goal_spec, task_planning]`、零回退——「补测试推不出测试文件」的模板机
  泛化 friction（run-20260718）在模型路径下结构性消失。
- **诚实边界**：规划每 run 多一次 strong 档调用（成本进 cost_report·测试计数已随真实语义
  更新）；模型计划质量不稳时 L3 兜底，更差退化即回模板（与改前等价）；replan 产 repair 任务
  的路径不走 PlanAgent（replan_command 自建修复任务·非本刀范围）。
