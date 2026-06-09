# ADR 0007: RuntimeProgress 作为产品主路径对象

日期：2026-06-03

## 状态

Superseded by ADR-0012

> `runtime_progress` 继续作为 CLI Status、诊断和兼容对象存在；本文关于 Studio 主屏消费 `runtime_progress` 的决策不再生效。

## 背景

Asteria 已经具备 `main_path`、`todo_view`、agent loop decision / execution / observation、run loop summary、final report summary 等 evidence。但如果 CLI、Chat、Status、Studio 分别读取这些对象并自行拼装“当前进度”，产品会重新滑向多套状态心智，用户和模型都需要理解过多内部细节。

参考 Claude Code 一类成熟 agent 产品时，应保留一个简单主路径：

```text
Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop
```

权限、Hook、schema、sandbox、provider route、context budget 和 raw evidence 应作为外围控制与 Inspector 信息，而不是默认主屏心智。

## 决策

新增 `runtime_progress`，作为 Runtime-facing / product-facing 的稳定进度对象。

它折叠以下 evidence：

- `main_path`
- `todo_view`
- latest task execution evidence
- latest AgentLoopDecision
- latest AgentLoopExecutionResult
- latest AgentLoopObservation
- agent loop / run loop summary
- validation conclusion

默认消费者应优先读取 `runtime_progress`：

- `status --json`
- `sessions --context`
- `chat` session context
- `final_report_summary.json`
- `run_loop_summary.json`
- 后续 Studio 主屏

旧字段继续保留，作为向后兼容和 Inspector/raw evidence 入口。

## 设计约束

- `runtime_progress` 不新增 gate，不新增命令，不做额外阻断。
- 它只折叠已有证据，避免各层重复推断。
- 默认 UI/Chat 展示应以 Todo、Tool Use、Verify、Next Command、Stop Reason 为主。
- provider route、capability catalog、context pressure、worker tree、promotion queue 等诊断信息默认进入 Inspector 或 maintainer 层。
- 当 evidence 不足时，`runtime_progress` 应表达 unknown/pending，而不是制造新的 hard block。

## 后果

正面：

- Status、Chat、Final Report、Studio 可以消费同一个进度对象。
- 接受后的 `next_command`、loop exit、todo/verify 状态不再互相矛盾。
- 后续做 Studio 时不需要继续收敛 CLI 命令展示，先消费统一 evidence。

风险：

- `runtime_progress` 如果继续膨胀，会变成新的大杂烩。
- 新字段必须保持“产品主路径对象”，raw diagnostics 不能塞入默认层。

## 后续

- Execute/Chat/Status 继续围绕 `runtime_progress` 保持展示一致。
- Studio MVP 主屏优先消费 `runtime_progress`，Inspector 再展开 raw evidence。
- 真实 provider 小任务滚动验证时检查 `runtime_progress` 是否足够解释当前进展和下一步。
