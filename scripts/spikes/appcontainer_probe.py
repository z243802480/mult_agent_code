"""ADR-0030 S-B spike: does a Windows AppContainer actually isolate (no network, no write outside
its workspace), and what does it take to run a toolchain inside one?

This is a PROBE, not production code. Its job is evidence to decide whether S-B (default-deny
network + write-confined shell) is "just do it", "do it with an ACL allowlist", or "fall back to
WSL2". Two must-fail cases (network egress, write outside the workspace) are the self-check that
the container is genuinely confining — a probe that only ran happy-path commands would report
false-green.

Design decisions from the first attempt (recorded because they are findings):
  * Tools are launched from System32 (cmd/whoami/curl), which every AppContainer can read via the
    implicit ALL_APPLICATION_PACKAGES ACL. The FIRST attempt tried to `icacls /T` the whole Python
    install dir so the interpreter would be readable — it hung for minutes on site-packages. That
    cost IS the finding: S-B-impl must NOT grant a per-container ACL over a user-profile interpreter
    dir. So here we probe the interpreter only for the fast, decisive "unreadable without a grant"
    data point, and never recurse a big tree.
  * Every wait is bounded (30s) and stdout is line-buffered, so a hung child can't wedge the probe.

Run: python scripts/spikes/appcontainer_probe.py    (Windows only)
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

if sys.platform != "win32":
    raise SystemExit("AppContainer is Windows-only; this spike does not apply here.")

sys.stdout.reconfigure(line_buffering=True)  # see progress live even when redirected

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
WAIT_TIMEOUT = 0x102
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
CREATE_ALWAYS = 2
ERROR_ALREADY_EXISTS = 183
WAIT_MS = 30_000

APP_NAME = "asteria.sandbox.spike"
SYS32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


def _win_error(context: str) -> RuntimeError:
    return RuntimeError(f"{context} failed (GetLastError={ctypes.get_last_error()})")


def create_appcontainer_sid() -> ctypes.c_void_p:
    sid = ctypes.c_void_p()
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    hr = userenv.CreateAppContainerProfile(
        APP_NAME, APP_NAME, "asteria S-B spike", None, 0, ctypes.byref(sid)
    )
    if hr < 0:
        if (hr & 0xFFFF) == ERROR_ALREADY_EXISTS:
            userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
            if userenv.DeriveAppContainerSidFromAppContainerName(APP_NAME, ctypes.byref(sid)) < 0:
                raise RuntimeError("DeriveAppContainerSidFromAppContainerName failed")
        else:
            raise RuntimeError(f"CreateAppContainerProfile failed (HRESULT={hr & 0xFFFFFFFF:#010x})")
    return sid


def sid_to_string(sid: ctypes.c_void_p) -> str:
    out = wintypes.LPWSTR()
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(out)):
        raise _win_error("ConvertSidToStringSidW")
    value = out.value or ""
    kernel32.LocalFree(out)
    return value


def grant_full(path: str, sid_str: str) -> None:
    subprocess.run(
        ["icacls", path, "/grant", f"*{sid_str}:(OI)(CI)(F)", "/T", "/C", "/Q"],
        capture_output=True, text=True, timeout=60,
    )


def run_in_appcontainer(sid: ctypes.c_void_p, argv: list[str], cwd: str, out_path: str) -> int:
    sec_attr = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    hfile = kernel32.CreateFileW(
        out_path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
        ctypes.byref(sec_attr), CREATE_ALWAYS, 0, None,
    )
    if hfile == wintypes.HANDLE(-1).value:
        raise _win_error("CreateFileW(output)")

    size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    buf = (ctypes.c_byte * size.value)()
    if not kernel32.InitializeProcThreadAttributeList(buf, 1, 0, ctypes.byref(size)):
        raise _win_error("InitializeProcThreadAttributeList")

    caps = SECURITY_CAPABILITIES(sid, None, 0, 0)  # NO capabilities → no network
    if not kernel32.UpdateProcThreadAttribute(
        buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        ctypes.byref(caps), ctypes.sizeof(caps), None, None,
    ):
        raise _win_error("UpdateProcThreadAttribute")

    si = STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    si.StartupInfo.hStdOutput = hfile
    si.StartupInfo.hStdError = hfile
    si.lpAttributeList = ctypes.cast(buf, ctypes.c_void_p)

    pi = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(
        None, subprocess.list2cmdline(argv), None, None, True,
        EXTENDED_STARTUPINFO_PRESENT, None, cwd, ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        kernel32.CloseHandle(hfile)
        kernel32.DeleteProcThreadAttributeList(buf)
        raise RuntimeError(f"CreateProcessW-in-AppContainer failed (GetLastError={err})")

    wait = kernel32.WaitForSingleObject(pi.hProcess, WAIT_MS)
    if wait == WAIT_TIMEOUT:
        kernel32.TerminateProcess(pi.hProcess, 0xDEAD)
        code = 0xDEAD
    else:
        c = wintypes.DWORD()
        kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(c))
        code = c.value
    for h in (pi.hProcess, pi.hThread, hfile):
        kernel32.CloseHandle(h)
    kernel32.DeleteProcThreadAttributeList(buf)
    return code


def main() -> None:
    sid = create_appcontainer_sid()
    sid_str = sid_to_string(sid)
    print(f"AppContainer SID: {sid_str}")

    workspace = tempfile.mkdtemp(prefix="asteria-appc-")
    outdir = tempfile.mkdtemp(prefix="asteria-appc-out-")
    grant_full(workspace, sid_str)  # small tree → fast
    grant_full(outdir, sid_str)
    print("granted full ACL on workspace + outdir")

    cmd = os.path.join(SYS32, "cmd.exe")
    whoami = os.path.join(SYS32, "whoami.exe")
    curl = os.path.join(SYS32, "curl.exe")
    escape = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "asteria_escape.txt")

    matrix = [
        ("whoami identity in container", [whoami, "/user"], "must_pass"),
        ("network egress (curl http)", [curl, "-s", "--max-time", "6", "http://example.com"], "must_fail"),
        ("write inside workspace", [cmd, "/c", "echo x> probe.txt"], "must_pass"),
        (f"write outside workspace ({escape})", [cmd, "/c", f"echo x> {escape}"], "must_fail"),
        ("interpreter in user profile (no ACL grant)", [sys.executable, "--version"], "must_fail"),
    ]

    results = []
    for i, (label, argv, expectation) in enumerate(matrix):
        out_path = os.path.join(outdir, f"out{i}.txt")
        try:
            code = run_in_appcontainer(sid, argv, workspace, out_path)
            output = Path(out_path).read_text(encoding="utf-8", errors="replace").strip()
            launched = True
        except RuntimeError as exc:
            code, output, launched = -1, str(exc), False
        passed = (code == 0) if expectation == "must_pass" else (code != 0)
        results.append({
            "label": label, "expectation": expectation, "launched": launched,
            "exit": code, "verdict": "OK" if passed else "MISMATCH", "output_head": output[:200],
        })
        print(f"  [{results[-1]['verdict']:8}] {label}: exit={code} ({expectation})")

    # Prove the escape write really did NOT land (a must_fail that silently succeeded is the worst case).
    escaped = os.path.exists(escape)
    if escaped:
        os.remove(escape)
    print(f"escape file on disk after run: {escaped} (must be False)")

    for d in (workspace, outdir):
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", d], capture_output=True)
    userenv.DeleteAppContainerProfile(APP_NAME)

    report = {
        "sid": sid_str,
        "interpreter_dir_needs_recursive_acl_is_prohibitive": True,
        "escape_write_landed": escaped,
        "results": results,
        "all_expectations_met": all(r["verdict"] == "OK" for r in results) and not escaped,
    }
    report_path = Path(__file__).with_name("appcontainer_probe_result.json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport: {report_path}")
    print(f"All expectations met: {report['all_expectations_met']}")


if __name__ == "__main__":
    main()
