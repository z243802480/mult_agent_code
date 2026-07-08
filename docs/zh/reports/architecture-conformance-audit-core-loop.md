# 架构一致性审计 · 核心循环纠偏（KEEP / FIX / DELETE）

**日期**：2026-07-06
**触发**：用户指出"没按最早架构做成原子能力+大模型驱动,而是状态机;代码臃肿;调研主流没落实"。要求:先啃主流真实核心循环、再全面吃透本体系(蜂群/沙箱/上下文挂载/worker 都是体系一部分,不是臃肿)、然后**全面审计纠偏**——不符合体系的删,理解错写歪的**改(不减配)**;并明确**前端要与后端同步改**、体系定位是"在主流原语之上提供复杂问题的解决方案论,对模型是按需取用的原子能力"。
**关系**：执行 [ADR-0010](../adr/0010-open-agent-loop-and-evaluation-boundaries.md) / [ADR-0015](../adr/0015-session-loop-is-product-architecture.md) / [ADR-0016](../adr/0016-model-driven-cognition-conformance.md)（认知归模型/边界归状态）的**落地纠偏**,不新决策。

**本轮修订(2026-07-06)**：并入三份并行只读审计/调研——①后端逐文件 FSM 审计、②Studio 前端呈现契约审计、③主流(Claude Code/Codex/codex-rs)真实机制取证。据此**补齐 §4 逐文件覆盖**、**新增 §3 前端同步方案**,并**修正两处过时判断**(见下)。

> **⚠ 两处基线修正(诚实纠错)**
> 1. `review._overall` **不再是伪造标量**:后端审计确认它现在只用「模型显式打分」或「真实验证通过率」,**无** 0.9/0.6/0.2 硬编码桶(即已完成任务 A1"review 打分接 correctness_eval 去假分")。→ 从 **DELETE 改判 KEEP**。
> 2. **原生 tool-use 循环已半存在**:coder_agent 的 `tool_use` transport **已是 model-driven**(模型原生调工具、action 事后推断);**只有 `json` transport** 强制吐闭合 `next_action` 枚举。→ "立真身"不是从零造循环,而是**让 tool_use 成默认 + 修 json 路径**,工作量/风险都远小于原判。

---

## 0. 参考核心循环（真实产品级实证,不是简化版）

| 来源 | 实证 |
| --- | --- |
| **codex-rs `tasks/regular.rs` / `run_turn`**（源码级逆向,两处独立佐证） | 外层 `loop { let msg = run_turn(...).await?; if !has_pending_input() { return msg } }`;`run_turn` 内层 = model→tool→把输出 append 回 history→再问,直到模型吐 final message。**无独立 repair 状态机**:命令失败截获 stdout/stderr/exit code,格式化成 `function_call_output` 回灌,由模型决定下一步 |
| **Anthropic tool-use 官方**（[how-tool-use-works](https://platform.claude.com/docs/en/agents-and-tools/tool-use/how-tool-use-works)） | 工具 = 应用与模型间的契约:应用声明能力+I/O 形状,**"Claude decides when and how to call them. The model never executes anything on its own. It emits a structured request"**;规范循环 `while stop_reason == "tool_use": 执行并续`,`end_turn` 退出。失败=带 `is_error:true` 的 `tool_result` 回灌,**无 repair 分支**。红线原文:**"if you're writing a regex to extract a decision from model output, that decision should have been a tool call"** |
| **Claude Code sub-agent**（[sub-agents](https://code.claude.com/docs/en/sub-agents)） | 子代理 = **有界子循环**:独立 context window + scoped 工具白名单 + 独立权限;**"returns only the summary" / "results return to your main conversation"**(中间过程不回流父);fresh 起步。并发上限 ~10 超出排队。→ 我们 worker/subagent 的正主流对应物 |
| **Claude Code / Codex 方法论层** | Claude Code:Plan mode(只探不改)、**Checkpoints/`/rewind`**(改前自动存档可秒回)、hooks、Auto Mode(独立 classifier 逐动作分级)。Codex:**sandbox modes**(read-only/workspace-write/full)、approval policies。→ **candidate/promotion ≈ checkpoint/rewind;沙箱 ≈ Codex sandbox** |
| **ADR-0016 §1**（本仓库,Accepted） | 认知(要不要规划/要不要修/算不算做完/下一步)归模型,在 `model→tool→observation→model` 里涌现;**不得**有闭合 action 枚举、弹射命令、代码算的完成标量。参考形态点名 codex-rs run_turn |

**结论(三方一致)**：产品级核心循环 = **单循环 + 唯一控制分支(模型这轮吐 tool call 还是 final message)+ 错误即 observation(无 repair 状态机)**。harness 只做边界(权限/沙箱/预算保险丝/compaction/持久化/prompt 组装/工具枚举)。**关键区别**:主流让模型**调函数**,我们旧 json 路径让模型**填决策表**——后者把本该涌现的认知硬编码进 harness,正是 ADR-0016 要纠的。**主流方法论层全是"围绕模型自由工具循环的边界/安全/可回滚设施,没有一个替模型做认知决策"**——我们的差异化守在这一侧就是增值,越界切决策片就是造主流刻意不造的轮子。

---

## 1. 判据（ADR-0016 三分类 + KEEP/FIX/DELETE）

- **§1 认知** → 归模型涌现,禁写成 FSM。
- **§2 边界** → 显式确定性状态,保留(权限/沙箱/预算保险丝/持久化/人审/candidate/promotion)。
- **§3 证据** → surface 给模型/人,不 auto-gate。

- **KEEP**：符合体系且实现正确(多为 §2 边界 / §3 证据 / 正当原子能力)。
- **FIX**：**体系要的东西,但实现歪了**(把认知写成 FSM、把喂 context 的路由写成硬分类器)——**改,不减配**。
- **DELETE**：不符合体系的产物(伪造认知标量、per-action 弹射命令等纯 FSM 残件)。

---

## 2. 后端逐子系统审计

### 2.1 核心循环 / 认知层 —— **FIX（纠偏主战场）**

| 组件 | 现状(病) | 判据 | 动作 |
| --- | --- | --- | --- |
| `coder_agent` **json transport** 强制吐 `ExecutionAction`/`AgentLoopDecision`(含 `next_action` 闭合枚举 {tool,subagent,repair,replan,ask,stop}) | 模型被逼"填决策表"而非"调函数"(json 路径 `coder_agent.py:513-526`) | §1 违反 | **FIX**：从 json output_schema 去掉 `next_action` 枚举强制;让模型只发结构化 tool 调用,action 由 `agent_loop_decision._infer_action` 从调用**推导**(derived fact 而非 declared enum) |
| `coder_agent` **tool_use transport** | **已 model-driven**(原生 tool call,action 事后推断,`coder_agent.py:345-367` / 提取 `202-219`) | 合规 | **KEEP + 升为默认**："立真身"=让 tool_use 成主路径,真跑 glm/minimax 对齐 |
| `agent_loop_executor._ACTION_TARGETS`（`17-24`）dispatch 表 | 闭合 action→handler 硬映射;新增能力须改码+扩枚举,无组合性 | §1 违反 | **FIX**：改成 `action_kind→capability_provider` 适配器,枚举退为**校验集**而非 dispatch 逻辑(模型说"我要 subagent/tool",runtime 映射到 handler,而非反向切片) |
| `agent_loop_decision.py:34` 未知 action **静默降级为 "stop"** | 隐藏模型契约违反,模型学不到枚举 | §1 违反 | **FIX**：改为 `raise AgentLoopDecisionError` 把错误当 observation 喂回模型,不静默吞 |
| `execute_command.py` 主循环用 `attempt.status=="done"` 当**语义完成 gate**(`2010/2031`) | 混淆"这轮验证跑完"与"任务被接受";可能产物不全就早退,模型没被问 | §1 违反(实现歪) | **FIX**：`done` 正名为 `attempt_completed`(仅"轮次完成"标记);把 `contract_check.ok` 当**证据**喂给模型下一步决策,不由完成标记发明决策 |
| `execute_command.py` **auto_repair 进度守卫** `_auto_repair_loop_guard_warns`(`1642-1650/1647`) | 用**硬编码启发式**("同一失败类=无进展")替模型判断,不透明地卡住循环 | §1 违反(Rank1 最危险) | **FIX(谨慎·DO_NOT_TOUCH)**：失败一律格式化成 `tool_result` 回灌,进不进展由模型看 diff+验证输出判;守卫要么**下沉为模型可见 observation**,要么**明示为策略参数**不当魔法。⚠该文件是 Code Triage `DO_NOT_TOUCH`,但 [解冻记忆](../../adr/0016-model-driven-cognition-conformance.md) 授权闭合自主环含 scoped 触碰——**须最小切口、可回滚、单独 commit** |
| `repair_budget_exhausted`/`loop_no_progress` 当语义终止 | 撞小数字当认知终点 | §2 误用 | **FIX**：仅作**可 resume 的保险丝**(写 exit_reason+保状态),不冒充语义完成/失败 |

### 2.2 正当架构（体系要的,实现基本对）—— **KEEP，别当臃肿删**

| 子系统 | 依据 | 主流对照(取证) | 审计结论 | 动作 |
| --- | --- | --- | --- | --- |
| candidate workspace / merge gate / promotion / accept | ADR-0002 | **Claude Code Checkpoints/`/rewind`(改前存档可秒回)= 直接对应物**;Codex diff+approval | 审计确认 `task_attempt_runner` 的 contract_check/merge_gate 是**确定性边界闸**,verdict 是 feedback 不是路由决策(100% KEEP) | **KEEP**(别把 rewind 顶到 UX 前台;主流藏成 `Esc Esc`) |
| 沙箱 / write-scope / protected paths / 权限闸 | ADR-0013 | Codex sandbox modes(read-only/workspace-write/full,OS 级强制) | §2 边界 | **KEEP**（rollout 按 flag 灰度） |
| worker / subagent / delegation | 架构 §3.6;有界子循环 | **Claude Code sub-agent = 独立 context+scoped 工具+只回 summary**,完全同构 | 审计:`worker_runner`/`subagent_planner`/`agent_loop_executor` worker ID 生成均 **model-driven / 确定性投影**,子循环**未**写成 FSM(100% KEEP) | **KEEP**（前提:worker 必须是**模型自由调用的工具**,非 harness 状态机强编排） |
| 上下文挂载 / ContextEnvelope / Budget / Package + compaction | 大模型循环设计 | **主流铁律:harness 拥有 prompt 组装+compaction+级联注入,模型只消费成品**;Claude Code 三层 compaction | §2 边界 | **KEEP**（对齐:至少 microcompact 清陈旧 tool result 不调模型 + full compact 总结） |
| 持久化 JSONL / resume / handoff | ADR-0001 | Codex session 累积 | §2 边界 | **KEEP** |
| GoalSpec / planner / task plan / task_board | 大模型循环设计 §3 | Claude Code TodoWrite(便签**不驱动控制流**) | 审计:`task_board.ALLOWED_TRANSITIONS` 是**持久状态守卫记录事实**、`subagent_planner` 计划是**给模型的脚手架数据**,均**未**当 FSM 阶段驱动器(100% KEEP) | **KEEP** |
| runtime profiles / 路由解析 / provider fallback | 模型主导运行时设计;多 provider 是本体系差异化(国产化栈) | Codex 多 tool source | §2 边界 | **KEEP**（注:3 个陈旧测试,见 §5） |
| correctness_eval / `review._overall` 真实通过率作 DoD | ADR-0016 §3 允许 | Anthropic 长任务 harness checklist | **审计确认已是证据非伪造**:用模型显式分或真实验证率,unverified 留 None,**无硬编码桶**(已完成 A1) | **KEEP**（**本轮从 DELETE 改判**） |
| AGENTS.md / CLAUDE.md 级联注入 | 本仓 `CLAUDE.md` 用 `@AGENTS.md` import | agents.md 标准"就近覆盖";Claude Code `@path` import | §2 边界 | **KEEP** |

### 2.3 冻结项（体系有,但明令不碰）—— **KEEP_PLACEHOLDER，不扩不删**

- 蜂群/北极星/12-Agent/parallel_writes 全局默认:AGENTS.md 明确**冻结**(post-S7 gate),`KEEP_PLACEHOLDER`。**取证印证冻结是对的**:并行子代理(swarm)/全局并行写连 **Codex 都 feature-gate 挡住默认关闭**;主流子代理是"模型按需委派的工具"不是常开编排层。审计中不因"看着没用"就删,也不启用。

### 2.4 确认为不符合体系的残件 —— **DELETE（谨慎,逐个核）**

- per-action 弹射命令映射(`_ACTION_TARGETS` 的 repair/replan→command 那部分语义):**溶解后其纯 dispatch 支撑代码**即残件(枚举本身作校验集保留,不删)。
- ~~`review._overall` 伪造标量 gate~~ —— **撤销**(本轮修正:已是真实证据,见 2.2)。
- 其余无独立 repair-state-machine 依据的分叉代码:溶解 repair 后核实为残件再删。

### 2.5 逐文件覆盖表（§4 待办已由后端审计补齐）

| 文件 | 结论 | 关键位置 |
| --- | --- | --- |
| `agent_loop_executor.py` | **FIX** dispatch 表(40%),ID/状态生成 KEEP | `17-24` |
| `coder_agent.py` | tool_use **KEEP**、json path **FIX** 去枚举(~30%) | `345-367` / `513-526` |
| `agent_loop_decision.py` | 推导 KEEP、`:34` 静默降级 **MINOR FIX** | `214-219` / `34` |
| `task_attempt_runner.py` | **KEEP**(确定性 gate) | `189-222` |
| `execute_command.py`(repair) | **FIX** 进度守卫(DO_NOT_TOUCH·谨慎) | `1614-1730` |
| `execute_command.py`(主循环) | **FIX** `attempt.status` 语义混淆 | `2010/2031/2095-2119` |
| `task_board.py` | **KEEP** | `15-24` |
| `worker_runner.py` | **KEEP** | `30-125` |
| `subagent_planner.py` | **KEEP** | — |
| `review_agent.py` | **KEEP**(真证据) | `230-274` |

**整体健康度**:后端 **71% model-driven / 29% FSM 残渣**,残渣集中在 action dispatch + repair 循环控制,**可改不动架构**。
**最危险 Top3**:①auto_repair 进度守卫(硬编码启发式卡循环)②action dispatch 表 ③`attempt.status` 冒充任务完成。

> **✅ 收官更新（2026-07-08 · RA7b 重塑完成 → FSM 残渣 29%→0）**：上表所列 FIX/DELETE 文件**已全部删除或转正**，立真身脊梁（`core/model_driven_turn.py`）是编码任务唯一执行路径，详见 [ADR-0022](../adr/0022-model-driven-spine-landed.md) 与 `已删除与已替代登记.md` §3.2。逐项动作 + commit：
> - `agent_loop_executor.py` / `agent_loop_decision.py`（含 `:34` 静默降级、`recommended_command`）/ `execution_action.py` / `agent_loop_observation.py` → **DELETE**（task7 `86e16fe`+`a559a33`）
> - `coder_agent.py` json path `next_action` 枚举 + `propose_action` → **DELETE**，gut 到 `model_client` 壳（task7 `86e16fe`）；tool_use 原生调用形态由脊梁 `extract_tool_calls` 承接
> - `execute_command.py` 主循环 + repair 进度守卫（§最危险 Top3 全部）→ **DELETE**（`for round_index` 循环体 slice3f `7b25257`；auto_repair/replan 环 `db414d0`；探针 `13a3916`）
> - `task_attempt_runner.py` / `task_board.py` / `worker_runner.py` / `subagent_planner.py` / `review_agent.py`（真证据的 KEEP 项）→ 原样保留，不受影响
> §4 纠偏顺序 1–3（立真身→溶解 action-FSM→repair 退保险丝）+ §7 蓝图（A 轨立真身 / B 轨删废物合流）**全部达成**。剩 §4 步骤 4/5（前端流式叙事 Tier2 / 路由去中心化）由 ADR-0021 主线程系列（第一–五刀）落地，§5 遗留卫生项（`test_runtime_profiles` 3 红）仍为既有 config drift 非本重塑引入。

---

## 3. 前端同步方案（Studio,与新核心循环对齐）

后端从"结构化 action/phase"转"交错 prose+tool"后,前端呈现契约必须同步,否则主区仍显机器脚手架。审计发现前端**已有 `transcript_kind` 白名单初步隔离,但深度耦合 `phase` 枚举,且有真 bug 漏机器词到主线程**。

**核心诊断(带证据)**：
- **A. phase 耦合**：`narrative.ts:124-131` 用 `phase` 决定 `narrativeKind`;`types.ts:64` 把 phase 定成有限枚举。→ 改成 **`transcript_kind` 优先、phase 仅当分组 hint**。
- **B. 真 bug——display_level 被硬编码**：`runtimeNarrative.ts:155` 把 `display_level` 写死 `"main"`,不读事件真值 → 后端标了 inspector 也漏到主线程。→ 改 `event.display_level ?? "main"`。
- **C. 意图路由硬分类在 BFF**：`intent-router.mjs:30-41` 关键词匹配 + `server.mjs:796-839` 硬列表——主流**没有这层**(用户说啥做啥)。→ 去中心化为**前端显式按钮(chat/plan/run)**,BFF 只转发不覆盖,`intent_audit` 决策链曝到 Inspector。
- **D. 仍漏主线程的机器脚手架**：`decision_request` 非 `waiting_user` 态被当 observation 上主线程;phase 强制标题("核对结果"/"计划中" `runtimeNarrative.ts:219-226`)。→ 收进 Inspector 或改按 `transcript_kind` 定标题。

**改动清单(分层,Tier1 纯前端立即可修 → Tier5 需前后端协议)**：
- **Tier1(纯前端,即时)**：①`narrative.ts` DETAIL_KINDS 改显式白名单/读 display_level ②`runtimeNarrative.ts:155` display_level 不写死 ③标题按 transcript_kind 优先 ④`isRealToolEvent` 补 `transcript_kind==="tool_use"` 校验,防伪工具卡。
- **Tier2(流式呈现重构)**：主线程改**单条流式叙事**(narration 散文 + 内联工具块 + 折叠结果交错),而非"model block+tool block+final block"三层;工具卡改内联边注不打断文本流。对齐主流 §0-UX。
- **Tier3(路由去中心化)**：`server.mjs:796` 简化为"显式 mode 直用,否则 orchestrator",移除硬分类;GoalInput 改三按钮;Inspector 加 intent_audit 小节。
- **Tier4(后端契约强化)**：每个 user_progress 事件都带 `transcript_kind`;内部迭代/压缩标记标 `display_level="inspector"`;narration 总填 `content_delta` 不靠 summary fallback。
- **Tier5(协议升级)**：事件加 `tool_sequence_id` 分组同一交错序列;tool 事件结构化 `{tool_call_id, tool_use_delta, tool_result_delta, errors_delta}`。

**红线**：前端 UX **零"phase/next_action/gate/candidate"仪式词**,内部词汇一律 Inspector;主区只有模型人话 + 工具名 + 折叠结果(对齐 Claude Code/Codex TUI)。

---

## 4. 纠偏顺序（有界·可回滚·尊重冻结）

1. **立真身(非破坏)**：让 coder_agent **tool_use transport 成默认路径**(它已 model-driven),json 路径去掉 `next_action` 枚举强制、action 改推导。灰度在新入口后**不删旧路径**,真跑 glm/minimax 编码任务对齐行为(**前端 Tier1 同步**,让主区先能显模型人话+内联工具)。
2. **溶解 action-FSM**：新循环稳后,`_ACTION_TARGETS` 退为校验集+capability 适配器;`agent_loop_decision:34` 改 raise;主循环 `attempt.status` 正名并把 contract 当证据喂回。
3. **repair 退保险丝**：失败一律 `tool_result` 回灌模型;进度守卫下沉为 observation/策略参数(⚠DO_NOT_TOUCH `execute_command`,最小切口·单独 commit·可回滚)。
4. **前端同步**：Tier2 流式叙事重构 + Tier3 路由去中心化(前端三按钮),Tier4/5 前后端协议对齐。
5. **路由归位**：意图路由改"喂 context 不夺决策"(前后端一致)。
6. 全程:弱模型是否需脚手架**由 eval 定**(ADR-0016 nuance),不反射式加/减。

---

## 5. 遗留卫生项（非核心循环,记录不阻断）

- **`test_runtime_profiles.py` 3 红**(`weak_capability_route`/`strategy_bias`/`resolved_model_route`):worker `max_runtime_minutes` 期望 2 实得 3,源自老提交 `8fef920 enforce role-based model deadlines` 调了角色 deadline 未同步测试期望。经核实**非本会话回归**(本会话唯一碰 builder 的 slice3 `0e9232c` 只加 context_mounts+user_progress,未动 deadline)。属 KEEP 子系统 runtime-profiles 的陈旧测试,纠偏前后**顺手校准期望值**即可。

---

## 6. 一句话判据

**认知归模型的单循环(tool schema 调函数,不填决策表);错误即 observation 回灌(无 repair 状态机);边界与原子能力(沙箱/worker/candidate/上下文挂载)保留并各归其位;前端单条流式叙事、内部词汇下沉 Inspector;伪造认知删、写歪的定位改回来——不减配。**

---

## 7. 立真身 · 落地蓝图（2026-07-06 主代理亲手 grounding 后锁定）

亲读核心代码确认:**要的原子能力都已存在且实现良好**(不是臃肿,是立真身要复用的料):

| 好料(KEEP·复用) | 位置 | 角色 |
| --- | --- | --- |
| `AgentHarness`(能力清单+prompt envelope) | `agent_harness.py:592` | 主流"harness 拥有 prompt 组装"层 |
| `ToolExecutionGateway.run_tool_calls` | `tool_execution_gateway.py:32` | 原子工具执行(含权限/沙箱/MCP/skill 路由) |
| 模型原生工具调用 | `coder_agent.propose_action` tool_use 分支 `:78-103` | `tools=tool_definitions_for(...)`+`extract_tool_calls`+narration |
| `observation_from_tool_result/exception` | `agent_harness.py:991/1014` | "失败即 observation"的成品 |

**病(闭合 enum 由三层相互加固)——FIX 的精确坐标**:
1. prompt envelope `loop_decision_contract` section(`agent_harness.py:900-907`)明文教模型 `next_action.action ∈ {tool,subagent,repair,replan,ask,stop}`。
2. coder_agent `_validated_action_from_tool_calls`(`:212-218`)把原生 tool call 硬塞回 ExecutionAction 壳。
3. execute_command for-round 循环 `if next_action_kind==...`(`:2854/2909/2933`)按 enum 派发。

**立真身 = 把 4 个"料"接成一条 codex run_turn 形态干净循环,砍掉 3 层 enum**:
```
loop(fuse: max_iters / budget):
  resp = model.chat(prompt=AgentHarness envelope, tools=native schemas)
  narration = resp.content              # 上主线程(已有机制)
  calls = extract_tool_calls(resp)
  if not calls: return final            # 模型不再调工具 = 完成(唯一控制分支)
  obs = gateway.run_tool_calls(calls)   # 失败→observation_from_exception,不抛独立 repair 分支
  append(obs) → 下一轮
```
- **不碰 DO_NOT_TOUCH execute_command 的 FSM**:新循环是独立模块;灰度入口仿 `_validation_probe_runtime_action`(`:2783`)那种 1 行短路把编码任务路由进新循环,老 FSM 原样保留并存。新循环**复用** execute_command 已备好的 task(含 `allowed_tools`)+RuntimeContext,只替换内层控制。
- **护栏(弱模型刚需,非认知)**:max_iters/budget 保险丝、gateway 自带权限/沙箱/write-scope、每轮 observation 持久化 + narration 上屏。
- **收敛**:新循环在**真 glm/minimax** 上跑通小编码任务(correctness_eval 打分做基线)→ 老 FSM 三层成**可证明死代码** → 交 §B 轨(死代码普查)删。**A 轨(立真身)与 B 轨(删废物)在此合流。**

> 本文档是**纠偏基线**,三份审计 + 亲手 grounding 蓝图已并入,§4 顺序 + §7 蓝图为执行图。后续每完成一项在 §2.5 表更新动作与 commit。
