"""ADR-0030 S-B NUL-access feasibility probe (phase 1: diagnose namespace vs DACL — SAFE, no system
change). 1.2.139 pinned the unified root cause: git+pytest fail because the container cannot open the
NUL device. Before touching any system security descriptor, this asks a cheaper question that decides
the whole fix direction:

  Is NUL unreachable because the container's DOS-device map (\\??\\) doesn't resolve "NUL"/"\\.\\NUL"
  (a NAMESPACE problem — fixable per-container with a device symlink, NO system change), or because
  the \\Device\\Null object's DACL denies the container (a DACL problem — needs a system-level grant
  that may not survive reboot)?

Test: open NUL from inside the container via three paths of increasing "directness":
  - "nul"                          → via the CRT reserved-name → DOS device map
  - "\\\\.\\NUL"                   → Win32 device path → DOS device map
  - "\\\\?\\GLOBALROOT\\Device\\Null" → object-manager path, BYPASSES the DOS device map
If GLOBALROOT succeeds while the others fail → NAMESPACE problem (clean fix). If all fail → DACL.

Run: python scripts/spikes/sandbox_nul_grant_probe.py   (Windows; needs `asteria sandbox provision`)
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

ws = Path(tempfile.mkdtemp(prefix="asteria-nulg-"))
# A script file (not -c) so the many backslashes in the device paths survive shell layers intact.
(ws / "nul_paths.py").write_text(
    "import os\n"
    "paths = {\n"
    "    'crt_nul': 'nul',\n"
    "    'dosdev_nul': r'\\\\.\\NUL',\n"
    "    'globalroot': r'\\\\?\\GLOBALROOT\\Device\\Null',\n"
    "}\n"
    "out = []\n"
    "for label, p in paths.items():\n"
    "    for mode_name, flag in [('RDWR', os.O_RDWR), ('RDONLY', os.O_RDONLY)]:\n"
    "        try:\n"
    "            fd = os.open(p, flag); os.close(fd); r = 'OK'\n"
    "        except OSError as e:\n"
    "            r = 'FAIL(errno%d,win%s)' % (e.errno, getattr(e, 'winerror', '?'))\n"
    "        out.append('%s/%s=%s' % (label, mode_name, r))\n"
    "open('nul_paths_result.txt', 'w').write('\\n'.join(out))\n",
    encoding="utf-8",
)

ctx = sp.ensure_sandbox(str(ws))
r = run_sandboxed(
    ctx, f'"{sys.executable}" nul_paths.py', cwd=str(ws), env=dict(os.environ),
    timeout=60, allow_network=False,
)
result_file = ws / "nul_paths_result.txt"
result = result_file.read_text(encoding="utf-8") if result_file.exists() else "(no result file)"

report = {
    "launch_exit": r.returncode,
    "in_container_nul_open": result,
    "stderr_head": r.stderr.encode("ascii", "replace").decode("ascii")[:200],
}
print(json.dumps(report, indent=2, ensure_ascii=False))
Path(__file__).with_name("sandbox_nul_grant_probe_result.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
)
subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(ws)], capture_output=True)
print("\nReport written next to this script.")
