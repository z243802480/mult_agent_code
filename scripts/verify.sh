#!/usr/bin/env bash
set -euo pipefail

python_bin="python"
if [[ -x ".venv/bin/python" ]]; then
  python_bin=".venv/bin/python"
elif [[ -x ".venv/Scripts/python.exe" ]]; then
  python_bin=".venv/Scripts/python.exe"
fi

export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"

"$python_bin" -m compileall -q src tests
"$python_bin" -m pytest
"$python_bin" -m ruff check .
"$python_bin" -m mypy src
"$python_bin" scripts/run_benchmarks.py

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

export AGENT_MODEL_PROVIDER=fake

"$python_bin" -m agent_runtime /init --root "$tmp_root/workspace"
"$python_bin" -m agent_runtime /model-check --root "$tmp_root/workspace"
"$python_bin" -m agent_runtime /new "create offline artifact" --root "$tmp_root/workspace"
"$python_bin" -m agent_runtime /sessions --root "$tmp_root/workspace"
"$python_bin" -m agent_runtime /run --root "$tmp_root/workspace"
"$python_bin" -m agent_runtime /compact --root "$tmp_root/workspace"
"$python_bin" -m agent_runtime /handoff --root "$tmp_root/workspace" --to FutureRun
sessions_context="$("$python_bin" -m agent_runtime /sessions --root "$tmp_root/workspace" --context)"
grep -q "snapshot:" <<<"$sessions_context"
grep -q "handoff:" <<<"$sessions_context"
grep -q "next:" <<<"$sessions_context"
find "$tmp_root/workspace/.agent/context/snapshots" -maxdepth 1 -name "*.json" -print -quit | grep -q .
find "$tmp_root/workspace/.agent/context/handoffs" -maxdepth 1 -name "*.json" -print -quit | grep -q .
test -f "$tmp_root/workspace/offline_artifact.txt"
"$python_bin" scripts/write_verification_summary.py --root . --platform linux --cli-workspace "$tmp_root/workspace"
"$python_bin" -m agent_runtime /verification --root .
