"""ADR-0030 S-B NUL-access feasibility probe (phase 2: does granting the NUL device an
ALL_APPLICATION_PACKAGES ACE let the container open it?).

Phase 1 (sandbox_nul_grant_probe.py) proved the block is NOT the DOS-device namespace (GLOBALROOT
also fails) and NOT missing world access — the NUL device DACL already grants Everyone (WD) 0x1201bf.
The block is the AppContainer model: an AppContainer token does not honour World ACEs on device
objects; the DACL must name ALL_APPLICATION_PACKAGES (AC / S-1-15-2-1) explicitly — exactly like
sandbox_provision grants AC to the toolchain dir. The NUL DACL has no AC ace. This tests adding one.

SAFETY: this modifies a SYSTEM device object's DACL. The change is ADDITIVE (appends one AC allow
ace, removes nothing) and BENIGN (NUL is a bit-bucket with no security value — Everyone already has
read/write). It is fully REVERSED in a finally block by re-applying the captured original DACL. It is
also NON-PERSISTENT by nature: the kernel recreates \\Device\\Null with the default DACL at every
boot, so this is a probe of feasibility, not a durable change.

Run: python scripts/spikes/sandbox_nul_grant_test.py   (Windows admin; needs `asteria sandbox provision`)
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

from asteria_runtime.core import sandbox_provision as sp
from asteria_runtime.core.sandbox_launch import run_sandboxed

if sys.platform != "win32":
    raise SystemExit("Windows only")
if not sp.toolchain_ready():
    raise SystemExit("run `asteria sandbox provision` first")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
a32 = ctypes.WinDLL("advapi32", use_last_error=True)

READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
FILE_SHARE_RW = 0x03
OPEN_EXISTING = 3
SE_KERNEL_OBJECT = 6
DACL_SECURITY_INFORMATION = 0x00000004
SDDL_REVISION_1 = 1
AAP_ACE = "(A;;FA;;;AC)"  # FILE_ALL_ACCESS to ALL_APPLICATION_PACKAGES

k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]


def _open_nul_for_dac() -> wintypes.HANDLE:
    h = k32.CreateFileW(r"\\.\NUL", READ_CONTROL | WRITE_DAC, FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
    if h == wintypes.HANDLE(-1).value or not h:
        raise SystemExit(f"open NUL (WRITE_DAC) failed: {ctypes.get_last_error()} (run as admin)")
    return h


def _read_dacl_sddl(h: wintypes.HANDLE) -> str:
    psd = ctypes.c_void_p()
    a32.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    if a32.GetSecurityInfo(h, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION,
                           None, None, None, None, ctypes.byref(psd)) != 0:
        raise SystemExit("GetSecurityInfo failed")
    sddl = wintypes.LPWSTR()
    a32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    if not a32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            psd, SDDL_REVISION_1, DACL_SECURITY_INFORMATION, ctypes.byref(sddl), None):
        raise SystemExit("ConvertSD failed")
    out = sddl.value or ""
    k32.LocalFree(sddl)
    return out  # e.g. "D:(A;;0x1201bf;;;WD)..."


def _set_dacl_from_sddl(h: wintypes.HANDLE, dacl_sddl: str) -> None:
    psd = ctypes.c_void_p()
    a32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    if not a32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            dacl_sddl, SDDL_REVISION_1, ctypes.byref(psd), None):
        raise SystemExit(f"ConvertStringSD failed: {ctypes.get_last_error()}")
    present = wintypes.BOOL()
    pdacl = ctypes.c_void_p()
    defaulted = wintypes.BOOL()
    a32.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                              ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    if not a32.GetSecurityDescriptorDacl(psd, ctypes.byref(present), ctypes.byref(pdacl), ctypes.byref(defaulted)):
        raise SystemExit("GetSecurityDescriptorDacl failed")
    a32.SetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    rc = a32.SetSecurityInfo(h, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION, None, None, pdacl, None)
    k32.LocalFree(psd)
    if rc != 0:
        raise SystemExit(f"SetSecurityInfo failed: {rc}")


_GIT = r"C:\Program Files\Git\cmd\git.exe"


def _probe_in_container() -> dict:
    """Open NUL directly, and run the two real toolchain blockers (git, pytest) that 1.2.139 pinned
    on the NUL open — so before/after the grant shows not just the micro-open but the actual payoff."""
    ws = Path(tempfile.mkdtemp(prefix="asteria-nulgt-"))
    (ws / "nul_open.py").write_text(
        "import os\n"
        "try:\n"
        "    fd = os.open('nul', os.O_RDWR); os.close(fd); r = 'OK'\n"
        "except OSError as e:\n"
        "    r = 'FAIL(errno%d)' % e.errno\n"
        "open('r.txt','w').write(r)\n",
        encoding="utf-8",
    )
    (ws / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (ws / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=ws, capture_output=True)
    ctx = sp.ensure_sandbox(str(ws))
    py = sys.executable
    env = dict(os.environ)

    def run(cmd: str) -> dict:
        r = run_sandboxed(ctx, cmd, cwd=str(ws), env=env, timeout=90, allow_network=False)
        return {"exit": r.returncode, "tail": (r.stdout + r.stderr).encode("ascii", "replace").decode("ascii")[-160:]}

    run(f'"{py}" nul_open.py')
    nul = (ws / "r.txt").read_text(encoding="utf-8") if (ws / "r.txt").exists() else "(no result)"
    out = {"nul_open": nul, "git": run(f'"{_GIT}" --version'), "pytest": run(f'"{py}" -m pytest -q')}
    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(ws)], capture_output=True)
    return out


h = _open_nul_for_dac()
report: dict = {}
try:
    original_dacl = _read_dacl_sddl(h)
    report["original_nul_dacl"] = original_dacl
    report["before_grant"] = _probe_in_container()
    granted_dacl = original_dacl + AAP_ACE  # append the AC ace to the DACL
    _set_dacl_from_sddl(h, granted_dacl)
    report["granted_nul_dacl"] = _read_dacl_sddl(h)
    report["after_grant"] = _probe_in_container()
finally:
    # ALWAYS restore the captured original DACL, even on error.
    try:
        _set_dacl_from_sddl(h, report.get("original_nul_dacl", ""))
        report["restored_nul_dacl"] = _read_dacl_sddl(h)
    except Exception as exc:  # noqa: BLE001
        report["RESTORE_ERROR"] = f"{type(exc).__name__}: {exc} — ORIGINAL: {report.get('original_nul_dacl')}"
    k32.CloseHandle(h)

before = report.get("before_grant", {})
after = report.get("after_grant", {})
nul_fixed = before.get("nul_open") != "OK" and after.get("nul_open") == "OK"
git_fixed = after.get("git", {}).get("exit") == 0
report["verdict"] = {
    "nul_open_fixed_by_grant": nul_fixed,
    "git_fixed_by_grant": git_fixed,
    "pytest_fixed_by_grant": after.get("pytest", {}).get("exit") == 0,
    "summary": (
        "NUL AC-ace grant is FEASIBLE and fixes git; pytest passes the NUL wall but may hit a "
        "second wall (stat/traverse of un-granted ancestor dirs — same AppContainer-ignores-World "
        "semantics, now on directories). See ADR-0030 S-B-fix."
        if nul_fixed and git_fixed
        else "grant did NOT deliver the expected fix — re-diagnose"
    ),
}
print(json.dumps(report, indent=2, ensure_ascii=False))
Path(__file__).with_name("sandbox_nul_grant_test_result.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
)
