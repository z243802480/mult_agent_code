# Asteria Studio 用户侧工程设计哲学

## 1. 核心判断

Asteria Studio 不是 dashboard，也不是命令包装器。它应该是用户侧的智能体工作区，是 Asteria 面向通用智能体的独立产品交互面。后端 runtime 可以先完成，但 Studio 的交互设计不应被临时后端形态绑死。

用户真正需要的是：

- 我把目标告诉智能体。
- 智能体立刻回应并开始工作。
- 工作过程持续流式显示。
- 思考、计划、工具调用、命令执行、文件修改、权限请求都出现在前台。
- 完成后，过程可以折叠，正式结果清晰留在对话中。
- 用户基于结果继续指导下一步。
- 长时间任务可以持续推进、暂停、恢复、审查、导出证据。
- 文件预览/对比、Git、MCP、plugin、skills、session、用户、token、权限和模型配置都能在同一个产品心流里被理解和管理。

因此 Studio 的主体验必须像 Codex / Claude Code / OpenCode 这类 workspace 产品，而不是后台管理系统。

## 2. 为什么必须流式

长任务如果只是后台跑，用户会失去信任。

流式不是“接口支持 SSE”这么简单，而是产品体验的骨架：

```text
user goal
  -> assistant acknowledgement
  -> thinking/planning chunks
  -> tool/command start
  -> stdout/stderr or structured progress
  -> file/diff events
  -> permission request if needed
  -> review/result
  -> folded reasoning + final answer
  -> user continues
```

前台必须看到这些事件对应的“用户任务进展”，而不是后台流水账。否则即使后台真的在跑，用户也会感觉系统卡死或是假智能体。

关键修正：用户不关心智能体内部状态机本身，用户关心自己的目标推进到了哪里。

因此主线程默认显示：

```text
理解目标
制定计划
核对约束
执行/生成
总结结果
等待用户下一步
```

内部细节只进入 Inspector：

```text
runtime command
stdout/stderr
raw tool events
schema/evidence refs
internal runtime transition / role skeleton suggestions
```

## 3. 首页信息架构

首页只能是 Workspace，不能是 Dashboard。

```text
App Shell
  Left Sidebar
    Projects / Workspaces
    Sessions
    Search
    Settings entry

  Main Thread
    User messages
    Assistant messages
    Streaming reasoning chunks
    Tool/command cards
    Permission cards
    File change cards
    Final response cards

  Composer
    Natural language input
    Mode: Plan / Run / Continue / Review
    Permission mode
    Model route indicator

  Right Inspector
    Selected event detail
    Command output
    Files / diff / artifact preview
    Git status
    Token/cost budget
    Evidence refs
```

Dashboard 只能放在后台页：

```text
Observability
  Gate status
  Model routes
  Token/cost usage
  Acceptance history
  Evidence bundle
  Package/doctor status
```

## 4. 前台事件模型

前台不应该直接展示裸 stdout 或后台 job。stdout 只是详情。

必须有统一事件模型：

```json
{
  "event_id": "evt-...",
  "session_id": "studio-session-...",
  "run_id": "run-...",
  "type": "assistant_delta | reasoning_delta | tool_start | tool_delta | tool_end | permission_request | file_changed | git_changed | final_answer | error",
  "status": "queued | running | waiting_user | completed | failed",
  "title": "Planning route",
  "summary": "Reading workspace instructions and building a task plan.",
  "content_delta": "...",
  "command": ["python", "-m", "asteria_runtime", "plan", "..."],
  "artifact_refs": [],
  "evidence_refs": [],
  "created_at": "..."
}
```

UI 根据 event type 渲染：

- assistant_delta / reasoning_delta：前台按“用户任务进展”流式显示，完成后可折叠。
- tool_start/tool_delta/tool_end：默认不作为主回复，只在 Inspector 显示；必要时在主线程显示一句用户可理解的进展，例如“正在核对工作区约束”。
- permission_request：明确按钮，允许一次 / 拒绝 / 修改。
- file_changed：文件卡片 + diff。
- final_answer：正式回复。
- error：失败原因 + 重试/导出证据/切换模型建议。

## 5. 对话不是假机器人

Studio 不应该有一个独立的“规则聊天机器人”冒充智能体。

正确做法：

- 普通问候可以本地轻量回复。
- 真实任务必须进入 runtime session。
- plan/run/review/resume 的输出必须回写到同一个对话线程。
- assistant 的正式回复来自 runtime 结果、review report 或真实模型，而不是前端随便拼接。
- 如果暂时没有真实模型结果，必须明确显示“正在规划/等待模型/等待权限”，而不是假装已回答。

## 6. 权限设计

权限不是 checkbox。

权限卡必须说明：

- 要运行什么命令。
- 会读哪些范围。
- 会写哪些范围。
- 是否联网。
- 预计 token/cost。
- 风险等级。
- 用户选择：
  - 允许一次。
  - 本会话允许同类操作。
  - 拒绝。
  - 修改目标。

所有权限决策写入 `.asteria/studio/events.jsonl`，并关联 runtime evidence。

## 7. 文件与 Git

文件体验必须围绕“本次任务产物”，而不是全局文件列表。

需要显示：

- 本次任务新增/修改/删除文件。
- diff。
- 生成报告预览。
- 可打开 artifact。
- git status。
- 可创建 commit / 查看变更 / 回滚候选，但必须走权限。

候选 worktree / promotion queue 进入产品后，Studio 要显示：

- candidate workspace。
- promotion queue。
- approve/reject/discard/retry。
- 主工作区是否被污染。

## 8. Token / 模型 / 路由

主工作区只显示轻量状态：

- 当前模型 route。
- token/cost 预算进度。
- 是否接近 budget。
- 是否 fallback/downgrade/retry。

详细 capability profile 和 gate evidence 放 Observability。

## 9. 设置页

设置页可以参考 Codex 的结构，但要适合 Asteria：

- 常规
  - 工作模式：编程 / 日常任务
  - 默认权限
  - 默认打开目标
  - Shell
  - 语言
  - 跟进行为
- 外观
  - 主题
  - 字体
  - 紧凑度
- 配置
  - runtime root
  - workspace root
  - `.asteria` 路径
- 模型
  - strong / medium / cheap route present
  - streaming enabled
  - timeout budget
- Git
  - worktree strategy
  - commit policy
- 环境
  - Python
  - Node
  - Shell
- MCP / 插件
- 使用情况和计费
- 已归档对话

设置页是后台配置，不应该污染主工作区。

## 10. 最小可用重做版本

下一次实现不再继续修补当前页面，而是按以下最小版本重做：

### Studio 最小可用线索 A：Session Thread

- 左侧 session 列表。
- 中间主线程。
- 底部 composer。
- 用户输入后立即创建：
  - user message
  - assistant acknowledgement
  - planning activity

### Studio 最小可用线索 B：Streaming Event Bridge

- 后端 job 输出统一转换成 Studio events。
- 前端每 500ms 或 SSE 订阅事件。
- 事件先映射成用户侧 task progress，再渲染到主线程。
- 内部工具事件进入 Inspector。
- 完成后 reasoning 自动折叠。

### Studio 最小可用线索 C：真实 plan 工作流

验收任务：

```text
帮我计划一下如何去青岛玩
```

必须表现为：

- 立即显示用户消息。
- 立即显示“正在规划”。
- 流式显示 planner progress。
- plan 完成后给正式旅行计划。
- 如果模型超时，显示超时、route、重试/切换模型建议。

### Studio 最小可用线索 D：权限卡

对 `run-limited`、`execute-one`、`resume-limited` 显示权限卡，不用 checkbox。

### Studio 最小可用线索 E：文件 / 证据 Inspector

选中某个 activity，右侧显示：

- command
- stdout/stderr
- evidence refs
- generated artifacts
- file diff

## 11. 当前原型处理

当前 `studio/src/main.tsx` 和 `studio/server.mjs` 已经混乱，不应该继续演进。

建议：

- 保留可复用的 API 经验。
- 新建清晰模块：
  - `server/runtime.ts`
  - `server/events.ts`
  - `server/sessions.ts`
  - `server/files.ts`
  - `src/App.tsx`
  - `src/components/Thread.tsx`
  - `src/components/Composer.tsx`
  - `src/components/ActivityCard.tsx`
  - `src/components/Inspector.tsx`
  - `src/components/Settings.tsx`
- 用 Playwright 截图验收首页。


## 12. Goal / Plan / Ask 路由

Studio 的默认入口应像用户侧智能体工作区，而不是 runtime 命令启动器。

用户直接可见的模式：

- Goal：执行目标，允许在权限策略内修改文件、运行验证和生成交付物。
- Plan：只读分析，不修改用户业务文件。
- Ask：轻量问答，默认不进入长任务执行。

高级能力不作为默认模式暴露：

- Debug：进入 Ops / Debug Console。
- Models：模型策略或 route 配置。
- Skills：可挂载工作流能力。
- MCP Servers：可挂载外部上下文/工具。
- Multitask：Goal 内部执行策略。

建议路由：

```text
explicit Goal / Plan / Ask selected
  -> respect selected mode

ordinary Q&A
  -> Ask

progress / status / next-step question
  -> Ask + mount active long-task status

read-only planning / comparison / evaluation
  -> Plan

workspace-changing task
  -> Goal, with permission card if needed

large ambiguous request
  -> Plan first, then ask user which priority to execute

backend / route / evidence / trace question
  -> Ops / Debug Console
```

每次自动路由都应形成 `IntentRoute` 记录，至少包含：

- `intent`
- `target_mode`
- `confidence`
- `permission_pressure`
- `risk_reason`
- `recommended_next_action`

这些记录进入 session evidence，供后续复盘为什么系统选择了 Goal、Plan 或 Ask。
