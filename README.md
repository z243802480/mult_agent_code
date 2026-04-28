# Agent Runtime

Local-first multi-agent autonomous development runtime. The current MVP path is a CLI that
turns a goal into a GoalSpec, task plan, controlled tool execution, repair, review, context
snapshot, and final report.

## Quick Start

```powershell
python -m pip install -e ".[dev]"
agent --help
agent /init --root .
agent /sessions --root .
```

`agent /run "goal"` writes run artifacts under `.agent/runs/<run_id>/`, including
`goal_spec.json`, `task_plan.json`, logs, `review_report.md`, and `final_report.md`.

## Model Configuration

MiniMax is the default provider:

```powershell
$env:AGENT_MODEL_PROVIDER = "minimax"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

OpenAI-compatible providers are also supported:

```powershell
$env:AGENT_MODEL_PROVIDER = "openai-compatible"
$env:AGENT_MODEL_BASE_URL = "https://api.openai.com/v1"
$env:AGENT_MODEL_NAME = "<model name>"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

## Verify Locally

Windows:

```powershell
.\scripts\verify.ps1
```

Linux/macOS:

```bash
bash scripts/verify.sh
```

Docker:

```bash
docker build -t agent-runtime:verify .
docker run --rm agent-runtime:verify
```

The verification command compiles sources, runs tests, runs ruff, runs mypy, and checks basic CLI commands in a temporary workspace.

## Offline Model

For deterministic local smoke tests without API keys:

```powershell
$env:AGENT_MODEL_PROVIDER = "fake"
agent /model-check --root .
agent /new "create offline artifact" --root .
agent /run --root .
```

The fake provider is for reproducible validation only. It does not evaluate real model quality.

## Local Models

Local OpenAI-compatible servers are supported through provider aliases:

```powershell
$env:AGENT_MODEL_PROVIDER = "ollama"
$env:AGENT_MODEL_NAME = "qwen2.5-coder:7b"
agent /model-check --root .
```

Default local endpoints:

- `ollama` / `local`: `http://localhost:11434/v1`
- `lmstudio`: `http://localhost:1234/v1`
- `vllm`: `http://localhost:8000/v1`
- `localai`: `http://localhost:8080/v1`

See [docs/zh/DEVELOPMENT.md](docs/zh/DEVELOPMENT.md) for the Chinese development guide.
