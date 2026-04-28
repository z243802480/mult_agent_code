#!/usr/bin/env bash
set -euo pipefail

python -m compileall -q src tests
python -m pytest
python -m ruff check .
python -m mypy src

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT

agent /init --root "$tmp_root/workspace"
agent /sessions --root "$tmp_root/workspace"
agent /run --help >/dev/null
