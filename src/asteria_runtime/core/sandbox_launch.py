"""Sandboxed shell launch (ADR-0030 S-B): run the model's command inside a Windows AppContainer
so network egress and out-of-workspace writes are refused by the OS, not by a static denylist.

The spike (scripts/spikes/appcontainer_probe.py, changelog 1.2.119) proved the principle: a command
in an AppContainer with no `internetClient` capability cannot reach a socket, and cannot write
outside the ACLs it was granted. This module is that mechanism made production: capability gated on
`allow_network`, stdout/stderr captured to separate files, a bounded wait, and — layered on top —
the S-A Job Object so a detached child inside the sandbox is still reaped when the run ends.

Fail-closed on purpose (unlike the S-A fence, which degrades silently): if the caller ASKED for a
sandbox and one cannot be built, that is a refusal, not a fall-through to an unsandboxed run — the
whole point is that "network is off" is an OS guarantee, and silently running unsandboxed would make
that guarantee a lie. The caller (command_tools) turns a SandboxUnavailable into a failed command.

Windows only; callers must gate on sys.platform before importing behaviour that assumes it.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

from asteria_runtime.core.sandbox_provision import SandboxContext, SandboxUnavailable

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
WAIT_TIMEOUT = 0x102
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
CREATE_ALWAYS = 2
SE_GROUP_ENABLED = 0x00000004
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
_MAX_ACTIVE_PROCESSES = 512
_MAX_PROCESS_MEMORY_BYTES = 4 * 1024 * 1024 * 1024

# The well-known capability SID for outbound internet access. Present ⇒ the AppContainer may open
# sockets; absent ⇒ WFP refuses egress at the OS layer (this is the whole mechanism).
INTERNET_CLIENT_SID = "S-1-15-3-1"


if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class _SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [
            ("AppContainerSid", ctypes.c_void_p),
            ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
            ("CapabilityCount", wintypes.DWORD),
            ("Reserved", wintypes.DWORD),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class _SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rt", "wt", "ot")]

    class _JOB_BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOB_EXTENDED(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOB_BASIC),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


def _string_sid_to_pointer(sid_str: str) -> ctypes.c_void_p:
    psid = ctypes.c_void_p()
    _advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    if not _advapi32.ConvertStringSidToSidW(sid_str, ctypes.byref(psid)):
        raise SandboxUnavailable(
            f"ConvertStringSidToSidW({sid_str}) failed (GetLastError={ctypes.get_last_error()})"
        )
    return psid


def _make_job() -> wintypes.HANDLE:
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise SandboxUnavailable("CreateJobObjectW failed")
    info = _JOB_EXTENDED()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
    )
    info.BasicLimitInformation.ActiveProcessLimit = _MAX_ACTIVE_PROCESSES
    info.ProcessMemoryLimit = _MAX_PROCESS_MEMORY_BYTES
    _kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    )
    return job


def _inheritable_write_handle(path: str) -> wintypes.HANDLE:
    sec = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    h = _kernel32.CreateFileW(
        path,
        GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        ctypes.byref(sec),
        CREATE_ALWAYS,
        0,
        None,
    )
    if h == wintypes.HANDLE(-1).value:
        raise SandboxUnavailable(
            f"CreateFileW({path}) failed (GetLastError={ctypes.get_last_error()})"
        )
    return h


def run_sandboxed(
    ctx: SandboxContext,
    command: str,
    *,
    cwd: str,
    env: dict[str, str],
    timeout: int,
    allow_network: bool,
) -> subprocess.CompletedProcess[str]:
    """Run `command` (a shell string) inside the AppContainer described by `ctx`. Returns a
    CompletedProcess. Raises SandboxUnavailable if the sandbox cannot be built (caller fails the
    command), and subprocess.TimeoutExpired with captured output on timeout — same contract as
    run_fenced so command_tools handles both identically."""
    if sys.platform != "win32":
        raise SandboxUnavailable("AppContainer sandbox is Windows-only")

    # Per-command subdir under the granted io root (inherits the container ACL), so concurrent
    # commands never collide on stdout/stderr. Cleaned up after the output is read.
    call_dir = tempfile.mkdtemp(dir=ctx.io_dir)
    out_path = str(Path(call_dir) / "stdout.txt")
    err_path = str(Path(call_dir) / "stderr.txt")
    hout = _inheritable_write_handle(out_path)
    herr = _inheritable_write_handle(err_path)
    job = _make_job()

    # Attribute list: one attribute (security capabilities).
    size = ctypes.c_size_t(0)
    _kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attr_buf = (ctypes.c_byte * size.value)()
    if not _kernel32.InitializeProcThreadAttributeList(attr_buf, 1, 0, ctypes.byref(size)):
        raise SandboxUnavailable("InitializeProcThreadAttributeList failed")

    # allow_network wires the internetClient capability at launch. HONEST LIMITATION (verified, not
    # assumed): for a bare CreateAppContainerProfile container (not a full APPX package) the
    # launch-time capability does NOT reach the token — probed `whoami /groups` shows S-1-15-3-1
    # absent and egress stays blocked even with allow_network=True. Making the escape hatch work
    # needs the container registered with a Windows Firewall rule (operator/admin setup), a
    # documented S-B follow-up. The SECURITY-CRITICAL direction — default-deny — IS proven (blocks
    # against a net-connected machine). So today the sandbox means "network OFF, writes confined";
    # a workflow that genuinely needs network must not enable the sandbox yet. Fails CLOSED.
    cap_array = None
    caps = _SECURITY_CAPABILITIES(ctx.sid_pointer, None, 0, 0)
    if allow_network:
        internet = _string_sid_to_pointer(INTERNET_CLIENT_SID)
        cap_array = (_SID_AND_ATTRIBUTES * 1)(_SID_AND_ATTRIBUTES(internet, SE_GROUP_ENABLED))
        caps.Capabilities = ctypes.cast(cap_array, ctypes.POINTER(_SID_AND_ATTRIBUTES))
        caps.CapabilityCount = 1
    if not _kernel32.UpdateProcThreadAttribute(
        attr_buf,
        0,
        PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        ctypes.byref(caps),
        ctypes.sizeof(caps),
        None,
        None,
    ):
        raise SandboxUnavailable("UpdateProcThreadAttribute failed")

    si = _STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
    si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    si.StartupInfo.hStdOutput = hout
    si.StartupInfo.hStdError = herr
    si.lpAttributeList = ctypes.cast(attr_buf, ctypes.c_void_p)

    # shell=True equivalent: cmd.exe /c "<command>". cmd.exe is in System32, readable by every
    # AppContainer via ALL_APPLICATION_PACKAGES, so it always launches; the tools it then invokes
    # must live where sandbox_provision granted read/exec.
    comspec = str(Path(env.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe")
    cmdline = subprocess.list2cmdline([comspec, "/c", command])

    pi = _PROCESS_INFORMATION()
    ok = _kernel32.CreateProcessW(
        None,
        cmdline,
        None,
        None,
        True,
        EXTENDED_STARTUPINFO_PRESENT,
        None,
        cwd,
        ctypes.byref(si),
        ctypes.byref(pi),
    )
    if not ok:
        err = ctypes.get_last_error()
        for h in (hout, herr, job):
            _kernel32.CloseHandle(h)
        _kernel32.DeleteProcThreadAttributeList(attr_buf)
        raise SandboxUnavailable(f"CreateProcessW-in-AppContainer failed (GetLastError={err})")

    _kernel32.AssignProcessToJobObject(job, pi.hProcess)

    timed_out = False
    wait = _kernel32.WaitForSingleObject(pi.hProcess, timeout * 1000)
    if wait == WAIT_TIMEOUT:
        timed_out = True
        _kernel32.TerminateProcess(pi.hProcess, 0xDEAD)
        _kernel32.WaitForSingleObject(pi.hProcess, 2000)
    code_dw = wintypes.DWORD()
    _kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code_dw))
    returncode = code_dw.value

    for h in (pi.hProcess, pi.hThread, hout, herr):
        _kernel32.CloseHandle(h)
    _kernel32.DeleteProcThreadAttributeList(attr_buf)
    _kernel32.CloseHandle(job)  # KILL_ON_JOB_CLOSE reaps any survivor in the sandbox tree

    stdout = Path(out_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(err_path).read_text(encoding="utf-8", errors="replace")
    shutil.rmtree(call_dir, ignore_errors=True)
    if timed_out:
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)
