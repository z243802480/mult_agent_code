# Studio 会话与上下文设计准则

状态：`design`

更新时间：2026-06-03

本文是 Asteria Studio 的长期体验约束，专门约束 session 管理、context 管理、主会话展示和 Inspector 诊断层。它不是 UI 灵感清单，而是实现前必须遵守的产品规则。

参考来源：

- Claude Code 官方文档：[How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)，session 绑定当前目录，context window 包含 conversation history、file contents、command outputs、CLAUDE.md、auto memory、skills 和 system instructions；接近上限时会先清理旧 tool outputs，再必要时总结会话，并提供 `/context`、`/compact`。
- Claude Code 官方文档：[Memory](https://code.claude.com/docs/en/memory)，CLAUDE.md / rules / auto memory 是持久规则和项目记忆，不应依赖早期对话长期保留；规则可按路径和任务组织，避免把所有内容塞进常驻上下文。
- Claude Code 官方文档：[Claude Code on the web](https://code.claude.com/docs/en/claude-code-on-the-web)，sessions 在侧边栏管理，context 命令和 auto-compaction 是会话体验的一部分；subagent 可使用独立 context window，保持主会话轻量。
- Claude 官方博客：[Using Claude Code: session management and 1M context](https://claude.com/blog/using-claude-code-session-management-and-1m-context)，同一任务继续同一 session，走错路用 rewind，session 膨胀时用 compact；session 和 context 管理直接影响结果质量。
- OpenAI Codex 公开资料：[Codex use cases](https://developers.openai.com/codex/use-cases) 与 [AGENTS.md scope/precedence](https://github.com/openai/codex/blob/main/codex-rs/core/prompt_with_apply_patch_instructions.md)，以及当前 Codex App 体验：AGENTS.md 层级指令、sandbox/approval 边界、主会话中的过程消息、侧边 Inspector 的环境/Git/上下文/文件/终端入口。
- 用户提供的 Claude Code / Codex 截图：Claude Code 主窗口按时间展示过程、命令、失败、重试、总结和下一步；context window 作为底部可展开状态；Codex App 右侧 Inspector 更像环境/文件/浏览器/审查/终端入口，而不是主路径内容容器。

## 1. 总体结论

Studio 的主产品形态必须是“会话式工作流”，不是“运行时 dashboard”。

用户应该看到一条连贯 session：

```text
用户目标
-> 模型理解与计划
-> 工具/命令/文件操作的简短过程消息
-> 失败、重试、权限请求或用户决策
-> 验证与结果
-> 最终总结、风险和下一步
```

过程信息不是藏起来，而是以 message / turn 的方式进入主会话。原始证据、长 JSON、route、schema、worker graph、context attribution、provider telemetry、run files 等进入 Inspector。

## 2. 主会话设计准则

主会话是用户理解任务的唯一主线。

必须进入主会话：

- 用户原始目标和 Asteria 对目标的理解。
- 计划摘要和当前 todo。
- 关键工具使用：例如“读取项目规则”“运行测试”“修改 3 个文件”“检查 Git diff”。
- 工具失败和恢复动作：例如“push 失败，正在重试”“测试失败，进入 repair”。
- 权限请求和用户选择。
- 验证结论：通过、失败、未能验证及原因。
- 最终总结：做了什么、验证了什么、剩余风险、下一步。

不得默认进入主会话：

- run_id、worker_id、provider route、raw schema、JSONL 文件名、evidence bundle path。
- 大段 stdout/stderr、完整 traceback、完整 diff、完整 model telemetry。
- gate-status、capability-report、validation、route guidance 等维护命令名。
- 仅对维护者有意义的内部阶段名和字段名。

主会话可以包含可折叠过程块，但折叠块必须是用户语义，例如：

```text
Ran 2 commands
Read 4 files
Updated 3 files
Verified with pytest
Background task failed
```

不要使用：

```text
Runtime snapshot
Run activity
agent_loop_execution_results.jsonl
route_guidance.status
worker topology roots=1
```

## 3. Session 管理准则

每个 Studio session 应对应一个用户心智上的任务上下文，而不是一个 backend run。

Session 应包含：

- 用户消息。
- Asteria 的过程消息。
- tool / permission / file / verification 的用户级摘要。
- 最终回答。
- 被选中的 workspace、branch、permission mode、model strategy。
- 与 runtime run/evidence 的引用。

Session 不应直接等同于：

- 单个 `.asteria/runs/<run_id>`。
- 一次 CLI invocation。
- 一个 validation run。
- 一个 worker invocation。

一个 session 可以关联多个 run。多个 run 的过程必须被折叠成用户可理解的连续叙事，而不是让用户自己在 run 列表里拼接。

Session 侧边栏应展示：

- 任务标题。
- 最近更新时间。
- 状态：working / needs input / ready to review / completed / blocked。
- 少量结果信号，例如 modified files、pending decision、background task。

侧边栏不展示 run id、gate 状态矩阵或 evidence 文件名。

## 4. Context 管理准则

Context 是运行时资源，也是用户可理解的工作状态，不是后台 token 表。

Studio 应区分五类 context：

| 类型 | 含义 | 主会话展示 | Inspector 展示 |
| --- | --- | --- | --- |
| startup | 系统、项目规则、AGENTS/CLAUDE 类指令 | 只在需要时提示“已加载项目规则” | 具体文件、大小、加载原因 |
| durable | 长期目标、用户偏好、项目记忆 | 摘要和可恢复状态 | active memory、snapshot、来源 |
| working | 当前任务相关文件、计划、证据 | 当前计划和关键文件 | 文件列表、hash、diff refs |
| transient | 最近命令、临时观察、短期思考 | 简短过程消息 | tool call / observation 明细 |
| tool-output | 命令输出、测试日志、大段 stdout | 摘要、失败原因、下一步 | 完整输出、截断策略、raw path |

Context window 指示应作为“可展开状态”，类似用户截图里的 context window popover：

- 默认只显示比例和健康状态。
- 展开后显示 Messages、Tools、Project rules、Memory、Tool output、Free space。
- near limit 时提示 compact 建议。
- hard stop 时必须解释为什么不能继续，而不是继续堆规则。

主会话不应持续展示 context attribution 表；这属于 Inspector。

## 5. Compact 与恢复准则

Compaction 是 session 体验的一部分，不是错误处理尾巴。

Compact 前必须保留：

- 当前目标。
- 当前计划和完成状态。
- 已接受决策。
- 修改文件和原因。
- 验证结果。
- 当前阻塞。
- 下一步。

Compact 后主会话应出现一条用户可读消息：

```text
Context compacted. Preserved the current goal, completed work, verification status, and next step.
```

Inspector 才展示 compact boundary、before/after token、droppable sections、snapshot path。

如果 context 反复 compact 后立即再次接近上限，应停止自动循环，向用户说明“某个文件或工具输出过大”，并给出缩小范围、清理日志、重新开始 session 或保存 handoff 的选择。

## 6. Inspector 设计准则

Inspector 是诊断层，不是主路径。

它应该做得强，但默认不抢主会话叙事。

Inspector 的职责：

- 当前选中消息的详情。
- 命令输出、tool observation、permission evidence。
- 文件 preview、diff、artifact、Git 状态。
- context window breakdown。
- worker topology、subagent evidence、candidate workspace、merge/promotion gate。
- provider/model route、deadline、token、cost。
- raw evidence files 和 schema refs。

Inspector 的入口可以常驻，但内容应基于“当前选中消息/当前 run/当前 workspace”联动。用户点击主会话里的过程块，Inspector 显示对应证据；用户点击 Inspector 里的 evidence，主会话可以定位到对应消息。

不要把 Inspector 里的 raw detail 同步复制到主会话。

## 7. 过程与总结格式

Claude Code 截图里最值得学习的是节奏：

```text
简短说明正在做什么
Ran N commands
关键解释
Ran / Read / Pushed / Verified
失败时解释失败性质
重试或降级
最后给出状态总结和下一步
```

Asteria 主会话应采用相同节奏：

1. 过程消息短。
2. 每个工具块可展开。
3. 失败要解释影响和下一步。
4. 最终总结必须比过程更清楚。
5. 背景任务可以以卡片存在，但只显示状态、原因和可执行动作。

最终总结建议固定为：

```text
结果
- 做了什么
- 验证了什么
- 还有什么风险

下一步
- 用户可选动作
- Asteria 可继续动作
```

## 8. Studio 实现硬约束

后续 Studio 改动必须满足：

- 主会话优先：新增状态展示前先判断是否应成为 session message。
- Inspector 次之：只有 raw / debug / evidence / telemetry / file detail 进入 Inspector。
- 不新增固定 runtime 面板承载过程叙事。
- 会话存在用户可执行下一步时，动作入口必须跟在对应过程与结果之后；不得固定在会话顶部抢占叙事。
- L3 workflow、worker topology、route、gate 等内部运行结构只进入 Inspector；主会话只展示它们产生的用户任务进展。
- 不在主屏默认展示 run id、JSONL 文件、route/gate/capability 内部名。
- context 信息必须以“健康摘要 + 可展开 breakdown”的方式展示。
- action button 只在有用户可执行下一步时出现；没有下一步时不要显示假按钮。
- 文件 chip、整轮 diff 与 `Review changes` 必须打开同一个 Inspector diff review，并定位对应 scope/file；不能只更新隐藏状态。
- `Accept` 前必须始终存在只读查证入口；打开查证区不应触发写操作或 runtime 状态迁移。
- 权限请求必须使用稳定的用户语义预览：Action、Impact、Scope、Network、Risk / Reversibility。原始 command 和 policy evidence 只进入 Inspector。
- Runtime request 的 `permission_preview.scope_detail` 是精确范围真源；Studio 只展示限长摘要，并保留完整 runtime request 供 Inspector 查证。不得让前端通过关键词推断文件范围。
- 只允许为有限产品动作定义 permission profile；不得让 Studio 通过关键词或事件类型穷举任意模型行为，也不得展示 Runtime 尚未实现的持久授权选项。
- Playwright smoke 必须验证主窗口 conversation turn，而不是只验证 Inspector 或固定卡片。
- 文案 smoke 必须继续拦截 backend wording 泄漏，但不能误伤数据结构字段。

## 9. 当前 Asteria 缺口

## 9.1 Studio 数据源边界

Studio 主会话必须遵守单一语义数据源原则：

- 主会话 timeline 只消费 `user_progress` 中 `display_level=main` 的会话事件。
- `user_progress.transcript_kind` 是首选语义来源；`channel` / `event_type` 只作为旧 run 兼容字段。
- `runtime_progress` 只用于补足没有 `user_progress` 的 run，并且必须先合成为用户语义：Plan/Todo、Tool Use、Verify、Next step、Result。
- Studio 不应继续手写大量 runtime event 映射。需要展示给用户的进展必须由 Runtime 生产侧先写成 `transcript_kind` + `ui_intent` 的主会话事件。
- `worker_results`、`workers.jsonl`、`agent_run_graph`、`model_calls`、`route_timeline`、`validation_results`、`raw_evidence`、run files 只能进入 Inspector。
- 如果 subagent/worker 的结果需要出现在主会话，Runtime 必须先写入 `runtime_progress.worker_summary` 或 `user_progress`，不能让 Studio 主屏直接解释 worker JSONL。
- Context window 主屏只显示比例、健康和 free space；context attribution、section breakdown、compact boundary、token/cost 明细只进入 Inspector。
- 最终回答必须固定成用户语义结构：Result、Verification、Risks / Next step。缺少验证或风险时也要明确说明“未记录”，不能把 raw evidence 当总结展示。

这条边界是产品约束，不是前端偏好。新增 Studio 功能前必须先判断：它是用户流程消息，还是 Inspector 诊断证据。

需要补齐：

- Studio session 与 runtime run 的多对多映射。
- context window popover。
- compact / handoff / resume 的主会话消息。
- 主会话过程块与 Inspector evidence 的双向定位。
- 最终总结模板和后台任务卡片。
- 主会话去噪：继续删除无用区域、重复状态、小字段堆叠和 maintainer-only 文案。

这些工作优先于继续增加新的 dashboard 面板。
