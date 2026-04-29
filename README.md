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
Failed implementation candidates are backed up, rolled back, and recorded as discarded experiments
before the debug loop attempts a clean repair.
Policy-blocked execution plans pause the run with a one-time decision point; approving it resumes
the original task without changing global permissions.
Applied decisions are also written to `.agent/memory/decisions.jsonl`, so constraints,
cancelled scope, and replanning choices remain durable across handoffs.
Planner, coder, and debug agents receive a bounded runtime context assembled from memory,
the latest snapshot, and the latest handoff package.

## Model Configuration

MiniMax is the default provider:

```powershell
$env:AGENT_MODEL_PROVIDER = "minimax"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

MiniMax keys are region-specific. The runtime uses `https://api.minimax.io/v1` by default
and switches to `https://api.minimaxi.com/v1` for China-region `sk-cp-` keys.

Model tiers can be routed independently. This keeps expensive calls for planning/review while
using cheaper or local models for routine work:

```powershell
$env:AGENT_MODEL_STRONG_PROVIDER = "minimax"
$env:AGENT_MODEL_STRONG_API_KEY = "<your minimax key>"
$env:AGENT_MODEL_STRONG_NAME = "MiniMax-M2.7"

$env:AGENT_MODEL_MEDIUM_PROVIDER = "ollama"
$env:AGENT_MODEL_MEDIUM_NAME = "qwen2.5-coder:7b"

$env:AGENT_MODEL_CHEAP_PROVIDER = "fake"
```

If no tier-specific provider is configured, the runtime falls back to `AGENT_MODEL_PROVIDER`.

OpenAI-compatible providers are also supported:

```powershell
$env:AGENT_MODEL_PROVIDER = "openai-compatible"
$env:AGENT_MODEL_BASE_URL = "https://api.openai.com/v1"
$env:AGENT_MODEL_NAME = "<model name>"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

## Real Model Smoke

Use a temporary workspace for real-provider checks so repository state stays clean:

```powershell
python scripts/real_model_smoke.py
```

The script runs `/init`, `/model-check`, and a minimal `/run`, then verifies the expected file,
session logs, cost report, model calls, tool calls, and final report. If the provider link is flaky,
increase `AGENT_MODEL_MAX_RETRIES` and rerun the script.
Never commit real API keys; keep them in process environment variables or secret storage only.

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

## Benchmarks

Run deterministic MVP regression scenarios:

```powershell
python scripts/run_benchmarks.py
```

The runner currently covers the password-tool smoke scenario and a failing-tests repair scenario.

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
