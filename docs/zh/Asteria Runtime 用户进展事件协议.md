# Asteria Runtime 用户进展事件协议

> 2026-05-28 同步记录：`user_progress.jsonl` 现在是 Tool 权限决策的用户侧主线。每次 Tool 调用前必须记录 `permission/permission_decision`，并在 `data.capability_decision` 中包含 `decision`、`allowed`、`requires_decision`、`intent`、`task_kind`、`risk`、`permission_mode` 和 `reason`。对应原始证据写入 `capability_decisions.jsonl`，执行观察写入 `tool_observations.jsonl`。MCP/Skill 接入真实执行路径时复用同一字段格式；Studio/CLI 只消费这些 runtime-native 事件和 artifact/evidence refs。

> 2026-05-28 追加同步：权限决策审计入口已收敛为 `CapabilityDecisionRecorder`，但 Tool、MCP、Skill 不是同一种执行机制。Tool 走本地工具网关和 `tool_observations.jsonl`；MCP 应走外部 server/session/protocol 调用入口；Skill 应走按需加载的过程知识/产物能力入口。三者只共享 capability decision 记录格式：先生成并持久化 `capability_decisions.jsonl` 与 `permission/permission_decision`，再进入各自执行层；readiness/gate 统计 reason 覆盖率。

> 2026-05-28 MCP adapter 同步：`McpAdapter` 已接入真实 MCP protocol/session 调用入口。MCP 调用结果写入 `mcp_invocations.jsonl`；用户进展为兼容现有 schema 暂使用 `channel=tool,event_type=tool_output`，并在 `data.capability_type=mcp`、`data.adapter=mcp_protocol_session`、`data.mcp_invocation` 中标明这是 MCP 事件。权限决策仍先写 `permission/permission_decision`，不复用 `ToolExecutionGateway`。官方 `@modelcontextprotocol/server-everything@2026.1.26` 已完成真实 stdio smoke，当前 stdio framing 为 JSONL。

> 2026-05-28 工具边界纠偏：这里的 Tool 事件当前指 Asteria 内部 runtime tool registry 的调用事件，不代表完整模型侧标准工具集。后续新增模型-facing tool surface 时，仍应复用 `permission/permission_decision` 与 observation 协议，但工具命名、参数 schema、展示策略和执行 adapter 需要单独建模。

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
- `file_changed`
- `evidence`
- `decision`
- `model_decision`
- `validation_result`
- `final_report`
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
- `/run` 的用户过程线已补齐 workspace/input/output 选择、输出与 artifact 落点、模型路线判断、文件变化摘要、验证结论和最终报告落点；这些信息同时进入 `user_progress.jsonl` 与 `final_report_summary.json`。
- provider streaming 已写入 `model` channel：流式路径会记录 `start / delta / end / error`，非流式路径也会以同一协议记录开始、完整响应和结束。
- `ToolExecutionGateway` 已写入 `tool` channel：工具开始、工具结束、工具失败都会形成结构化事件，并保留 `tool_call_id`、命令摘要、耗时和调用链。
- 文件写入类工具已写入 `file` channel：`write_file`、`apply_patch`、`restore_backup` 的成功结果会记录文件路径、操作类型和备份引用。
- `studio-benchmark` 已作为用户侧内测基准入口存在，但当前真实任务覆盖仍未跑满，不能视为用户内测已准备好。

## 9. 下一步开发重点

1. 继续把 `/resume`、`/review`、专业智能体和工具链路的细分节点接入同一协议，让真实任务的计划、执行、验证、修复都能被用户看懂。
2. Studio server 优先读取 `user_progress.jsonl`，只在旧 run 缺少该文件时回退到历史证据；这一步是薄事件消费，不代表完整 Studio UI 进入 Runtime 后端 P0。
3. Studio 前端按用户任务主线展示 `display_level=main`，把命令、stdout、schema、原始证据放到 Inspector。
4. 扩展 `studio-benchmark`：检查 `model/tool/file/evidence` channel 覆盖率，以及五个真实用户任务是否完成到可复盘程度。
