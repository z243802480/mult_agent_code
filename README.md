# agent-runtime

Local-first multi-agent development runtime. The current MVP path is a CLI that turns a goal into a GoalSpec, task plan, controlled tool execution, repair, review, context snapshot, and final report.

## Quick Start

Use Python 3.11+ from the repository root.

```powershell
$env:PYTHONPATH = "src"
python -m agent_runtime --help
python -m agent_runtime init --root .
python -m agent_runtime model-check --root .
python -m agent_runtime run "create a tiny local notes module" --root .
```

`agent run` writes run artifacts under `.agent/runs/<run_id>/`, including `goal_spec.json`, `task_plan.json`, logs, `review_report.md`, and `final_report.md`.

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

## Model Health Check

Before running a full goal, validate provider configuration and JSON-mode behavior:

```powershell
python -m agent_runtime model-check --root .
python -m agent_runtime model-check --root . --skip-call
```

`--skip-call` only validates local environment configuration. Without it, the command sends one small JSON health-check prompt to the configured provider.

## Development

Install dev dependencies in your preferred local environment, then run:

```powershell
$env:PYTHONPATH = "src"
python -m pytest
python -m compileall -q src tests
ruff check .
mypy src
```

See [docs/zh/DEVELOPMENT.md](docs/zh/DEVELOPMENT.md) for the Chinese development guide.
