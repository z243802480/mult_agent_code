# S74 Post-S73 Beta Convergence 实施计划

更新时间：2026-06-08
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

## 5. S74 完成定义

1. 文档真源一致，无过期 active 计划。
2. Execute 完整集成测试全绿。
3. S73 与 steady pulse 可复现。
4. 3–5 个真实 Beta 任务形成统一结果报告。
5. Studio/runtime/evidence 对同一任务结论一致。
6. 产生下一阶段 DecisionPoint，并明确保留、扩大或回退哪些复杂能力。

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
