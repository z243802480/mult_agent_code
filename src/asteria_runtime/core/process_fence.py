"""Process fence (ADR-0030 S-A): run a shell command in an OS-enforced process group so the
WHOLE tree dies when the run ends, and a fork/memory bomb fails the command instead of the box.

This is a fence, not a sandbox — it does NOT touch network or filesystem (that is S-B). What it
buys, on top of today's `subprocess.run`, is one OS guarantee the static ShellGuard can never give:
"the run finished" now means "nothing it spawned is still alive." Today a `start /b`, a trailing
`&`, or any detached grandchild outlives the run; on Windows the Job Object's KILL_ON_JOB_CLOSE
reaps them the instant we close the job handle.

Degradation is deliberate and silent: if the OS cannot create/assign the job (unsupported platform,
nested-job denial), the command still runs — just unfenced. The fence is hardening, not a
correctness dependency, so a platform that can't provide it must not turn a legitimate command into
a failure. Windows is the primary target; the POSIX path (new session + process-group kill) is
weaker by nature — a double-forked daemon escapes a process group — and is best-effort.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

# Bomb-scale thresholds, NOT fine-grained quotas: real tools (pytest workers, npm, git, compilers)
# sit well under these; a fork bomb wants thousands of processes and a memory bomb wants all of RAM,
# both far above. Set generously on purpose — precise per-tool quotas are S-B's job (they need the
# compatibility spike's data), and a fence that misfires on a heavy-but-legitimate build is worse
# than no fence. Tune here if the spike shows a real tool crossing them.
_MAX_ACTIVE_PROCESSES = 512
_MAX_PROCESS_MEMORY_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB per process


def run_fenced(
    command: str,
    *,
    cwd: os.PathLike[str] | str,
    env: dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Drop-in for the guarded `subprocess.run(command, shell=True, capture_output=True, text=True)`
    on the model's command path, wrapped in a process fence. Raises subprocess.TimeoutExpired with
    captured output on timeout, exactly like subprocess.run."""
    if sys.platform == "win32":
        return _run_win32(command, cwd=cwd, env=env, timeout=timeout)
    return _run_posix(command, cwd=cwd, env=env, timeout=timeout)


def _plain_run(
    command: str, *, cwd: os.PathLike[str] | str, env: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _run_posix(
    command: str, *, cwd: os.PathLike[str] | str, env: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[str]:
    # start_new_session=True puts the child in its own process group (we are not in it), so the
    # kill below cannot hit the harness. Weaker than a Job Object: a double-forked daemon leaves
    # the group and survives — documented, and the reason Windows is the primary target.
    with subprocess.Popen(
        command,
        cwd=cwd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    ) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _killpg(proc.pid)
            stdout, stderr = proc.communicate()
            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
        finally:
            _killpg(proc.pid)  # reap any group stragglers left after normal exit
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _killpg(pid: int) -> None:
    try:
        # POSIX-only names; _run_posix is the only caller and never runs on Windows. The ignore is
        # for mypy checking under a win32 platform assumption, not a real attribute gap.
        os.killpg(os.getpgid(pid), signal.SIGKILL)  # type: ignore[attr-defined]
    except (ProcessLookupError, PermissionError, OSError):
        pass  # already gone / not our group — best effort


def _run_win32(
    command: str, *, cwd: os.PathLike[str] | str, env: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[str]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),  # ULONG_PTR
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return _plain_run(command, cwd=cwd, env=env, timeout=timeout)  # can't fence → run unfenced

    try:
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
        info.BasicLimitInformation.ActiveProcessLimit = _MAX_ACTIVE_PROCESSES
        info.ProcessMemoryLimit = _MAX_PROCESS_MEMORY_BYTES
        kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        )

        with subprocess.Popen(
            command,
            cwd=cwd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        ) as proc:
            # Assign right after spawn. cmd.exe must load, parse, and only then CreateProcess the
            # target, so this (a microsecond syscall) lands before any child does real work; the
            # default job forbids breakaway, so the whole tree is captured. If assign fails
            # (nested-job denial etc.) the command runs unfenced rather than failing — hardening,
            # not a gate.
            kernel32.AssignProcessToJobObject(job, int(proc._handle))  # type: ignore[attr-defined]
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    finally:
        # Closing the last handle to the job trips KILL_ON_JOB_CLOSE: any process still alive in
        # the tree — including a detached grandchild communicate() never waited for — is reaped now.
        kernel32.CloseHandle(job)
