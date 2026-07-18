"""ADR-0030 S-B compatibility spike: does a REAL toolchain (git, pytest, ruff, node/npm) actually
work INSIDE the AppContainer, or do container restrictions (readable tool dirs, pytest's import/
cache machinery, subprocess) break it? This is the evidence gate for turning sandbox_shell on by
default — the mechanism is proven (1.2.121); this asks whether real work survives it.

PROBE, not production. Builds a real small python project + git repo in a temp workspace, grants it
the container ACL, and runs the toolchain in-container with allow_network=False (these tools need no
network). Records exit + output head + a verdict per tool.

Run: python scripts/spikes/sandbox_toolchain_probe.py   (Windows; needs `asteria sandbox provision`)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from asteria_runtime.core import sandbox_provision as sp
from asteria_runtime.core.sandbox_launch import run_sandboxed

if sys.platform != "win32":
    raise SystemExit("Windows only")
if not sp.toolchain_ready():
    raise SystemExit("run `asteria sandbox provision` first")

ws = Path(tempfile.mkdtemp(prefix="asteria-tc-"))
(ws / "pyproject.toml").write_text(
    "[project]\nname='tc-probe'\nversion='0.0.1'\n", encoding="utf-8"
)
(ws / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
(ws / "test_calc.py").write_text(
    "from calc import add\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n"
    "def test_add_zero():\n    assert add(0, 0) == 0\n",
    encoding="utf-8",
)
subprocess.run(["git", "init", "-q"], cwd=ws, capture_output=True)
subprocess.run(["git", "add", "-A"], cwd=ws, capture_output=True)

ctx = sp.ensure_sandbox(str(ws))
env = dict(os.environ)
py = sys.executable
git = r"C:\Program Files\Git\cmd\git.exe"
node = r"C:\Program Files\nodejs\node.exe"
npm = r"C:\Program Files\nodejs\npm.cmd"

matrix = [
    ("python --version", f'"{py}" --version'),
    ("stdlib import", f'"{py}" -c "import json,os,sys,subprocess; print(\'ok\')"'),
    ("git --version", f'"{git}" --version'),
    ("git status", f'"{git}" status --short'),
    ("pytest (real run, 2 tests)", f'"{py}" -m pytest -q'),
    ("ruff check", f'"{py}" -m ruff check calc.py'),
    ("node --version", f'"{node}" --version'),
    ("npm --version", f'"{npm}" --version'),
]

results = []
for label, command in matrix:
    try:
        r = run_sandboxed(ctx, command, cwd=str(ws), env=env, timeout=90, allow_network=False)
        exit_code, out = r.returncode, (r.stdout + r.stderr)
    except Exception as exc:  # noqa: BLE001 - probe records failures, does not raise
        exit_code, out = -1, f"{type(exc).__name__}: {exc}"
    head = out.encode("ascii", "replace").decode("ascii").strip()[:180]
    results.append({"tool": label, "exit": exit_code, "output_head": head})
    print(f"  exit={exit_code:>4}  {label}")
    if head:
        print(f"          {head[:120]}")

subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(ws)], capture_output=True)

report = {"results": results}
Path(__file__).with_name("sandbox_toolchain_probe_result.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
)
print("\nReport written next to this script.")
