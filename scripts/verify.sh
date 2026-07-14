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
# 自主环 ring-recovery benchmark 的 plumbing 档(确定性·无需 provider key)。罐头 provider 修不好
# bug,故这里**不**证恢复——只证 benchmark harness 没随运行时 API 漂移而腐坏(单测覆盖不到脚本的
# 端到端接线)。真栈恢复证明在 nightly(.github/workflows/ring-recovery-nightly.yml)。
"$python_bin" scripts/ring_recovery_smoke.py --allow-fake

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

export AGENT_MODEL_PROVIDER=fake

"$python_bin" -m asteria_runtime /init --root "$tmp_root/workspace"
"$python_bin" -m asteria_runtime /model-check --root "$tmp_root/workspace"
"$python_bin" -m asteria_runtime /new "create offline artifact" --root "$tmp_root/workspace"
"$python_bin" -m asteria_runtime /sessions --root "$tmp_root/workspace"
"$python_bin" -m asteria_runtime /run --root "$tmp_root/workspace"
"$python_bin" -m asteria_runtime /compact --root "$tmp_root/workspace"
"$python_bin" -m asteria_runtime /handoff --root "$tmp_root/workspace" --to FutureRun
sessions_context="$("$python_bin" -m asteria_runtime /sessions --root "$tmp_root/workspace" --context)"
grep -q "snapshot:" <<<"$sessions_context"
grep -q "handoff:" <<<"$sessions_context"
grep -q "next:" <<<"$sessions_context"
find "$tmp_root/workspace/.asteria/context/snapshots" -maxdepth 1 -name "*.json" -print -quit | grep -q .
find "$tmp_root/workspace/.asteria/context/handoffs" -maxdepth 1 -name "*.json" -print -quit | grep -q .
test -f "$tmp_root/workspace/offline_artifact.txt"
"$python_bin" scripts/write_verification_summary.py --root . --platform linux --cli-workspace "$tmp_root/workspace"
"$python_bin" -m asteria_runtime /verification --root .
"$python_bin" -m asteria_runtime /acceptance --root "$tmp_root/acceptance" --suite offline --allow-fake
"$python_bin" -m asteria_runtime /acceptance-gate --root "$tmp_root/acceptance" --suite offline --min-scenarios 1
