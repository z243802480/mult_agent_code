# Asteria

Local-first multi-agent autonomous development runtime. The current MVP path is a CLI that
turns a goal into a GoalSpec, task plan, controlled tool execution, repair, review, context
snapshot, and final report.

The active product direction is Asteria Runtime OS for long-task autonomous
development: task contracts, worker invocation evidence, isolated candidates, merge gates,
resume/handoff, acceptance gates, and cost controls. The Chinese documents are the current
source of truth; start with `docs/zh/当前状态与路线.md`.

## Quick Start

```powershell
python -m pip install -e ".[dev]"
asteria --help
asteria init --root .
asteria status --root .
```

The default user workflow is `init -> run -> status -> resume -> review -> accept`:
start a goal with `asteria run "goal"`, inspect progress with `asteria status`, resolve
runtime decisions with `asteria resume` after `asteria decide`, verify the result with
`asteria review`, then finalize reviewed candidate outputs with `asteria accept`.
`asteria accept` finalizes one reviewed run; `asteria acceptance` runs validation
suites for maintainers and CI, so it is not part of the ordinary user completion
path. Use plain command names in new docs and scripts; slash-prefixed forms such as
`asteria /run` remain compatibility aliases for older automation.

`asteria run "goal"` writes run artifacts under `.asteria/runs/<run_id>/`, including
`goal_spec.json`, `task_plan.json`, `task_plan_eval.json`, logs, `review_report.md`, and
`final_report.md`.
Execute and debug attempts run in isolated candidate workspaces under the active run directory.
Validated changed files are promoted back to the source workspace; failed candidates stay isolated
and are recorded as discarded experiments for repair/debug evidence.
Policy-blocked execution plans pause the run with a one-time decision point; approving it resumes
the original task without changing global permissions.
Applied decisions are also written to `.asteria/memory/decisions.jsonl`, so constraints,
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
asteria real-model-smoke
```

The script runs `init`, `model-check`, and a minimal `run`, then verifies the expected file,
session logs, cost report, model calls, tool calls, review pass status, and that every task is done.
If the provider link is flaky, the script retries the full `run` for transient provider errors and
sets `AGENT_MODEL_MAX_RETRIES=5` for subprocesses when you have not configured it yourself.
Never commit real API keys; keep them in process environment variables or secret storage only.

For a broader manual acceptance pass, run curated real-task scenarios:

```powershell
asteria real-model-acceptance --suite core
```

The `core` suite covers file smoke, single-file CLI work, markdown search, safe dry-run rename,
multi-file changes, config-driven reporting, and Runtime OS release-gate scenarios. The `advanced` and `nightly` suites add
test-driven repair, docs+code sync, safe refactor, decision memory, and memory lesson reuse. These
are intentionally not part of default CI because they consume real provider calls.
When budget allows, use `--suite nightly` for the broader stability pass. Acceptance summaries include
duration, run status, review status, task status counts, model/tool calls, token estimates, repair
attempts, and context compactions so real-provider quality and cost can be compared over time.
Pass `--history-jsonl <path>` to append comparable summaries and include trend deltas. The runtime
`asteria acceptance` command writes `.asteria/acceptance/history.jsonl` automatically.
Inspect persisted history with:

```powershell
python -m asteria_runtime acceptance-history --root . --limit 5
```
Use it as a local gate with:

```powershell
python -m asteria_runtime acceptance-history --root . --suite nightly --fail-on-warning
```

Or make `/acceptance` fail immediately when the latest run introduces trend regressions:

```powershell
python -m asteria_runtime acceptance --root . --suite core --fail-on-trend-warning
```

For release gating, evaluate the latest persisted acceptance report:

```powershell
python -m asteria_runtime acceptance-gate --root . --suite core --min-scenarios 10 --min-capabilities 10
```

The gate blocks when acceptance failed without a successful repair rerun, when trend warnings are
present, when Runtime OS worker/merge/resume evidence is incomplete, or when the report does not
cover the required suite/scenario/capability/tier count.

Summarize recent real-task capability health with:

```powershell
python -m asteria_runtime capability-report --root .
```

The report combines acceptance history, capability coverage, failure type distribution, repair
rounds, model/tool cost signals, common blockers, and recommended next actions.

`asteria acceptance` also persists machine-readable output under
`.asteria/acceptance/latest_summary.json` and `.asteria/acceptance/acceptance_report.json`.
Pass `--promote-failures` to turn failed scenarios into ready tasks on the current session.
Promoted tasks include report, summary, workspace, transcript, expected artifact, and reproduction commands.
Add `--run-promoted` to immediately continue the current session after new failure tasks are promoted.
Add `--rerun-promoted` to run the promoted tasks and then rerun only the newly promoted scenarios;
when the rerun passes, the command exits successfully and records the closed failures in the report.
Newly promoted failures are also recorded as `failure_lesson` entries in `.asteria/memory/failures.jsonl`.
Verification command rewrites live in `verification_command_normalizer.py` and only cover known low-risk test fixture patterns; unsafe commands still go through policy enforcement.

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
docker build -t asteria-runtime:verify .
docker run --rm asteria-runtime:verify
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
asteria model-check --root .
asteria new "create offline artifact" --root .
asteria run --root .
```

The fake provider is for reproducible validation only. It does not evaluate real model quality.

## Local Models

Local OpenAI-compatible servers are supported through provider aliases:

```powershell
$env:AGENT_MODEL_PROVIDER = "ollama"
$env:AGENT_MODEL_NAME = "qwen2.5-coder:7b"
asteria model-check --root .
```

Default local endpoints:

- `ollama` / `local`: `http://localhost:11434/v1`
- `lmstudio`: `http://localhost:1234/v1`
- `vllm`: `http://localhost:8000/v1`
- `localai`: `http://localhost:8080/v1`

See [docs/zh/开发指南.md](docs/zh/开发指南.md) for the Chinese development guide.
