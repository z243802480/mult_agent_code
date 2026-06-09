# S74 Post-S73 Beta Convergence 实施计划

更新时间：2026-06-09
状态：**active**
Brief：[`../../../benchmarks/reference_briefs/S74-post-s73-beta-convergence.md`](../../../benchmarks/reference_briefs/S74-post-s73-beta-convergence.md)
前置：[`../reports/S73-beta-opt-in-ingress-signoff-20260607.md`](../reports/S73-beta-opt-in-ingress-signoff-20260607.md)

## 1. 阶段判断

S61–S73 已经证明 Asteria 具备 route、spawn、dynamic workflow、live provider、workflow monitor、verifier 与显式 parallel writes opt-in。当前风险不再是“能力不存在”，而是：

1. 执行真源落后于代码，导致智能体继续做已完成或已过时任务。
2. 普通 Execute 主路径仍有契约漂移，复杂能力签字不能替代基础路径全绿。
3. maintainer pulse 在不同 Python/temp 环境下不可复现。
4. Beta friction 只有维护者记录，尚无外部用户证据支持扩大默认权限。
5. Studio、runtime 与 evidence 已有大量能力，但是否真实帮助用户完成任务尚未形成统一结果证据。

因此 S74 禁止继续新增编排 Wave，先完成产品收敛。

### 1.1 2026-06-09 方法校正

S74 不再把统一低模型调用数或低 repair 次数作为 Agent Runtime 硬停止条件。成熟 Harness 的公开机制显示：模型应在工具 observation 循环中自主推进，权限/sandbox/不可逆操作属于硬边界，turns/预算/deadline 属于可配置资源保险丝，调用次数、repair 和耗时属于按任务类型评估的产品 SLO。

因此：

- 简单任务调用量和 repair 超出目标时记录性能回归，但不据此限制复杂任务。
- 长任务只要持续产生新 evidence、artifact 或 verification，就允许在授权预算内继续。
- 重复相同失败且没有新增证据时，才进入 no-progress 的 ask/stop/resume 边界。
- provider、schema、tool/verification repair 分层归因。
- 任何改变自主边界或停止条件的建议必须先调研、写明分类、建立 eval，并提供回滚/删除条件。

执行依据：[`../adr/0010-open-agent-loop-and-evaluation-boundaries.md`](../adr/0010-open-agent-loop-and-evaluation-boundaries.md)。

复杂度清算必须同时遵守 [`../adr/0011-reference-first-complexity-liquidation.md`](../adr/0011-reference-first-complexity-liquidation.md)。愿景与实现分开裁决：Asteria 特有能力可以保留，但确认当前实现劣于成熟产品的稳定原语后，必须停止修补，保留能力契约并替换实现；无产品价值的能力与实现一并删除。

## 2. 工作分层

### S74-A：执行真源与可复现基线（P0）

| 工作 | 交付 | 退出条件 |
| --- | --- | --- |
| 三源归一 | AGENTS、总计划、当前状态、vibe slices 全部指向 S74 | documentation contracts 全绿 |
| 关闭旧 active | S61、S70–S73、Triple、Studio F2 改为 closed/reference/input | 无过期 ACTIVE 搜索结果 |
| pulse 可复现 | pytest temp/cache、解释器、workspace 输出路径显式化 | S73 与 steady pulse 在干净 workspace 可复跑 |

受限环境可显式使用 `steady_iteration_check.py --skip-wheel`；wheel/venv 安装验证仍作为独立发布检查，不应让它掩盖 Runtime 与文档基线。

### S74-B：Runtime 主路径正确性（P0）

| 问题簇 | 当前证据 | 修复原则 |
| --- | --- | --- |
| readonly fast-path schema | Execute 完整集成 4 个相关失败 | `risk_tier` 与兼容 telemetry 分层；不扩 schema 动物园 |
| permission / read scope | schema 提前失败，未进入 DecisionPoint/runtime request | 恢复真实权限主路径，不绕过策略 |
| verification evidence | 安全替换后 evidence 摘要契约漂移 | 保留安全替换，统一结果证据 |
| user progress | Execute 真实边界缺少语义事件 | 只记录已发生动作；提案与 raw evidence 留 Inspector |

退出条件：

```powershell
pytest tests/integration/test_execute_command.py -q
pytest tests/unit/test_user_progress_logger.py tests/unit/test_plan_progress_contract.py -q
```

### S74-C：真实 Beta 任务矩阵与耗时归因（P1）

最少 3–5 个真实 provider 任务，必须覆盖：

| 路径 | 示例 | 必须记录 |
| --- | --- | --- |
| session agent | 单文件修复 / doc update | 首次有效动作时间、总耗时、model/tool calls |
| subagent | 主任务委托一个 child worker | 父子 evidence、context isolation、结果回流 |
| L3 workflow | 多阶段 manifest + verifier | checkpoint/resume、workflow monitor、merge evidence |
| parallel writes opt-in | 两个 disjoint files | DecisionPoint、workspace isolation、promotion/rollback |

统一结果字段：

```text
goal_completed
artifact_verified
accepted_or_blocked_reason
elapsed_total
elapsed_model
elapsed_tool
elapsed_verify
elapsed_waiting
model_calls
tool_calls
repair_count
replan_count
user_progress_consistent
studio_runtime_consistent
```

不以“生成了 JSONL”视为成功；任务必须产出可验证结果，Studio 主会话必须能解释发生了什么。

### S74-D：产品 DecisionPoint 与删除清单（P1）

真实任务完成后，只允许选择以下一项：

| 决策 | 条件 |
| --- | --- |
| 继续维护默认关闭 | opt-in 有价值但样本不足，或复杂路径优势不稳定 |
| 扩大显式 opt-in | 完成率、耗时、恢复与用户叙事均优于串行基线 |
| 回退/删除复杂路径 | 复杂路径没有带来明确收益，或维护成本显著高于价值 |

全局默认开启 parallel writes 必须是新的产品 DecisionPoint，不由 S74 自动批准。

### S74-E：复杂度价值审计（P1）

不是把现有大代码库整体推倒，也不是继续默认保留。按行为路径而不是按文件行数审计：

1. 建立当前默认路径 Golden Trace，固定结果正确性、安全边界和用户可见行为。
2. 为每条候选复杂路径标注 owner、用户价值、真实调用入口、eval、维护成本和退出条件。
3. 没有真实入口、没有 eval、只服务历史单点失败或与其他路径重复的实现进入冻结/删除候选。
4. 一次只停用或删除一条路径，使用相同 Golden Tasks 配对复验。
5. 删除后结果、安全和恢复不退化，且主路径更短或更易维护，才完成清算。

审计优先级：

| 优先级 | 对象 | 原因 |
| --- | --- | --- |
| P0 | 默认主路径中的重复 retry / repair / review 重入 | 直接影响用户等待与收敛 |
| P0 | JSON action 与 native `tool_use` 双路径 | 必须用配对 eval 决定默认、opt-in 或回退 |
| P1 | 只服务历史 failure-tail 的 parser/gate/recommendation 分支 | 最容易形成面条代码 |
| P1 | 重复 summary / progress / evidence 投影 | 容易造成真源冲突 |
| P2 | maintainer-only orchestration 与验证壳 | 默认隐藏，确认无调用后再合并或删除 |

全系统队列、裁决字段与横向反查清单见 [`S74_COMPLEXITY_LIQUIDATION_REGISTER.md`](./S74_COMPLEXITY_LIQUIDATION_REGISTER.md)。清算范围不限于上表；任何发现的重复语义、无消费者 evidence、只为 probe 存在的产品代码、永久 flag、历史 fallback 和劣质自研抽象都必须进入登记表。

## 3. 四个产品方向的关系

| 方向 | S74 中的任务 |
| --- | --- |
| Runtime 主循环 | 恢复 Execute 基线；验证失败进入 repair/replan/ask/stop；保持 bounded |
| Studio Session | 产品收敛优先；删除固定内部 workflow 面板；下一步动作跟在会话结果之后；不新增无证据面板 |
| Inspector / Evidence | 验证 route、worker、validation、merge 可查证；不进入主叙事 |
| Provider / Gate / Validation | 真实 provider 校准 deadline/route；gate 仅保留能驱动恢复或安全的规则 |

## 4. 停止规则

- 基线未全绿，不开新功能 Slice。
- pulse 不可复现，不接受新的 signoff。
- 没有真实 Beta 任务证据，不扩大默认权限。
- 模型输出宽泛时，先简化 prompt/schema/主流程，不新增 parser 分支。
- 复杂能力没有可衡量收益时，允许删除或回退。
- Runtime 主路径基线足够后，暂停后端能力扩展，优先修复 Studio 会话心流、权限护栏和可查证交互。
- 不把 model/tool calls、repair/replan 或耗时 SLO 直接升级为所有任务的 Runtime 硬停止条件。
- 没有 reference、eval 和退出条件，不接受改变 Agent 自主边界或默认路径的研发建议。

## 5. S74 完成定义

1. 文档真源一致，无过期 active 计划。
2. Execute 完整集成测试全绿。
3. S73 与 steady pulse 可复现。
4. 3–5 个真实 Beta 任务形成统一结果报告。
5. Studio/runtime/evidence 对同一任务结论一致。
6. 产生下一阶段 DecisionPoint，并明确保留、扩大或回退哪些复杂能力。
7. 完成第一批复杂度价值审计，形成带证据的保留、冻结、合并和删除候选清单。
8. 所有审计项使用 ADR-0011 四道裁决门；确认劣质实现后停止修补并执行替换或删除。

## 6. 当前收敛进展（2026-06-08）

- Execute 完整集成：`43 passed`。
- Runtime verification 护栏：候选工作区内安全重定向允许执行，越界重定向会替换为计划内验证。
- Studio 主会话：删除固定 `WorkflowMonitorCompact`；下一步动作跟在会话结果之后；权限请求只在 session timeline 显示一次。
- Studio 页面交互：`smoke:interactive-main-path` 的 Continue、Accept、Allow、Cancel 与 Composer slash action 共 `3 passed`。
- 下一轮产品切片：会话文件 chip / 整轮 diff / `Review changes` 统一打开 Inspector diff review；Accept 前保留只读查证入口。
- `Review changes` 会显示当前工作区改动数量（存在时）；只打开查证区，不触发写操作或 runtime 状态迁移。
- 权限卡采用生产侧 `permission_preview`：Action / Impact / Scope / Network / Risk / Reversibility；受控 runtime action 的权限要求与预览共用同一个 action profile，原始 command 仅供 Inspector 查证。
- 新权限卡有语义预览时不再重复旧通用确认文案；旧 run 缺少 `permission_preview` 时继续兼容显示兜底说明。
- Runtime request 已生产真实 `read_scope` / `write_scope` / tool 范围预览；DecisionPoint、user progress 与 Studio 共用该语义契约，旧 run 仅从结构化 `runtime_requests.jsonl` 补全。
- `model-check` 新增 `call_health`，区分“最终成功”和“健康主路径”；streaming fallback 成功必须标记为 `degraded`。
- 真实验收运行器在源码 checkout 中默认把当前 `src/` 注入子进程 `PYTHONPATH`；安装包验收仍使用其自身环境。禁止用机器上旧安装包的通过结果冒充当前源码签字。

### 2026-06-08 当前源码真实灰度诊断

`validation_small_cli` 在旧安装包路径曾于约 58 秒通过；修正验收源码绑定后，当前源码在 240 秒预算内失败。证据显示：

- 6 次模型调用，0 次工具调用，说明主要耗时发生在可执行动作之前。
- medium goal spec 约 13 秒；首次 coder 约 14 秒但 streaming fallback，随后 repair/coder 遭遇 provider SSL/streaming failure。
- review strong route 单次占满约 90 秒 deadline，随后 medium review 成功，但场景总预算已耗尽。
- 当前 P0 不是增加 timeout 分支，而是提高简单任务第一轮可执行动作率、压缩 goal/coder/review 上下文，并让低风险小任务避免不必要的 strong review。
- 托管沙箱内的 pulse 子进程仍受系统 temp/cache ACL 限制；直接契约测试已通过，不以继续堆环境分支作为产品研发任务。

### 2026-06-08 Fast-path 动作与上下文校正

- 有明确工作范围的任务，首轮没有执行或验证 observation 时不得选择 `stop`。Runtime 仍接受六种 loop action，只拒绝自相矛盾或没有依据的退出。
- `stop` decision 不得同时携带 tool calls 或 runtime requests。
- slim Coder context 只保留 task contract、scoped context package、最近 observation、role contract 和精简能力名；全工作区文件、memory、完整能力注册表和重复 tool surface 继续持久化为 evidence，不进入 prompt。
- GoalSpec 使用角色上下文投影，不再接收完整 Runtime 能力环境。
- Review deterministic-first 对简单产物保留轻量验证；bugfix 仍必须有真实命令验证。
- 聚焦回归：documentation contracts `11 passed`；Plan/Execute/Review/Run 相关契约 `95 passed`。
- 当前源码真实 `validation_small_cli` 仍因 provider TLS 不稳定失败。Coder context estimate 已从约 `24.8k` 降至 `8.0k` tokens，随后 Coder 调用在返回 action 前遭遇 SSL EOF。此前 GoalSpec 调用约 `26.5k` input tokens，因此继续完成了 GoalSpec 角色上下文投影。
- 角色上下文投影后的当前源码真实灰度已通过：`validation_small_cli` 风格任务耗时 `32.565s`，2 次模型调用、3 次工具调用、0 repair、0 strong call；首轮 Coder 返回 tool action，写入 `greet.py` 并通过两条真实命令验证，Review 走 deterministic-first。
- GoalSpec context estimate 从约 `32.8k` 降至 `1.4k` tokens，真实 input 从约 `26.5k` 降至 `1.3k`；Coder context estimate 约 `8.0k`。证据：`.asteria/verification/s74-role-context-gray.json`。
- 下一步继续用 2–4 个真实 Beta 任务检查角色上下文投影是否对 doc update、bugfix、subagent 路径同样成立；不得为单次 provider outage 增加 recovery/parser 分支。

### 2026-06-08 Beta 验证扩展

| 路径 | 结果 | 调用与耗时 | 结论 |
| --- | --- | --- | --- |
| 当前源码 doc update | 通过 | `64.842s`；3 model calls；2 tool calls；0 repair；medium only | 角色上下文主路径成立；streaming fallback 与一次 compact 仍有优化空间 |
| 当前源码 bugfix + repair | 通过 | `94.635s`；5 model calls；4 tool calls；1 repair；medium + strong | 失败正确进入 repair 并完成验证；strong review streaming failure 是主要耗时证据 |
| subagent Execute 机制灰度 | 通过 | 4 条集成路径全绿；spawn fake pulse `23/23` | 父子 evidence、bounded child loop、readonly fanout 与写入阻断成立；尚缺真实 provider 模型主动选择 subagent 的任务证明 |
| 文档真源与维护 pulse | 通过 | documentation contracts `13 passed`；maintainer pulse 全绿 | pulse 已从 `vibe_slices.json` 动态读取 S74，旧 active 值与过时过程计划已清理 |

当前判断：

1. 默认单任务与 repair 主路径已经可用，不新增 parser/recovery 尾巴。
2. 下一项最高价值验证是“真实 provider 模型选择 subagent 并回收结果”；在此之前不扩大 subagent 默认使用面。
3. bugfix 的 strong review 需要继续观察真实样本；若持续拉长简单任务，优先收缩 route/prompt，而不是增加 timeout 分支。
4. L3 与 parallel writes 仍保持显式 opt-in，只有真实任务证明收益后才进入 DecisionPoint。

### 2026-06-08 真实 provider subagent 主路径验证

任务明确要求委派独立 subagent 审查四份文档并回收报告。运行最终完成、Review 通过，但真实 evidence 显示：

- 首轮与恢复后的 `AgentLoopDecision` 都选择 `tool`，未选择 `subagent`。
- 两个 worker 均为 `primary`；`subagent_child_plans.jsonl` 不存在。
- GoalSpec 首轮遗漏 `input/` read scope，正常读取触发 DecisionPoint；批准后同一 session 能恢复并完成。
- 生成报告文本自称 `Reviewer: Subagent (CoderAgent)`，但执行 evidence 不支持该声明。
- run 已完成且 blockers 为空，但 `final_report_summary.next_actions` / `goal_policy` 仍残留已解决的 `decide --decision-id decision-0001`。

结论：当前不能签字“真实 provider subagent 主路径可用”。下一步不应增加更多 spawn 规则，而应修正三处主链契约：

1. GoalSpec/TaskPlan 必须保留用户明确的 delegation intent 与所需 read scope。
2. 用户可见角色声明必须来自 worker/dispatch evidence，不能来自模型自由文本。
3. decision resolve + resume 完成后必须刷新 final summary 与下一步，清除已解决 DecisionPoint。

证据目录：`.asteria/tmp/s74-real-subagent/.asteria/runs/run-20260608-0001/`。

### 2026-06-08 明确委派契约纠正与复验

本轮不新增 spawn 规则，而是按成熟产品的控制面原则统一修正执行事实契约：

- 新增窄 `execution_preferences`：用户明确要求的 delegation 与 read scope 从原始目标进入 GoalSpec/Task；模型不能自行扩写权限。
- Runtime 在父任务首轮校验 `delegation=required`；模型若返回直接 tool action，统一纠正为 `subagent`，child worker 不重复委派。
- 显式 read scope 采用能力增量语义，与默认可读输出路径合并，不再覆盖已有能力。
- run 完成且无 pending DecisionPoint 时，final summary / active goal memory 清除已解决的旧 `decide` 指引。

纠正过程：

1. 首次复验已产生真实 `subagent` decision 与 child evidence，但发现显式 `input/` 覆盖默认输出 read scope；改为增量合并。
2. 第二次复验发现 GoalSpec 模型自行加入历史 `reports/`；改为执行控制只从用户原始目标提取。
3. 干净 workspace 复验最终完成、Review 通过、输出存在，`input/` scope、subagent dispatch、child plan 与最终结果一致。

复验结论：

| 项 | 结果 |
| --- | --- |
| delegation truth | 首轮 `subagent` decision；`agent_loop_execution_results.jsonl` 有 dispatch；`subagent_child_plans.jsonl` 存在 |
| scope truth | GoalSpec requested read scope 仅 `input/`；Task 在此基础上合并默认可读输出路径 |
| final state | completed；Review pass；0 blocker；下一步 `accept` |
| 成本 | 约 10 分钟；17 model calls；多轮 repair |

当前签字：**明确委派事实契约可用，但 subagent 默认路径效率不合格，暂不放量。**

下一项最高价值工作不是增加更多编排能力，而是减少父任务重入、child 无效 JSON、Debug 重写和重复 Review 调用；目标是让同类小任务在保留 evidence/权限隔离的前提下恢复到分钟级。

证据目录：`.asteria/tmp/s74-real-subagent-clean/.asteria/runs/run-20260608-0001/`。
