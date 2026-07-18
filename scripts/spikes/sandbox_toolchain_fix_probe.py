"""ADR-0030 S-B "try-fix" spike: the 1.2.122 compat probe recorded that git / pytest / node break in
the AppContainer; this one runs targeted micro-experiments to pin the ROOT CAUSE of each and test the
cheapest candidate fixes — so the S-B-impl slice is evidence-driven, not guessed. It does NOT modify
the user profile ACLs (that surgery is deferred to impl with a recommendation); every experiment runs
INSIDE the container, which is isolated and safe.

Run: python scripts/spikes/sandbox_toolchain_fix_probe.py   (Windows; needs `asteria sandbox provision`)

Hypotheses under test:
  GIT  — "could not open '/dev/null'": is the NUL *device* itself refused to the container (so git's
         msys /dev/null maps to a blocked \\Device\\Null), or is it git-specific? And does a controlled
         HOME / no-system-config env change anything?
  PYTEST — "Failed to find real location of python.exe": python RUNS (exit 0) but pytest's re-exec/
         path machinery needs GetFinalPathNameByHandle on the interpreter, whose ancestor dirs in the
         user profile are not traversable by the container. Confirm via realpath, and test whether an
         in-process pytest.main (no re-exec) or isolated mode sidesteps it — a cheap fix if it does.
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

ws = Path(tempfile.mkdtemp(prefix="asteria-tcfix-"))
(ws / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
(ws / "test_calc.py").write_text(
    "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    encoding="utf-8",
)
# Decisive experiment as a real script file (avoids -c shell-escaping noise): can the container's
# CRT open the NUL device at all, in each access mode? This is what actually settles the root cause.
(ws / "nul_modes.py").write_text(
    "import os\n"
    "r = []\n"
    "for name, flag in [('RDONLY', os.O_RDONLY), ('WRONLY', os.O_WRONLY), ('RDWR', os.O_RDWR)]:\n"
    "    try:\n"
    "        fd = os.open('nul', flag); os.close(fd); r.append(name + '=OK')\n"
    "    except OSError as e:\n"
    "        r.append(name + '=FAIL(errno%d)' % e.errno)\n"
    "print('NUL_MODES ' + ' '.join(r))\n",
    encoding="utf-8",
)
subprocess.run(["git", "init", "-q"], cwd=ws, capture_output=True)

ctx = sp.ensure_sandbox(str(ws))
base_env = dict(os.environ)
py = sys.executable
git = r"C:\Program Files\Git\cmd\git.exe"

# A container-writable HOME candidate: the granted io dir (inherits the container ACL).
granted_home = ctx.io_dir

experiments = [
    # --- GIT root-cause + cheap fixes ---
    ("git__baseline", f'"{git}" --version', base_env,
     "reproduce the /dev/null failure"),
    ("nul__write", 'cmd /c "echo hi>NUL & echo NULWRITE_OK"', base_env,
     "can the container write the NUL device at all?"),
    ("nul__read", 'cmd /c "type NUL & echo NULREAD_OK"', base_env,
     "can the container read the NUL device at all?"),
    ("git__nosys_home", f'"{git}" --version',
     {**base_env, "HOME": granted_home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "NUL"},
     "does a controlled HOME + no-system-config change the /dev/null failure?"),
    # --- PYTEST root-cause + cheap fixes ---
    ("py__version", f'"{py}" --version', base_env,
     "python runs (baseline) — the 'real location' line is a WARNING, not the failure"),
    ("py__realpath", f'"{py}" -c "import os,sys;print(\'RP=\'+os.path.realpath(sys.executable))"',
     base_env, "realpath SUCCEEDS in-container — proving 'real location' is a red herring"),
    ("nul__modes_python", f'"{py}" nul_modes.py', base_env,
     "THE root cause: can the CRT open the NUL device in each mode? (git+pytest both need this)"),
    ("pytest__dash_m", f'"{py}" -m pytest -q', base_env,
     "reproduce the true pytest failure: _pytest.capture FDCapture os.open(os.devnull, O_RDWR)"),
    ("pytest__capture_sys", f'"{py}" -m pytest -q --capture=sys', base_env,
     "does --capture=sys (no FDCapture) avoid the devnull open? (cheap partial workaround test)"),
]

results = []
for label, command, env, hypothesis in experiments:
    try:
        r = run_sandboxed(ctx, command, cwd=str(ws), env=env, timeout=90, allow_network=False)
        exit_code, out = r.returncode, (r.stdout + r.stderr)
    except Exception as exc:  # noqa: BLE001 - probe records failures, never raises
        exit_code, out = -1, f"{type(exc).__name__}: {exc}"
    ascii_out = out.encode("ascii", "replace").decode("ascii").strip()
    head = ascii_out[:200]
    # The real exception is at the END of a traceback, so keep the tail too (devnull PermissionError).
    tail = ascii_out[-300:] if len(ascii_out) > 500 else ""
    results.append(
        {
            "label": label,
            "hypothesis": hypothesis,
            "exit": exit_code,
            "output_head": head,
            "output_tail": tail,
        }
    )
    print(f"  exit={exit_code:>5}  {label}")
    if head:
        print(f"           {head[:150]}")

subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(ws)], capture_output=True)

Path(__file__).with_name("sandbox_toolchain_fix_probe_result.json").write_text(
    json.dumps({"results": results}, indent=2, ensure_ascii=False), encoding="utf-8"
)
print("\nReport written next to this script.")
