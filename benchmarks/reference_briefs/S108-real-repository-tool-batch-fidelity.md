# S108 — 真实仓库自主修复与工具批次结果保真

用户 2026-11-10「继续吧」，承接 S107 下一步：在真实仓库目标中验证自主排错，不人为延长时长。

## 任务与待证问题

目标仓库为当前 Asteria 的跟踪源码快照，实际生产运行时冻结在 main@57f6274（代码同 7e0055c）。静态审查发现 execute_tool_calls 整批捕获网关异常并只投影为首工具失败；若后续调用触发权限异常，已执行前缀的结果可能丢失、失败工具名错配、后缀去向不明。先用实际网关/权限层复现，再把修复作为真实 repo 的完整目标交给冻结 harness。

参考机制（2026-11-10 一手源）：
- [Anthropic Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)：工具结果以 tool_use_id 关联对应调用，错误以 is_error 明确反馈。
- [Codex-rs ToolOutput](https://github.com/openai/codex/blob/main/codex-rs/tools/src/tool_output.rs)：具体结果按 call_id 转换；[tools/parallel.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/parallel.rs) 为调用保持对应结果。借鉴结果归属/错误反馈，不复制专有实现、不新增并行。

## 边界与验收

- 初始真实仓库输入来自 Git 跟踪文件，排除保护路径、本地运行数据及既有未跟踪验证目录；在 WSL 隔离快照中运行。完整本地现有测试可读，禁止修改原测试/保护文件/冻结运行时；新增回归文件可写。
- 修复仅围绕工具批次的结果归属、已完成前缀和异常/未执行后缀表达。模型自行诊断、规划、实现和验证；不预先提供补丁或算法。权限/预算/用户暂停等硬边界仍生效，不允许为了执行后缀越过拒绝，不重放已完成副作用，不把失败/缺失结果写成成功。
- 可改 core/model_driven_turn.py、core/tool_execution_gateway.py、必要的窄辅助模块及新增专用测试；避免 execute/run 等无关重构。MCP/skill 路径不能因修复丢证据。旧 stop_on_failure 默认语义保持，接口尽可能兼容。
- 预先固定独立验收：真实网关后续权限失败时前缀成功不能丢/错名、后缀副作用不发生；同名多调用不会混淆参数；工具返回失败和抛异常都正确；异常后重试不重复副作用；model feedback 与持久化证据归属一致；单调用/全成功、别名及现有 MCP/skill 回归保持。
- 最多单次 60 分钟、默认全局预算，正常 auto 权限。运行中不修改解答或追加提示；失败就留账，不为凑时长/刷通过重复运行。完成后外部独立检查、现有回归、Ruff/类型棘轮、Review/Accept，再审核产物是否可合回当前仓库。
- 只证明实际完成的范围/时长。真实仓库修复通过不等于一到三小时稳定性已过；若 harness 卡住，修通用原因须另记研发介入，旧样本不抹掉。

ACTIVE_SLICE=S108。两轮真实目标均未自主完成；工程修复及失败原因见 S108 报告，不计零介入成功。


## 首轮新增摩擦：16 轮默认截断使真实工程重复导航

实际运行跨多次 max_rounds=16 自动续作，仍无实现改动；task_progress 仅保留一行动作摘要，新的调用链理解没有延续。本方正常 pause 一次保存失败，原目标未完成，运行内解答改动/提示 0。

[Claude Agent SDK agent loop 官方文档](https://code.claude.com/docs/en/agent-sdk/agent-loop) 的 max_turns 默认不限（可显式设置），与费用限制分开；[Python SDK 源码](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py) 同样为 None。该参考不意味着取消本项目预算：这里只去掉预算内每 16 轮重置历史的隐性默认，把默认单任务保险丝对齐现有 goal 模型调用预算（默认 200、尊重 active_budget_profile）；显式 max_turn_iterations、小预算、权限/暂停/上下文硬闸及全局计数不变。不加无限循环，不叠新记忆/状态机。

允许在 execute_command._model_turn_iteration_fuse 做这处窄改并更新对应单测；这属于已授权自主环修复，不做无关重构。确定性证明必须覆盖跨 16 轮读取后写入验证仍在同一对话，旧 FSM round 配置不再暗中截断，显式短 fuse 仍生效、小预算不扩大、profile 生效。通过后重新冻结运行时，从相同原始目标快照完整重跑一次，不向模型提供原问题补丁，独立 oracle 保持原字节。首轮与重跑分记研发介入，不拼成零介入成功。


预算边界补验：原压力检查主要在外层执行/续跑边界；长对话不能把 0.90 hard-stop 推迟到 200 次。默认 fuse 调整需同时由纯循环接收预算边界回调，在下一模型调用及工具批次前检查全局实际压力；命中保留观察并以既有 budget_hard_stop 退出，不补跑验收工具、不当用户暂停、不自动重规划。使用既有 DecisionPoint 路径交还人审。回归覆盖首轮已到硬闸、模型调用后到硬闸、工具后到硬闸、完成前停止且历史证据保留。该窄预算接线允许触及 execute/run 与纯循环，显式权限和预算数值不变。若真实运行使用预算接线前冻结原型，必须写清，不能声称该原型与最终代码逐字相同。


第二轮因前置诊断的验收/修复契约停下，未自主交付；不再盲目刷样本。已复现批次缺陷由主代理修复，并补 actual _SubagentAwareToolRunner 的结果/副作用顺序：保留相邻专家批次并发，不允许提前跨过前序拒绝；原并发默认不变。原字节 oracle 9/9 仅证明该工程修复，不能算原目标由 harness 完成。默认 fuse 的最终版本同时含每轮成本硬闸，原型曾撞预算丢摘要的测试失败如实保留；更新摘要测试的显式短 fuse 后，以额外真实小预算集成验证停止/持久化/DecisionPoint，而非删掉断言。

预算检查复用 BudgetController 同一方法，并接到 LocalExecutor 的已有专家循环，避免只保护主循环。没有实际调用新子代理或改变专家并发开关；确定性假模型验证共享预算到限时专家零模型/工具调用。

收口回执：主代理工程修复在 9982169 的 Verify 42824687289 三 job 全绿；真实目标两轮失败、最终版本尚无新的真实目标样本，不能关闭自主完成缺口。下一步只读诊断/恢复及验证时限，不开新编排 Wave。
