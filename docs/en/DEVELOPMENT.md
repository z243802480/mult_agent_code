# Development Environment and Verification

This document records local development setup, model configuration, real-model smoke checks, acceptance suites, and pre-submit verification. The Chinese documentation tree is the more detailed project source of truth; this file is the English counterpart.

## 1. Python Environment

The target runtime is Python 3.11 or newer. Before running commands from the repository root, set:

```powershell
$env:PYTHONPATH = "src"
```

For an editable development environment:

```powershell
python -m pip install -e ".[dev]"
```

## 2. Common Commands

Inspect the CLI:

```powershell
python -m agent_runtime --help
```

Initialize a workspace:

```powershell
python -m agent_runtime init --root .
```

Run the minimal autonomous loop:

```powershell
python -m agent_runtime run "Build a local notes module" --root .
```

Run tests and static checks:

```powershell
python -m pytest
ruff check .
mypy src
```

Run the unified verification script:

```powershell
.\scripts\verify.ps1
```

## 3. Model Configuration

The default real provider is MiniMax:

```powershell
$env:AGENT_MODEL_PROVIDER = "minimax"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

MiniMax keys may be region-specific. The runtime defaults to `https://api.minimax.io/v1`; when a key starts with `sk-cp-`, it automatically switches to the China endpoint `https://api.minimaxi.com/v1`. To force a specific endpoint:

```powershell
$env:AGENT_MODEL_BASE_URL = "https://api.minimaxi.com/v1"
```

API keys must be injected through process environment variables, CI secrets, or local secret management. Do not write real keys into `.env`, documentation, fixtures, logs, or commits.

OpenAI-compatible provider:

```powershell
$env:AGENT_MODEL_PROVIDER = "openai-compatible"
$env:AGENT_MODEL_BASE_URL = "https://api.openai.com/v1"
$env:AGENT_MODEL_NAME = "<model name>"
$env:AGENT_MODEL_API_KEY = "<your key>"
```

Local model provider:

```powershell
$env:AGENT_MODEL_PROVIDER = "ollama"
$env:AGENT_MODEL_NAME = "qwen2.5-coder:7b"
```

Tiered routing example:

```powershell
$env:AGENT_MODEL_STRONG_PROVIDER = "minimax"
$env:AGENT_MODEL_STRONG_API_KEY = "<your minimax key>"
$env:AGENT_MODEL_STRONG_NAME = "MiniMax-M2.7"

$env:AGENT_MODEL_MEDIUM_PROVIDER = "ollama"
$env:AGENT_MODEL_MEDIUM_NAME = "qwen2.5-coder:7b"

$env:AGENT_MODEL_CHEAP_PROVIDER = "fake"
```

If a tier-specific provider is not configured, the runtime falls back to the global `AGENT_MODEL_PROVIDER`.

## 4. Real-Model Smoke

Use the real-model smoke script for provider-level verification. It creates a temporary workspace, runs `/init`, `/model-check`, and a minimal `/run`, then checks target files, session logs, cost reports, model calls, tool calls, review status, and task completion:

```powershell
python scripts/real_model_smoke.py
```

Windows wrapper:

```powershell
.\scripts\real_model_smoke.ps1
```

Use explicit output paths when machine-readable summaries are needed:

```powershell
python scripts/real_model_smoke.py --root C:\temp\agent-real-smoke --summary-json C:\temp\agent-real-smoke-summary.json
```

For transient TLS EOF, timeout, or provider instability, increase model retries:

```powershell
$env:AGENT_MODEL_MAX_RETRIES = "5"
python scripts/real_model_smoke.py
```

The script defaults child processes to five model retries when `AGENT_MODEL_MAX_RETRIES` is not set, and it can retry the entire `/run` after early provider transport failures:

```powershell
python scripts/real_model_smoke.py --run-attempts 3 --model-max-retries 5
```

Pass criteria:

- `model-check` succeeds.
- `.agent/runs/<session_id>/final_report.md` exists.
- Run status is `completed`.
- `eval_report.json` overall status is `pass`.
- `task_plan.json` has no incomplete or blocked tasks.
- Expected target artifacts exist and match the user goal.
- Failures, retries, tool calls, and model calls are recorded under `.agent/`.
- No real API key appears in the repository.

## 5. Real-Task Acceptance Suite

After the minimal smoke passes, run the real-task acceptance suite:

```powershell
python scripts/real_model_acceptance.py --suite core
```

The current `core` suite includes:

- `file_smoke`: minimal file creation loop.
- `password_cli`: generate a single-file password strength CLI.
- `markdown_kb`: generate a single-file Markdown indexing/search tool.

Run a single scenario:

```powershell
python scripts/real_model_acceptance.py --scenario password_cli
```

Acceptance normally requires a real provider. Fake providers are only allowed for runner tests:

```powershell
python scripts/real_model_acceptance.py --suite offline --allow-fake
```

`agent acceptance` writes results under `.agent/acceptance/`:

- `latest_summary.json`: raw machine-readable script summary.
- `acceptance_report.json`: schema-validated runtime report with suite, scenarios, result status, failure summaries, and output tails.

To feed failed scenarios back into the development loop:

```bash
python -m agent_runtime /acceptance --suite core --promote-failures
```

This creates ready repair tasks in the current session `task_plan.json`, syncs `.agent/tasks/backlog.json`, records `failure_lesson` entries under `.agent/memory/failures.jsonl`, and writes structured evidence under `.agent/acceptance/failures/<scenario>.json`.

Use `--run-promoted` to execute promoted repair tasks immediately. Use `--rerun-promoted` to rerun only the newly promoted scenarios after repair and record closure details under `acceptance_report.json.repair_closure`.

## 6. Structured Output Tolerance

Real models may return `<think>` blocks, markdown fences, near-JSON, or small field drift. The runtime applies bounded tolerance at the model boundary:

- Extract the last parseable JSON object.
- Strip a markdown code fence only when the entire response is fenced.
- Remove `<think>...</think>` blocks.
- Normalize bounded fields for `GoalSpec`, `ExecutionAction`, and `EvalReport`.
- Filter unknown tool-call arguments against the tool signature and record warnings.

Tolerance is not a relaxed persistence model. Persisted runtime objects still must pass schema validation. Unsafe outputs must block, log the reason, and enter repair or decision flow.

## 7. Verification Artifacts

`agent run` writes session artifacts under `.agent/sessions/<session_id>/`:

- `goal_spec.json`
- `task_plan.json`
- `events.jsonl`
- `tool_calls.jsonl`
- `model_calls.jsonl`
- `cost_report.json`
- `review_report.md`
- `final_report.md`

Before committing code, verify:

- Source passes `.\scripts\verify.ps1`.
- New behavior has unit or integration tests.
- Command, model, or safety-boundary changes include failure-path tests.
- Real-model verification only records redacted/example key prefixes, never real keys.

## 8. ContextSnapshot and Handoff

Before long pauses, handoff, context compression, or user-decision stages:

```powershell
python -m agent_runtime /compact --root .
python -m agent_runtime /handoff --root . --to-role FutureRun
```

`ContextSnapshot` must preserve recoverable state, not just a chat summary:

- Goal summary and definition of done.
- Accepted and pending decisions.
- Current run status, phase, and task statistics.
- Active tasks, latest artifacts, modified files, verification results, and failure evidence.
- Review/final-report summaries, open risks, and next actions.

`HandoffPackage` recommends the next command based on state: `decide` for pending decisions, `debug` for failures or blocked tasks, `execute` for ready/in-progress tasks, and `review` when tasks are complete.
