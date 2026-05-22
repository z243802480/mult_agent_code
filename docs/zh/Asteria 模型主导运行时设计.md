# Asteria 模型主导运行时设计

## 1. 结论

Asteria 的下一阶段应从“状态机严格驱动模型”调整为“模型主导工作循环，Runtime 提供能力环境和护栏”。

状态机仍然重要，但它的职责不是替模型做完整规划，也不是把每一步模型输出卡成固定 JSON。它应该负责：

- 把用户目标、项目规则、可用能力、权限、预算、沙箱和历史证据组织成模型可理解的上下文。
- 暴露原子能力：读文件、搜索、编辑、shell、验证、MCP、skills、子 worker、候选工作区、promotion。
- 执行权限检查、路径保护、成本限制、上下文压缩和可恢复落盘。
- 把模型的尝试、工具调用、失败、修复、验证和结论记录成可审计事件。

模型负责：

- 根据目标和环境判断下一步。
- 选择工具、MCP、skill 或子 agent。
- 读取工具结果并调整策略。
- 多轮尝试直到完成、阻塞或需要用户决策。
- 产出用户能读懂的最终结论。

一句话：Asteria 应该做 agent harness，不应该做模型的上级流程审批员。

## 2. 外部产品共识

本轮参考了 Claude Code、opencode 和 Codex 的公开文档。共同趋势很明确：

- Agent 的核心是循环，不是表单：理解上下文、行动、观察结果、验证，再重复。
- 工具是模型可选择的能力，不是由外部状态机逐项硬编码。
- 权限、沙箱、预算、hooks 和审计在模型之外执行，但会把结果反馈给模型。
- project instructions、skills、MCP、subagents、worktree 是环境能力的一部分，需要被整理进提示词和工具目录。
- UI 展示的是一次工作过程：模型思考、工具准备、工具调用、结果、修复、验证、最终报告，而不是裸状态 JSON。

参考来源：

- [Claude Code Overview](https://code.claude.com/docs/en/overview)：Claude Code 是能读代码、改文件、运行命令并连接开发工具的 agentic coding tool；同一引擎覆盖 terminal、IDE、desktop 和 browser。
- [Claude Code Agent Loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)：agent loop 是模型评估 prompt、调用工具、接收结果并重复直到任务完成。
- [opencode Modes](https://opencode.ai/docs/modes/)：mode 用 prompt、tools、model 和 permission 组合表达不同工作方式；内置 build 和 plan。
- [opencode Tools](https://opencode.ai/docs/tools/)：工具让 LLM 在代码库中执行动作，并可通过 permission 控制 allow、deny 或 ask。
- [Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md)：Codex 会在工作前读取全局和项目级 AGENTS.md，并按路径层级合并成指令链。
- [Codex Skills](https://developers.openai.com/codex/skills)：skills 用渐进式加载把可复用工作流暴露给模型，让模型按任务选择是否启用。
- [Codex MCP](https://developers.openai.com/codex/mcp)：MCP 把模型连接到外部工具和上下文，并支持 CLI/IDE 共享配置。

## 3. 设计原则

### 3.1 状态机变成护栏

现有 `goal_spec`、`task_plan`、`task_plan_eval`、`final_answer` 仍可保留，但语义要下调：

- 它们是可审计的工作产物，不是模型必须一次完美命中的硬闸。
- schema 校验用于持久化可靠性，不能因为模型自然语言缺少某个字段就阻断合理尝试。
- 结构化产物缺失时，runtime 应进入修复或降级路径：让模型补齐、由 runtime 从 transcript 提取、或生成最小可恢复摘要。
- 真正的完成标准是用户目标是否被推进、产物是否存在、验证是否通过、最终结论是否清楚。

### 3.2 Prompt 是主要编排面

下一步要把编排重点从“Python 里写死阶段”移到“运行时提示词管理”：

```text
System / developer policy
  -> project guidance: AGENTS.md, docs/zh 当前状态, local conventions
  -> capability manifest: tools, MCP, skills, subagents, modes
  -> safety envelope: permissions, protected paths, budget, network, sandbox
  -> working memory: run transcript, evidence tail, recent failures
  -> user goal
  -> model chooses next action
```

Runtime 每轮都应向模型提供清晰的能力目录和边界，而不是把模型锁在单一 `goal_spec -> task_plan -> execute -> final` 的死链里。

### 3.3 工具调用结果进入模型循环

每次工具调用必须形成两类输出：

- 给模型的观察：简洁、任务相关、可继续推理。
- 给用户和审计的证据：完整命令、stdout/stderr、文件 diff、artifact refs、telemetry、错误分类。

Studio 主线看前者，Inspector 看后者。

### 3.4 失败是循环节点

失败不应直接表现为“状态机坏了”。失败应进入模型可处理的观察：

```text
attempt failed
  -> runtime classifies error and preserves evidence
  -> model receives concise failure observation
  -> model decides repair, replan, ask user, downgrade route, or stop
```

只有以下情况才硬停：

- 权限或 protected path 阻断。
- 预算接近 hard stop。
- 用户必须决策。
- 多次 repair/replan 后仍无法取得新证据。
- release/promotion gate 明确阻断。

## 4. Asteria Agent Harness

建议新增内部抽象 `AgentHarness`，先不急着重构所有命令，但新执行链路应逐步向它收敛。

职责：

- 加载项目和会话上下文。
- 构建 prompt envelope。
- 暴露工具目录和能力 manifest。
- 调用模型并接收 tool request / text delta / final。
- 把工具请求交给 permission/sandbox gateway。
- 把工具结果作为 observation 回灌模型。
- 记录 user_progress、raw events、model calls、tool calls、artifacts。
- 在停止时生成 final answer 和 folded run report。

非职责：

- 不替模型决定完整任务路线。
- 不把所有模型输出强制转成固定 JSON 后才允许继续。
- 不绕过权限、成本、schema、候选工作区和 gate。

## 5. 模式设计

Asteria 应采用 mode，而不是用命令数量表达全部产品形态：

| Mode | 目的 | 默认能力 |
| --- | --- | --- |
| `plan` | 分析、阅读、制定方案 | read/search/status/model context，可写计划文件 |
| `build` | 实现用户目标 | read/search/edit/write/shell/test/candidate workspace |
| `review` | 审查结果和风险 | read/search/diff/test/report |
| `repair` | 根据失败证据修复 | read/search/edit/shell/test，带失败 observation |
| `release` | 灰度、gate、promotion | gate/gray/release/promotion，只走受控命令 |

用户不需要理解内部命令。CLI 和 Studio 都应把用户意图映射到 mode，再由模型在该 mode 的能力边界内工作。

## 6. 能力 Manifest

每次模型循环应注入一个简洁 manifest：

```json
{
  "modes": ["plan", "build", "review", "repair", "release"],
  "tools": [
    {"name": "read_file", "kind": "read", "permission": "allow"},
    {"name": "search", "kind": "read", "permission": "allow"},
    {"name": "edit_file", "kind": "write", "permission": "ask"},
    {"name": "shell", "kind": "execute", "permission": "ask", "policy": "no_destructive"},
    {"name": "run_tests", "kind": "verify", "permission": "allow_or_ask"},
    {"name": "mcp", "kind": "external", "permission": "ask"},
    {"name": "skill", "kind": "workflow", "permission": "allow"},
    {"name": "subagent", "kind": "delegate", "permission": "ask"}
  ],
  "boundaries": {
    "protected_paths": [".env", ".env.*", "secrets/", ".git/", "*.pem", "*.key"],
    "network": "policy_controlled",
    "writes": "candidate_workspace_preferred",
    "budget": "runtime_enforced"
  }
}
```

manifest 给模型看的是能力和边界，不是内部 Python 类名。

## 7. Studio 展示方向

Studio 要展示 Agent Harness 的真实工作过程：

```text
User Goal
  -> Assistant acknowledgement
  -> Context and capability loading
  -> Model reasoning / plan summary
  -> Tool / MCP / skill organization
  -> Tool invocation
  -> Observation
  -> Repair / replan loop
  -> Verification
  -> Final answer
  -> Folded run report
```

主线默认展示用户能理解的节奏：

- 正在理解目标。
- 正在查看项目规则和能力。
- 正在选择工具。
- 正在执行。
- 发现问题并修复。
- 正在验证。
- 已完成，结果如下。

内部事件继续保留在 Inspector：命令、stdout/stderr、schema、JSONL、evidence refs、route telemetry、cost。

## 8. 实现计划

### P0-A：放松强结构闸门

- 盘点 `goal_spec`、`task_plan_eval`、`final_answer_quality` 中会直接阻断模型继续尝试的规则。
- 将“格式不完美”改成 repairable warning。
- schema 失败优先走补全、提取、最小摘要 fallback。
- final answer 验收改为用户结果标准：做了什么、验证如何、产物在哪里、风险和下一步是什么。

### P0-B：新增 AgentHarness 草图

- 新增 harness 层，先服务 `plan` 和小范围 `run`。
- 抽象 `PromptEnvelope`、`CapabilityManifest`、`ToolObservation`、`AgentTurn`。
- 复用现有 provider route、tool registry、permission policy、candidate workspace、user_progress。
- 不一次性重写 ExecuteCommand，先在新链路旁路验证。

### P0-C：能力目录进入提示词

- 从工具注册表、MCP、skills、policy config、AGENTS.md、docs/zh 当前状态生成简洁 capability/context summary。
- 模型每轮都知道有哪些能力、哪些需要审批、哪些被禁用。
- 只把必要摘要放入上下文，详情通过 tool/search/skill 渐进加载。

### P0-D：工具结果回灌模型

- 统一工具 observation 格式。
- 每个 tool result 都同时写 raw evidence 和 user-facing progress。
- 模型收到失败 observation 后可选择 repair/replan/ask/stop。

### P0-E：Studio 切到 Harness Narrative

- 主线优先消费 `user_progress.jsonl` 和 harness turn events。
- 展示“模型组织能力和工具”的阶段，而不是只展示后台日志。
- final report 由 harness 从 transcript、artifact、verification 和风险中汇总，不再把 stdout 或 JSON 路径当最终回复。

### P1：扩展到 subagent、MCP 和 worktree

- 子 agent 作为模型可请求的能力，runtime 控制并发、隔离和预算。
- MCP 作为工具 provider 进入 manifest，默认按权限策略 ask/deny/allow。
- tracked-clean git repo 优先 worktree/candidate branch。

## 9. 验收标准

下一轮实现后，用 5 个小 benchmark goal 验收：

- 模型能看到能力目录并主动选择工具。
- 至少一次失败能进入 repair/replan，而不是直接卡死。
- Studio 主线能读出完整过程。
- final answer 是自然语言结论，不是状态 JSON。
- raw evidence 仍完整可追溯。
- protected path、预算、权限、promotion gate 仍能阻断风险动作。
