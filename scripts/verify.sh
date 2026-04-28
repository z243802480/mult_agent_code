#!/usr/bin/env bash
set -euo pipefail

python -m compileall -q src tests
python -m pytest
python -m ruff check .
python -m mypy src

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

export AGENT_MODEL_PROVIDER=fake

agent /init --root "$tmp_root/workspace"
agent /model-check --root "$tmp_root/workspace"
agent /new "create offline artifact" --root "$tmp_root/workspace"
agent /sessions --root "$tmp_root/workspace"
agent /run --root "$tmp_root/workspace"
test -f "$tmp_root/workspace/offline_artifact.txt"
