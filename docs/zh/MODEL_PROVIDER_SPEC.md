# 多智能体自主开发系统 - 模型提供商规格

## 1. 文档目的

本文档定义模型适配层的接口、配置、路由、重试、超时、成本记录和 provider 隔离策略。

目标：

- 支持智谱、MiniMax、DeepSeek、OpenRouter、本地 OpenAI-compatible 服务。
- 不让某个 provider 的特殊字段污染核心运行时。
- 支持成本统计和模型路由。
- 支持后续 embeddings、rerank 和工具调用能力扩展。

## 2. 设计原则

- 核心运行时只依赖 `ModelClient` 抽象。
- Provider 细节封装在 adapter 内。
- 所有模型调用必须记录 `ModelCall`。
- 非关键任务优先使用 cheap/medium 模型。
- 强模型只用于规划、架构、复杂评审、重大决策等高价值节点。
- 失败必须有重试和降级策略。

## 3. ModelClient 接口

```python
class ModelClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        ...

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        ...

    def rerank(self, request: RerankRequest) -> RerankResponse:
        ...
```

MVP 必须实现：

- `chat`

V1 可实现：

- `embed`
- `rerank`

## 4. ChatRequest

```json
{
  "purpose": "planning",
  "model_tier": "strong",
  "messages": [
    {
      "role": "system",
      "content": "You are PlannerAgent..."
    },
    {
      "role": "user",
      "content": "做一个密码测试工具"
    }
  ],
  "response_format": "json",
  "temperature": 0.2,
  "max_output_tokens": 4000,
  "timeout_seconds": 60,
  "metadata": {
    "run_id": "run-20260427-0001",
    "agent_id": "agent-0001",
    "task_id": "task-0001"
  }
}
```

## 5. ChatResponse

```json
{
  "content": "{}",
  "finish_reason": "stop",
  "usage": {
    "input_tokens": 5000,
    "output_tokens": 1200,
    "total_tokens": 6200
  },
  "model_provider": "zhipu",
  "model_name": "glm-example",
  "raw_response_ref": null
}
```

## 6. Provider 配置

环境变量：

```text
AGENT_MODEL_PROVIDER
AGENT_MODEL_BASE_URL
AGENT_MODEL_API_KEY
AGENT_MODEL_NAME
AGENT_MODEL_TIMEOUT_SECONDS
AGENT_MODEL_MAX_RETRIES
```

### 6.1 分层模型路由

运行时支持按模型层级配置不同 provider。这样可以把规划、评审、调研等高价值调用交给强模型，
把代码执行、debug 或压缩交给本地/便宜模型，避免所有阶段都消耗同一档模型。

全局配置仍然有效：

```powershell
$env:AGENT_MODEL_PROVIDER = "minimax"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

MiniMax key 有区域差异。默认使用 `https://api.minimax.io/v1`，如果 key 以 `sk-cp-` 开头，
运行时默认切换到中国区端点 `https://api.minimaxi.com/v1`。

如果设置了分层 provider，则对应 `model_tier` 会走该 provider，未设置的 tier 回退到全局 provider。

```powershell
$env:AGENT_MODEL_STRONG_PROVIDER = "minimax"
$env:AGENT_MODEL_STRONG_API_KEY = "<your minimax key>"
$env:AGENT_MODEL_STRONG_NAME = "MiniMax-M2.7"

$env:AGENT_MODEL_MEDIUM_PROVIDER = "ollama"
$env:AGENT_MODEL_MEDIUM_NAME = "qwen2.5-coder:7b"

$env:AGENT_MODEL_CHEAP_PROVIDER = "fake"
```

支持的 tier：

```text
strong  -> goal_spec / planning / brainstorming / research / review
medium  -> coding / debugging / evaluation
cheap   -> summarization / classification / model-check smoke
```

每个 tier 支持独立配置：

```text
AGENT_MODEL_<TIER>_PROVIDER
AGENT_MODEL_<TIER>_API_KEY
AGENT_MODEL_<TIER>_BASE_URL
AGENT_MODEL_<TIER>_NAME
AGENT_MODEL_<TIER>_TIMEOUT_SECONDS
AGENT_MODEL_<TIER>_MAX_RETRIES
```

如果某个 tier 没有设置独立字段，会回退读取同名全局字段，例如
`AGENT_MODEL_API_KEY`、`AGENT_MODEL_BASE_URL`、`AGENT_MODEL_NAME`。

### 6.2 本地模型 Provider

本地模型优先走 OpenAI-compatible 接口，不在核心运行时绑定某个本地推理框架。

支持的 provider 别名：

```text
local
ollama
lmstudio
vllm
localai
```

默认端点：

```text
ollama   -> http://localhost:11434/v1
lmstudio -> http://localhost:1234/v1
vllm     -> http://localhost:8000/v1
localai  -> http://localhost:8080/v1
local    -> http://localhost:11434/v1
```

推荐配置示例：

```powershell
$env:AGENT_MODEL_PROVIDER = "ollama"
$env:AGENT_MODEL_NAME = "qwen2.5-coder:7b"
```

如果使用 LM Studio、vLLM 或自定义服务：

```powershell
$env:AGENT_MODEL_PROVIDER = "local"
$env:AGENT_MODEL_BASE_URL = "http://localhost:1234/v1"
$env:AGENT_MODEL_NAME = "<your local model>"
$env:AGENT_MODEL_API_KEY = "local"
```

本地模型默认超时为 180 秒，默认重试 1 次。适合 7B/14B 量化模型的离线验证、
低成本开发和隐私敏感任务。复杂规划、架构评审和高风险决策仍建议保留远程强模型兜底。

可选多模型配置：

```yaml
providers:
  zhipu:
    base_url: "https://..."
    api_key_env: "ZHIPU_API_KEY"
    models:
      cheap: "..."
      medium: "..."
      strong: "..."
  minimax:
    base_url: "https://..."
    api_key_env: "MINIMAX_API_KEY"
    models:
      cheap: "..."
      medium: "..."
      strong: "..."
```

具体 model name 不写死在核心代码中。

## 7. 模型路由

默认路由：

```yaml
goal_spec: strong
planning: strong
brainstorming: strong
architecture: strong
coding: medium
review: strong
debugging: medium
summarization: cheap
classification: cheap
evaluation: medium
```

路由优先级：

```text
CLI 参数
  > .agent/policies.json
  > 环境变量
  > 默认配置
```

## 8. 重试策略

默认：

```yaml
max_retries: 2
retry_backoff_seconds: [1, 3]
retry_on:
  - timeout
  - rate_limit
  - transient_network_error
```

不应重试：

- 鉴权失败。
- 请求格式错误。
- 预算不足。
- policy denied。

## 9. 超时策略

默认：

```yaml
cheap: 30
medium: 60
strong: 90
```

长任务不能通过无限拉长单次模型调用解决。需要拆任务、压缩上下文或降级目标。

## 10. 成本记录

每次调用必须写入 `model_calls.jsonl`：

```json
{
  "schema_version": "0.1.0",
  "model_call_id": "modelcall-0001",
  "run_id": "run-20260427-0001",
  "agent_id": "agent-0001",
  "purpose": "planning",
  "model_provider": "zhipu",
  "model_name": "glm-example",
  "model_tier": "strong",
  "input_tokens": 5000,
  "output_tokens": 1200,
  "status": "success",
  "created_at": "2026-04-27T14:30:00+08:00",
  "summary": "生成任务计划"
}
```

如果 provider 不返回 token usage，adapter 必须记录：

```json
{
  "input_tokens": null,
  "output_tokens": null,
  "usage_estimated": false
}
```

后续可添加本地估算器，但不能假装是精确值。

## 11. JSON 输出要求

当命令需要结构化输出时：

- 优先使用 provider 支持的 JSON mode。
- 不支持时，使用强提示约束。
- 返回后必须用 schema 校验。
- 运行时可在模型边界做有限 JSON 提取和字段归一化。
- 无法安全归一化或 schema 校验仍失败时，必须生成阻塞报告。

当前实现要求：

- 可移除 `<think>...</think>` 推理块，避免推理文本污染 JSON 解析。
- 只有当整段响应是 markdown code fence 时才剥离 fence，不能破坏 JSON 字符串中的代码片段。
- 可从响应中提取最后一个可解析 JSON 对象。
- 可修复轻微近似 JSON，例如简单未加引号的对象 key。
- `GoalSpec`、`ExecutionAction`、`EvalReport` 允许有边界的字段归一化，例如把对象数组转为字符串数组、补齐默认优先级、兼容 `tool/name/arguments` 别名。
- 工具调用参数会按工具函数签名过滤未知字段，并在工具事件中记录 warning。

边界：

- JSON 提取和归一化只能发生在模型输出边界。
- 持久化对象仍必须通过 schema 校验。
- 不能为了通过校验而静默改变用户目标、权限策略或成本预算。
- 多次失败后应进入 debug、repair 或 DecisionPoint，而不是无限重试。

## 12. Tool Calling 策略

MVP 不依赖 provider 原生 tool calling。

原因：

- 各 provider tool calling 差异较大。
- 为保持自主可控，工具选择和执行应由 runtime 管理。

MVP 策略：

```text
模型输出结构化 action proposal
  -> runtime 校验
  -> permission check
  -> tool execution
  -> tool result 注入下一轮
```

V1 可根据 provider 能力添加原生 tool calling adapter，但核心工具权限仍由 runtime 控制。

## 13. 降级策略

当成本或失败率过高：

1. 压缩上下文。
2. 降低候选数量。
3. 将 summarization/classification 切到 cheap。
4. 将 coding/debugging 从 strong 降到 medium。
5. 停止 research 分支。
6. 请求用户批准继续。

## 14. Provider 隔离

禁止：

- 在核心数据模型中加入 provider 专有字段。
- 在 agent prompt 中依赖特定 provider 行为。
- 在业务逻辑中判断具体模型名称。

允许：

- adapter 内处理 provider 参数差异。
- adapter 内处理认证、超时、返回格式归一化。
- adapter 内记录 raw response 引用。

## 15. MVP 验收

MVP 模型适配层完成条件：

- 能通过 OpenAI-compatible 接口调用 chat。
- 能记录 ModelCall。
- 能处理超时和重试。
- 能根据 purpose 路由模型 tier。
- 能从真实模型输出中提取、归一化结构化 JSON，并在 schema 校验失败时阻塞或进入修复流程。
- 不依赖 provider 原生 tool calling。
