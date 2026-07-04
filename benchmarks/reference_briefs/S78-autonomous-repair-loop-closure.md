# S78 · 自主 repair 闭环(第一环)· 执行规格

Slice 类型：解冻后核心增量——闭合 Goal→Plan→Execute→Verify→**repair→（自动）resume** 一环。用户 2026-07-04 授权解冻(见记忆 `freeze-lifted-autonomous-loop`),**可改此前 DO_NOT_TOUCH 的 `execute_command.py`**。目标=让验证失败后在**有界预算**内自动 repair 重试,而非每次失败就 block 交还人类;耗尽/无进展才诚实 block。**flag 门控、默认关、可一键回退。**

## 已验证的开环真相（只读代理 + 亲验，file:symbol:line）
- **四条审计声明全真**:`budget.py:185 record_repair_attempt` 零生产调用(注释明写"Intentionally unwired");`loop_progress_guard.py evaluate_loop_quality` 是 `observe_then_warn`/`hard_block:False`、只喂 summary 从不终止;`AgentLoopRunner` 仅 `test_agent_loop_runner.py` 调;`max_repair_attempts_per_task` 仅 `run_command.py:1605` 粗粒度用。
- **开环 STOP 点 = `ExecuteCommand._handle_runtime_managed_loop_action`（`execute_command.py:1493-1544`）**:模型出 `repair`/`replan` → `command="debug"/"replan"` → `_mark_task_blocked` → 写 `pending` 观察(`next_recommended_action=action_kind`)→ 进度事件 `recommended_command` → run-summary `exit_reason="repair_dispatch"/"replan_dispatch"` → **返回 `blocked` summary**。调用点 `_execute_task:2456-2468`：`if runtime_managed is not None: return runtime_managed`(立即结束任务)。
- **Goal 级编排 `run_command.py:_execute_until_no_ready:1215-1279`**:task=blocked 后写"stopped at resumable session boundary"、荐 `resume`、退出;blocked 不计入 `_ready_count`;**从不 import DebugCommand/ReplanCommand**。
- **关键洞见**:round 循环(`_execute_task:2319 for round_index in range(1,max_rounds+1)`,`max_rounds` 默认 2)**已把上一轮失败观察经 `runtime_context["latest_agent_loop_observation"]`(2328-2329)喂回 `coder.propose_action`(2335)**,且失败 tool 轮已会继续(`_should_continue_agent_loop:1581-1584` 对 `next_recommended_action∈{tool,repair,replan}` 且预算未 hard-stop 返回 True)。**故自动 repair 不需要新 agent**——CoderAgent 带着失败观察重提本身就是 repair。开环缺口仅在:repair 决策被 `_handle_runtime_managed_loop_action` 拦成 blocked 返回。

## 首个增量设计（最小 · 可逆）
**核心**:repair 分支不再终结;预算内→记一次 repair、写 `next_recommended_action="tool"` 的 `repair_result` 观察、让循环进下一轮(模型重提,期望这次给 tool);预算耗尽/无进展→保留今日 block 行为(改 `exit_reason`)。

| # | 站点 | 分类 | 改动 |
|---|---|---|---|
| E0 | 策略新增 `agent_loop.auto_repair`(bool, **默认 False**)+ 复用 `budgets.max_repair_attempts_per_task` | 配置(schema+defaults,additive) | 关时行为与今日**逐字节相同**;开时启用自动 repair |
| E1 | `_handle_runtime_managed_loop_action` repair 分支(`execute_command.py:1493-1544`) | **核心路径** | `auto_repair` 且 repair 预算未耗尽且 loop-guard 未 warn → 走"继续"分支(见 E1b);否则今日 block 行为但 `exit_reason="repair_budget_exhausted"`/`"loop_no_progress"` |
| E1b | 让 round 循环"进下一轮重提"而非"本轮跑空工具" | **核心路径**(控制流) | ⚠**实现前必读 `_execute_task` 2468-2620 的 fall-through**:`runtime_managed is None` 现语义=本轮继续跑 tool_calls;repair 无 tool_calls。需新机制让 `_execute_task` `continue` 到下一轮(如:让 `_handle_...` 返回一个哨兵/带 `continue_loop` 标志的结果,或在 `_execute_task` 内 repair 分支前置处理并设 `latest_loop_observation` 后 `continue`)。这是本增量唯一需要小心设计的控制流点 |
| E2 | 调 `context.budget.record_repair_attempt()`(`budget.py:185` 已存在) | additive(激活休眠保险丝) | 每记一次 repair;try/except `BudgetExceededError`→当作"耗尽→诚实 block" |
| E3 | 每任务 repair 计数 + `_repair_budget_ok` helper | additive | 计数来源:统计本任务 `agent_loop_observations.jsonl` 的 `repair_result` 数,或循环内局部 int。上界=`min(max_repair_attempts_per_task, 剩余 max_repair_attempts_total)` |
| E4 | loop-guard 作为终止条件(仅自动 repair 路径) | additive(新消费者,guard 不改) | `evaluate_loop_quality(...).warn is True`(重复无进展/重复失败)→终止 auto-repair、诚实 block、`exit_reason="loop_no_progress"` |
| E5 | `_should_continue_agent_loop:1581-1584` | 无需改 | 已允许失败轮继续 |
| E6 | round 上限:auto_repair 开时 = `max_rounds + max_repair_attempts_per_task` | 核心路径(config-gated) | `_agent_loop_max_rounds`(`execute_command.py:408`)或 2319 的 range;默认关时不变 |

## 终止条件（先触发者胜，全部必须保留）
1. 成功:repaired 轮 `status=="done"` → `_should_continue_agent_loop` 返 False,`exit_reason="completed"`(已工作)。
2. repair 预算耗尽:`record_repair_attempt` 抛 `BudgetExceededError` 或局部计数 ≥ `max_repair_attempts_per_task` → 诚实 block,`exit_reason="repair_budget_exhausted"`,`recommended_command="debug"`(人类兜底=最后手段非首选)。
3. 无进展:`evaluate_loop_quality` warn → 诚实 block,`exit_reason="loop_no_progress"`。
4. 全局预算 hard-stop:`_should_continue_agent_loop:1578-1580` 已保。

## 单测种子（确定性,无真模型）
- **auto-repair-then-succeed**:扩 `FakeRepairAfterFailureLoopClient`(`tests/integration/test_execute_command.py:736`)使第 2 次出 repairing **tool** 动作(写对模块过验证)、第 3 次 `stop`;`auto_repair=on`、`max_repair_attempts_per_task≥1` → 断言 `completed==1/blocked==0`、观察序列 `tool_result(failed)→repair_result(pending)→tool_result(succeeded)→stop`、`cost_report.repair_attempts==1`、`exit_reason="completed"`。(现有相反断言在 `test_execute_command.py:2161`,需 invert 或新增。)
- **auto-repair-budget-exhausted**:`FakeAlwaysFailRepairClient` 每轮 tool(fail)→repair;`max_repair_attempts_per_task=2` → 恰 2 次 repair 后 block,`repair_attempts==2`、`exit_reason="repair_budget_exhausted"`、`recommended_command="debug"`。**证明能确定性终止一个打转的模型。**
- **no-progress-guard-trip**:字节相同失败观察 → `exit_reason="loop_no_progress"` 早于数值预算。
- **opt-out 回归**:`auto_repair=off`(默认),现有 `test_execute_command_routes_failed_observation_to_repair_action`(:2161)**逐字不变通过**(`blocked==1`,`exit_reason="repair_dispatch"`)——这就是可逆性。

## 边界
- 本增量**只闭 repair 环**;`replan` 仍人类门控(涉及新任务合成/DecisionPoint,单独一环)。
- `AgentLoopRunner`/`DebugAgent` 占位不动。
- 落地后**紧接前端拉齐**:Studio 呈现自动 repair 轮次/预算/终止原因(对齐用户"后端就绪即拉前端")。

## 相关文件（绝对路径）
- `src/asteria_runtime/commands/execute_command.py`(`_handle_runtime_managed_loop_action` 1356/1493-1544;`_execute_task` 2258-2746;`_should_continue_agent_loop` 1563;`_agent_loop_max_rounds` 408)
- `src/asteria_runtime/core/budget.py`(`record_repair_attempt` 185;`pressure`/`repair_attempts` 242/259)
- `src/asteria_runtime/core/loop_progress_guard.py`(`evaluate_loop_quality` 97)
- `src/asteria_runtime/commands/run_command.py`(`_execute_until_no_ready` 1157/1215-1279;无 Debug/Replan import)
- `src/asteria_runtime/core/agent_loop_observation.py`(`repair_result` 观察类型 + `_next_action` 映射)
- `tests/integration/test_execute_command.py`(种子:`FakeRepairAfterFailureLoopClient` 736;待 invert 的现行为测试 2161)
