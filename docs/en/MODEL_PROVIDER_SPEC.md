# Multi-Agent Autonomous Development System - Model Provider Specification

## 1. Purpose

This document defines the model adapter interface, configuration, routing, retry behavior, timeout behavior, cost recording, and provider isolation strategy.

Goals:

- Support Zhipu, MiniMax, DeepSeek, OpenRouter, and local OpenAI-compatible services.
- Prevent provider-specific fields from leaking into the core runtime.
- Support cost tracking and model routing.
- Leave room for future embeddings, reranking, and tool-calling extensions.

## 2. Design Principles

- The core runtime depends only on the `ModelClient` abstraction.
- Provider details are isolated inside adapters.
- Every model call must produce a `ModelCall` record.
- Non-critical work should prefer cheap or medium models.
- Strong models are reserved for planning, architecture, complex review, major decisions, and other high-value nodes.
- Failures must have retry and downgrade strategies.

## 3. ModelClient Interface

```python
class ModelClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        ...

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        ...

    def rerank(self, request: RerankRequest) -> RerankResponse:
        ...
```

MVP requirement:

- `chat`

V1 candidates:

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
      "content": "Build a password testing tool"
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

## 6. Provider Configuration

Environment variables:

```text
AGENT_MODEL_PROVIDER
AGENT_MODEL_BASE_URL
AGENT_MODEL_API_KEY
AGENT_MODEL_NAME
AGENT_MODEL_TIMEOUT_SECONDS
AGENT_MODEL_MAX_RETRIES
```

### 6.1 Tiered Model Routing

The runtime supports per-tier provider configuration. This allows high-value calls such as planning, review, and research to use strong models, while coding, debugging, or compression can use local or cheaper models.

Global configuration remains valid:

```powershell
$env:AGENT_MODEL_PROVIDER = "minimax"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

MiniMax keys may be region-specific. The default endpoint is `https://api.minimax.io/v1`; when the key starts with `sk-cp-`, the runtime switches to the China endpoint `https://api.minimaxi.com/v1`.

If tiered providers are configured, the matching `model_tier` uses that provider. Unconfigured tiers fall back to the global provider.

```powershell
$env:AGENT_MODEL_STRONG_PROVIDER = "minimax"
$env:AGENT_MODEL_STRONG_API_KEY = "<your minimax key>"
$env:AGENT_MODEL_STRONG_NAME = "MiniMax-M2.7"

$env:AGENT_MODEL_MEDIUM_PROVIDER = "ollama"
$env:AGENT_MODEL_MEDIUM_NAME = "qwen2.5-coder:7b"

$env:AGENT_MODEL_CHEAP_PROVIDER = "fake"
```

Supported tiers:

```text
strong  -> goal_spec / planning / brainstorming / research / review
medium  -> coding / debugging / evaluation
cheap   -> summarization / classification / model-check smoke
```

Each tier supports independent configuration:

```text
AGENT_MODEL_<TIER>_PROVIDER
AGENT_MODEL_<TIER>_API_KEY
AGENT_MODEL_<TIER>_BASE_URL
AGENT_MODEL_<TIER>_NAME
AGENT_MODEL_<TIER>_TIMEOUT_SECONDS
AGENT_MODEL_<TIER>_MAX_RETRIES
```

Missing tier-specific fields fall back to global fields such as `AGENT_MODEL_API_KEY`, `AGENT_MODEL_BASE_URL`, and `AGENT_MODEL_NAME`.

### 6.2 Local Model Provider

Local models should use OpenAI-compatible APIs. The core runtime must not bind itself to one local inference framework.

Supported provider aliases:

```text
local
ollama
lmstudio
vllm
localai
```

Default endpoints:

```text
ollama   -> http://localhost:11434/v1
lmstudio -> http://localhost:1234/v1
vllm     -> http://localhost:8000/v1
localai  -> http://localhost:8080/v1
local    -> http://localhost:11434/v1
```

Recommended configuration:

```powershell
$env:AGENT_MODEL_PROVIDER = "ollama"
$env:AGENT_MODEL_NAME = "qwen2.5-coder:7b"
```

LM Studio, vLLM, or custom endpoint:

```powershell
$env:AGENT_MODEL_PROVIDER = "local"
$env:AGENT_MODEL_BASE_URL = "http://localhost:1234/v1"
$env:AGENT_MODEL_NAME = "<your local model>"
$env:AGENT_MODEL_API_KEY = "local"
```

Local models default to a 180-second timeout and one retry. They are suitable for offline checks, low-cost development, and privacy-sensitive tasks. Complex planning, architecture review, and high-risk decisions should still keep a remote strong-model fallback.

Optional multi-provider configuration:

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

Concrete model names must not be hard-coded into core runtime logic.

## 7. Model Routing

Default routing:

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

Routing precedence:

```text
CLI arguments
  > .agent/policies.json
  > environment variables
  > defaults
```

## 8. Retry Strategy

Default:

```yaml
max_retries: 2
retry_backoff_seconds: [1, 3]
retry_on:
  - timeout
  - rate_limit
  - transient_network_error
```

Do not retry:

- Authentication failures.
- Invalid request formats.
- Budget exhaustion.
- Policy denial.

## 9. Timeout Strategy

Defaults:

```yaml
cheap: 30
medium: 60
strong: 90
```

Long tasks must not be solved by making single model calls unbounded. Use task decomposition, context compaction, or goal reduction instead.

## 10. Cost Recording

Every call must write to `model_calls.jsonl`:

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
  "summary": "Generated task plan"
}
```

If the provider does not return token usage, the adapter must record:

```json
{
  "input_tokens": null,
  "output_tokens": null,
  "usage_estimated": false
}
```

A local estimator may be added later, but estimated values must not be presented as exact provider usage.

## 11. JSON Output Requirements

For commands that require structured output:

- Prefer provider-supported JSON mode.
- Use strict prompting when JSON mode is unavailable.
- Validate responses against schemas after parsing.
- Apply limited JSON extraction and field normalization at the model boundary.
- Block or enter repair flow when safe normalization is impossible or schema validation fails.

Current implementation expectations:

- Remove `<think>...</think>` blocks so reasoning text does not pollute JSON parsing.
- Strip markdown fences only when the entire response is fenced.
- Extract the last parseable JSON object from a response.
- Repair slight near-JSON issues such as simple unquoted object keys.
- Allow bounded normalization for `GoalSpec`, `ExecutionAction`, and `EvalReport`.
- Filter tool-call arguments by tool signature and record warnings for unknown fields.

Boundaries:

- Extraction and normalization happen only at the model-output boundary.
- Persisted objects still must pass schema validation.
- The runtime must not silently change user goals, permission policy, or cost budgets to pass validation.
- Repeated failure should enter debug, repair, or DecisionPoint flow instead of infinite retry.

## 12. Tool Calling Strategy

The MVP does not depend on provider-native tool calling.

Reasons:

- Tool-calling behavior differs across providers.
- The runtime should remain self-controlled.
- Tool permissions must stay under runtime policy control.

MVP flow:

```text
model emits structured action proposal
  -> runtime validation
  -> permission check
  -> tool execution
  -> tool result injected into the next model turn
```

V1 may add native tool-calling adapters, but core tool permissions remain controlled by the runtime.

## 13. Downgrade Strategy

When cost or failure rate becomes too high:

1. Compact context.
2. Reduce candidate count.
3. Move summarization/classification to cheap models.
4. Move coding/debugging from strong to medium models.
5. Stop research branches.
6. Ask the user before continuing.

## 14. Provider Isolation

Forbidden:

- Adding provider-specific fields to core data models.
- Depending on provider-specific behavior in agent prompts.
- Branching business logic by concrete model name.

Allowed:

- Handling provider parameter differences inside adapters.
- Normalizing authentication, timeout, and response formats inside adapters.
- Recording raw-response references inside adapters.

## 15. MVP Acceptance

The MVP model adapter is complete when:

- Chat works through an OpenAI-compatible interface.
- `ModelCall` records are written.
- Timeout and retry behavior works.
- `agent model-check` failures write `.agent/model/latest_failure.json`, classify configuration, authentication, rate limit, timeout, network, server error, budget, and provider-response failures, and record lessons under `.agent/memory/failures.jsonl`.
- Model tier is routed by purpose.
- Structured JSON can be extracted and normalized from real model output, with schema validation blocking or repair flow on failure.
- The MVP does not depend on provider-native tool calling.
