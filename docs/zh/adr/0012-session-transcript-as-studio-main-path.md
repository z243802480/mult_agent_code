# ADR-0012: Session Transcript as Studio Main Path

日期：2026-06-09
状态：Accepted

## 背景

ADR-0007 试图用 `runtime_progress` 统一 Status、Chat、Final Report 和 Studio 的产品进度。实际演进后形成了多个互相兜底的数据源：

- `user_progress`
- `main_path`
- `runtime_progress`
- `final_report_summary.runtime_progress`
- `run_loop_summary.runtime_progress`
- Studio 对上述对象和 raw event 的 narrative 重建

这使 Runtime、Status、Final Report 和 Studio 都在重新推导“用户看见什么”。Studio 甚至会在没有主会话事件时，根据内部 progress 和 summary 猜测 Plan、Tool Use、Verify、Next step 与 Final。该实现偏离 Claude Code / Codex 的 Session 驾驭方式：过程和结果应作为连续消息进入 Session，诊断对象不应反向生成主会话。

## 决策

Studio 主会话采用 Session Transcript 单一真源：

```text
user_progress(display_level=main, transcript_kind=...)
  -> Studio Session Transcript
  -> conversation turns
```

### 主路径

- Runtime 在真实生命周期边界生产用户语义事件。
- Studio 主会话只消费 `user_progress` 中 `display_level=main` 的事件。
- `transcript_kind` 和事件正文决定会话叙事；Studio 只负责展示、分组和 evidence 联动。
- 最终结果必须由 Runtime 写入 `final | stop` 事件，不允许 Studio 根据 run status 或 summary 猜测最终回答。

### 诊断与兼容

- `runtime_progress`、`main_path`、final/run loop summary 继续服务 CLI Status、Inspector、诊断和旧消费者。
- 老 run 没有 `user_progress` 时，Studio 可以使用隔离的 legacy event adapter。
- legacy adapter 不得读取多个 summary 并合成看似真实的 Session Transcript。
- Inspector 可以读取所有 raw evidence，但不得反向注入主会话。

## 删除内容

- 删除 Studio 从 `runtime_progress` 合成 Plan/Tool/Verify/Next-step 会话事件的实现。
- 删除 Studio 从 final summary、run summary 或 workflow state 猜测 Final message 的实现。
- 删除主窗口顶部基于 `runtime_progress` 推断固定 Understand/Plan/Execute/Verify/Result 的 `WorkflowPhaseStrip`；真实过程只在 Session Transcript 中出现。
- 后续逐步删除 Studio 主会话中根据内部 channel/event/provider wording 推导用户语义的兼容逻辑；生产侧补齐后即可移除对应 fallback。
- 当前实现已要求新主路径事件携带 `transcript_kind`；缺少该字段的 `user_progress` 不进入新 Session Transcript，而由 run-detail 提供的 legacy events adapter 负责旧 run 展示。

## 验收

- 有 `user_progress` 的 run：主会话事件严格来自用户进展事件。
- 缺少 `final | stop` 时：Studio 不制造最终回答。
- 缺少 `user_progress` 的旧 run：使用已有 legacy events，不使用 `runtime_progress` 合成会话。
- Runtime progress、route、gate、worker、summary 仍可在 Inspector 查证。

## 后果

主会话真源从“多个内部状态的前端重建”回归为“Runtime 生产的连续 Session Transcript”。这要求 Runtime 对用户语义事件负责，也让 Studio 不再承担穷举模型行为和修补后端状态矛盾的责任。
