# Asteria Runtime 用户进展事件协议

## 1. 背景

Studio 当前已经能展示模型事件和 runtime 输出，但仍有硬编码风险：前端或 Studio server 会根据 stdout 猜测“结果”“下一步”。这只能作为过渡，不能作为产品内核。

正确方向是：runtime 在执行过程中主动产出用户可理解、机器可订阅的多通道事件，Studio 只负责展示和交互。

## 2. 事件目标

用户进展事件回答的是用户关心的问题：

- 当前在哪个 workspace 工作？
- 我的目标是否被理解了？
- 计划是什么？
- 现在执行到哪一步？
- 是否需要我授权？
- 产物和证据在哪里？
- 结果是什么？
- 下一步我可以做什么？

它不暴露内部状态机名、裸 stdout、临时 worker 细节或 schema 噪声。那些内容仍保留在 Inspector 和 evidence bundle。

## 3. 标准阶段

```text
understand -> plan -> execute -> review -> result -> next
```

特殊状态：

```text
blocked
```

阶段含义：

- `understand`：确认目标、约束、风险边界。
- `plan`：生成计划、任务拆分、验收标准。
- `execute`：执行工具、写文件、调用命令、生成产物。
- `review`：验证、审查、失败归因。
- `result`：正式结果。
- `next`：可选下一步。
- `blocked`：等待权限、模型、预算或用户决策。

## 4. Schema

正式 schema：

```text
src/asteria_runtime/schemas/user_progress_event.schema.json
```

最小事件：

```json
{
  "schema_version": "0.1.0",
  "event_id": "upe-...",
  "workspace_id": "workspace-...",
  "run_id": "run-...",
  "session_id": "session-...",
  "created_at": "2026-05-21T00:00:00Z",
  "sequence": 1,
  "channel": "progress",
  "event_type": "delta",
  "phase": "plan",
  "status": "running",
  "title": "制定计划",
  "summary": "正在把目标拆成可执行步骤。",
  "content_delta": "先确认交通、住宿、路线和预算。",
  "display_level": "main",
  "artifact_refs": [],
  "evidence_refs": []
}
```

`workspace_id` 用于把 Studio project switcher、CLI `--root` 和 workspace-local `.asteria/` 证据关联起来。事件文件本身必须落在当前 workspace 的 `.asteria/runs/<run_id>/user_progress.jsonl`，不能写到用户全局目录。

## 5. 多通道输出

runtime 需要同时支持一次性读取和流式订阅。事件先落盘为 JSONL，外部可以 tail、轮询、SSE 或 WebSocket 转发。

标准通道：

- `conclusion`：结论、最终结果、下一步。
- `progress`：用户可见任务进展。
- `model`：模型 start/delta/end/error、provider、route、token、耗时。
- `tool`：工具调用、shell 命令、stdout/stderr 摘要。
- `file`：文件创建、修改、删除、diff 摘要。
- `evidence`：产物、报告、验证、证据引用。
- `call_chain`：模型、agent、tool 的调用链。
- `execution_chain`：任务、worker、验证、promotion 的执行链。
- `diagnostic`：heartbeat、deadline、retry、fallback、budget pressure。
- `workspace`：workspace 切换、输出目录、candidate workspace、git/worktree 状态摘要。

事件类型：

- `message`
- `delta`
- `start`
- `end`
- `error`
- `tool_call`
- `tool_output`
- `file_created`
- `file_modified`
- `file_deleted`
- `evidence`
- `decision`
- `heartbeat`

这样 runtime 可以对外提供几种视图：

- 只看结论：过滤 `channel=conclusion`。
- 看用户过程：过滤 `display_level=main`。
- 看 shell/工具：过滤 `channel=tool`。
- 看文件变化：过滤 `channel=file`。
- 看证据：过滤 `channel=evidence`。
- 看诊断：过滤 `channel=diagnostic`。
- 复盘调用链：读取 `call_chain` / `execution_chain`。

## 6. 展示规则

Studio 主线程只展示：

- `display_level=main`
- 用户目标
- 模型/计划/执行/核对/结果/下一步
- 权限请求
- 文件和产物摘要

Inspector 展示：

- `display_level=inspector`
- runtime command
- stdout/stderr
- model telemetry
- evidence refs
- artifact refs
- raw events

## 7. 后续落地顺序

1. `plan` 在关键节点写入多通道 `user_progress_event`。
2. `run/review/resume` 继续接入同一协议。
3. Provider streaming 同步写入 runtime-native `model` channel，而不仅是 Studio session event。
4. Tool execution 写入 `tool` channel 和 `file` channel。
5. Studio server 优先读取 user progress event，不再解析 stdout 生成报告。
6. `studio-benchmark` 增加多通道覆盖检查。
7. 真实任务基准跑通后，再邀请第一个真实用户内测。
## 8. 当前落地进展

- `plan` 已写入 runtime-native `user_progress.jsonl`，覆盖 `understand / plan / review / result / next` 阶段。
- provider streaming 已写入 `model` channel：流式路径会记录 `start / delta / end / error`，非流式路径也会以同一协议记录开始、完整响应和结束。
- `ToolExecutionGateway` 已写入 `tool` channel：工具开始、工具结束、工具失败都会形成结构化事件，并保留 `tool_call_id`、命令摘要、耗时和调用链。
- 文件写入类工具已写入 `file` channel：`write_file`、`apply_patch`、`restore_backup` 的成功结果会记录文件路径、操作类型和备份引用。
- `studio-benchmark` 已作为用户侧内测基准入口存在，但当前真实任务覆盖仍未跑满，不能视为用户内测已准备好。

## 9. 下一步开发重点

1. 将 `/run`、`/resume`、`/review` 接入同一协议，让真实任务的计划、执行、验证、修复都能被用户看懂。
2. Studio server 优先读取 `user_progress.jsonl`，只在旧 run 缺少该文件时回退到历史证据。
3. Studio 前端按用户任务主线展示 `display_level=main`，把命令、stdout、schema、原始证据放到 Inspector。
4. 扩展 `studio-benchmark`：检查 `model/tool/file/evidence` channel 覆盖率，以及五个真实用户任务是否完成到可复盘程度。
