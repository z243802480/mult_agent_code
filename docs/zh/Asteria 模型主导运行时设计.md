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
| `release` | 发布准备验证、gate、promotion | gate/readiness/release/promotion，只走受控命令 |

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



## 6.1 从 claude_code 源码得到的可借鉴点

本轮本地阅读了 `claude_code/CLAUDE.md`、`claude_code/src/constants/prompts.ts`、`claude_code/src/constants/systemPromptSections.ts`、`claude_code/packages/builtin-tools/src/tools/AgentTool/prompt.ts`、权限/工具/compact 相关文件。结论不是照搬 Claude Code，而是吸收其成熟产品化经验，并保留 Asteria 的 Runtime OS 优势。

可借鉴点：

- **系统提示词分段组装**：Claude Code 把身份、任务原则、工具使用、风险动作、会话特定能力、输出风格、memory、环境信息拆成 section，并区分可缓存静态段与会话动态段。Asteria 的 `PromptEnvelope` 也应是可命名、可审计、可缓存的 section 列表，而不是一整块字符串。
- **能力目录显式化**：核心工具直接可用，延迟工具、MCP、skills、agents 通过发现或附件逐步暴露。Asteria 应保留 `CapabilityManifest`，但补充 `direct_tools`、`deferred_tools`、`skills`、`mcp_tools`、`subagents`、`modes`、`permission_state` 的分层，避免模型误以为所有能力都已常驻上下文。
- **工具优先级和误用防护**：Claude Code 明确要求“读文件用 Read，不要用 shell cat；搜索未知符号先 grep/glob；简单定位不要派子 agent”。Asteria 的提示词也需要写清工具选择规则，减少无意义 shell、无意义 delegation 和上下文浪费。
- **风险动作单独成章**：删除、force push、改 CI/CD、发外部消息、上传内容等高爆炸半径动作都需要确认。Asteria 已有 DecisionPoint、protected paths、ToolPermissionPolicy，应把这些不仅放在代码 policy 中，也放进模型可见的 safety envelope。
- **失败后诊断再换路**：失败不是直接 abandon，也不是盲目重试；先读错误、检查假设、做聚焦修复。Asteria 已有 repair/replan 次数预算，应在系统提示词中要求模型把失败 observation 当成下一轮输入。
- **子 agent prompt 需要像交代同事**：Claude Code 要求给子 agent 足够背景、已知事实、排除项、期望输出和作用域；不能把“理解”外包给子 agent。Asteria 的 WorkerInvocation 也应增加 `brief_quality` 检查，保证 delegation 是可执行任务，而不是空泛转包。
- **后台/并行 agent 要有隔离和汇报契约**：社区实现支持前台/后台、fork、worktree isolation、完成通知。Asteria 应继续坚持 candidate workspace、merge gate、promotion queue，不让并行 worker 污染主工作区。
- **独立验证代理理念值得吸收**：非平凡实现完成前，应有独立 review/verification 路线，且主 agent 不能自己给自己判 PASS。Asteria 已有 ReviewAgent、DebugAgent、MergeGate 和 Runtime OS gate，应把“实现者不能自封通过”写入 harness contract。
- **上下文压缩不是简单摘要**：compact 会保留边界消息、最近片段、文件状态、skills、计划和 hooks 结果，并记录压缩前后 token。Asteria 的 ContextSnapshot/ContextPackage 应从“保存摘要”升级为“保存继续执行所需的不变量、文件触点、失败证据和未完成任务”。
- **用户沟通是产品能力**：Claude Code 要求首次工具调用前说明将做什么，中途关键节点短更新，最终如实报告验证结果。Asteria 的 user_progress 事件协议已经走在正确方向，应继续保留并强化。

不能照搬的点：

- 不把产品做成单体交互 CLI 的超大文件堆叠。Asteria 的目标是 Runtime OS：CLI、Studio、JSON/JSONL evidence、candidate workspace、gate、resume 都要共享同一套运行证据。
- 不依赖单一模型或单一 provider 的专有行为。提示词、tool schema、provider adapter 必须可替换。
- 不让 feature flag、实验工具、远端控制、插件市场先于核心 runtime loop。MVP 仍以 filesystem + JSON/JSONL、真实行为和测试为优先。
- 不把 dashboard 放到核心之前。Studio 只消费 harness/user_progress/evidence，不成为新的执行内核。

## 6.2 Asteria 系统级提示词骨架

Asteria 的系统级提示词应由 Runtime 生成 `PromptEnvelope`，每个 section 有稳定名称、来源、优先级、是否可缓存、token 预算和证据引用。建议骨架如下：

```text
# Identity
You are Asteria, a local-first autonomous development runtime agent. You help the user turn a compact goal into verified local artifacts.

# Operating contract
- Work inside the current project and respect project guidance.
- Preserve user-authored content and avoid unrelated refactors.
- Prefer small, verifiable changes over speculative rewrites.
- Produce durable artifacts when the task requires them; answer inline when that is enough.
- Before reporting completion, verify with the strongest available local check. If you cannot verify, say exactly why.

# Project guidance
- Root AGENTS.md and nearest scoped guidance.
- docs/zh/当前状态与路线.md summary when working on Asteria itself.
- Current goal, definition of done, accepted decisions, open risks.

# Capability manifest
- Direct tools: read/search/edit/write/shell/test/status/report.
- Deferred tools: MCP, skills, subagents, automations, external adapters.
- Modes: plan, build, review, repair, release.
- For each capability: permission state, sandbox, read/write scope, cost tier, expected observation format.

# Tool-use policy
- Search or read before proposing code changes to files you have not inspected.
- Prefer dedicated file/search tools over shell equivalents.
- Use shell mainly for tests, builds, git inspection, and commands that cannot be represented by safer tools.
- Do not use subagents for a specific file read or a narrow symbol lookup; use subagents for broad exploration, independent implementation, adversarial review, or context isolation.
- Every tool result becomes a concise model observation plus durable raw evidence.

# Safety envelope
- Protected paths, network policy, destructive command policy, secret policy, budget, candidate workspace policy, merge gate policy.
- If a requested action has high blast radius, ask for a DecisionPoint rather than proceeding silently.
- Tool denial is an observation: do not retry the identical request; adapt or ask.

# Failure and repair
- Diagnose the error before changing route.
- Try focused repair within the repair budget.
- If scope, permissions, budget, or product direction is the blocker, create a structured runtime request or DecisionPoint.
- Never manufacture green status by suppressing tests, weakening validation, or hiding failures.

# Delegation contract
- Brief subagents like new teammates: goal, why it matters, known context, files/commands, constraints, expected output, and whether they may write.
- Parallelize only independent work.
- Isolate writes in candidate workspaces when possible.
- Implementation and verification should be separate for non-trivial changes.

# Context and compaction
- Keep active goal, decisions, modified files, validation results, failures, and next actions available across compaction/resume.
- Treat compacted summaries as state snapshots, not as proof that work succeeded.

# User communication
- Before the first action, briefly say what will be examined or changed.
- Give short progress updates at meaningful transitions.
- Final response states what changed, where, verification result, remaining risk, and next action if any.
```

该骨架不是写死在模型外的流程图，而是把 Runtime OS 的边界、能力和证据格式交给模型，让模型在边界内选择下一步。

## 6.3 PromptEnvelope section 数据结构建议

建议把系统提示词落成可持久化对象，便于调试、缓存和回放：

```json
{
  "id": "prompt-envelope-...",
  "run_id": "run-...",
  "model_route": "strong|medium|cheap",
  "sections": [
    {
      "name": "identity",
      "source": "runtime_builtin",
      "priority": 100,
      "cache_scope": "global",
      "content_ref": "sha256:...",
      "token_estimate": 80
    },
    {
      "name": "project_guidance",
      "source": "AGENTS.md + docs/zh/当前状态与路线.md",
      "priority": 90,
      "cache_scope": "project",
      "evidence_refs": ["file:AGENTS.md", "file:docs/zh/当前状态与路线.md"]
    },
    {
      "name": "capability_manifest",
      "source": "ToolRegistry + RuntimeProfile + policy",
      "priority": 80,
      "cache_scope": "turn",
      "evidence_refs": [".asteria/.../capabilities.json"]
    }
  ]
}
```

实现要求：

- 静态 section 不随每轮工具结果改变，减少 prompt cache 破坏。
- 动态 section 必须说明为什么动态，例如权限变化、MCP 连接变化、budget 接近阈值、context compaction 后恢复。
- section 内容进入 `.asteria/` 时可保存 hash + 摘要，必要时保存完整文本；不能把 secrets 或受保护文件内容写入 prompt evidence。
- `CapabilityManifest` 同时面向模型和审计，不暴露内部 Python 类名，而暴露用户可理解能力、权限和边界。

## 6.4 保留并放大的 Asteria 优势

学习 Claude Code 不等于变成 Claude Code。Asteria 必须继续保留这些更适合长期自治开发 runtime 的设计：

- **Runtime OS evidence-first**：TaskGraph、WorkerInvocation、WorkerResult、TaskExecutionEvidence、MergeGate、RuntimeProfile 都是可落盘、可回放、可验收对象。
- **候选工作区和 promotion gate**：写入隔离、merge gate 阻断、promotion queue 是超越普通 CLI agent 的关键安全能力。
- **多模型、多 profile 调度**：不要把成功绑定到单一 provider；route guidance、capability feedback、预算信号要继续沉淀。
- **Schema 校验但不让 schema 绑架模型循环**：持久化对象必须校验，但模型自然语言尝试可以先进入 repair/extract/fallback，而不是直接硬停。
- **用户进展事件协议**：主线给用户看，Inspector 给审计看；这比裸 stdout 或大段 JSON 更适合长任务。
- **成本和 hard-stop DecisionPoint**：预算接近硬停必须可见、可决策、可恢复。
- **真实任务基准和 release gate**：功能必须有真实行为和测试，不能靠 prompt 看起来聪明。

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

本节是模型主导设计的长期落地线索，不单独决定当前 P0/P1 顺序。当前执行优先级以 [当前状态与路线.md](./当前状态与路线.md) 和 [代码现状差距与研发计划.md](./代码现状差距与研发计划.md) 为准。下面条目保留为设计来源和验收线索；Studio 是独立产品交互面，后端 runtime 不由 Studio 反向牵引，但 Studio 的用户心流、实时过程展示、文件/配置/权限/模型管理设计长期有效。

### 落地线索 A：放松强结构闸门

- 盘点 `goal_spec`、`task_plan_eval`、`final_answer_quality` 中会直接阻断模型继续尝试的规则。
- 将“格式不完美”改成 repairable warning。
- schema 失败优先走补全、提取、最小摘要 fallback。
- final answer 验收改为用户结果标准：做了什么、验证如何、产物在哪里、风险和下一步是什么。

### 落地线索 B：新增 AgentHarness 草图

- 新增 harness 层，先服务 `plan` 和小范围 `run`。
- 抽象 `PromptEnvelope`、`CapabilityManifest`、`ToolObservation`、`AgentTurn`。
- 复用现有 provider route、tool registry、permission policy、candidate workspace、user_progress。
- 不一次性重写 ExecuteCommand，先在新链路旁路验证。

### 落地线索 C：能力目录进入提示词

- 从工具注册表、MCP、skills、policy config、AGENTS.md、docs/zh 当前状态生成简洁 capability/context summary。
- 模型每轮都知道有哪些能力、哪些需要审批、哪些被禁用。
- 只把必要摘要放入上下文，详情通过 tool/search/skill 渐进加载。

### 落地线索 D：工具结果回灌模型

- 统一工具 observation 格式。
- 每个 tool result 都同时写 raw evidence 和 user-facing progress。
- 模型收到失败 observation 后可选择 repair/replan/ask/stop。

### 后续展示方向：Studio 切到 Harness Narrative

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
