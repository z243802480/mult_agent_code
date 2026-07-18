"""Sandbox provisioning (ADR-0030 S-B): everything that must be true BEFORE a command can run in an
AppContainer — the profile exists, the toolchain is readable, the workspace is writable to the
container SID, and there is a granted directory to capture output into.

Split from sandbox_launch so the expensive, cacheable setup (creating the profile, `icacls`-granting
directories) is not repeated per command. The spike's key finding drives the design: granting a
per-container ACL over a big user-profile interpreter tree is prohibitively slow, so the toolchain
dir is granted ALL_APPLICATION_PACKAGES read/exec ONCE per process (cached), and each workspace is
granted the container SID ONCE (cached) — the first sandboxed command in a fresh process pays that
cost, the rest are free.

Everything here raises SandboxUnavailable on failure. That is deliberate: a sandbox that could not
be provisioned must fail the command (fail-closed), never silently run unsandboxed.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from dataclasses import dataclass


class SandboxUnavailable(RuntimeError):
    """A sandbox was required but could not be built. Callers must fail the command, not run it."""


# Well-known: every AppContainer implicitly has read/exec where this SID is granted. Granting it to
# the toolchain dir is what lets an AppContainer launch our Python/Git without a per-container ACL.
ALL_APPLICATION_PACKAGES_SID = "S-1-15-2-1"
_PROFILE_NAME = "asteria.runtime.sandbox"
_ERROR_ALREADY_EXISTS = 183

# Process-scoped caches. A warm worker is long-lived, so paying provisioning once per process is
# cheap in aggregate; a cold spawn pays it once. Persistent cross-process caching is a later
# optimisation (recorded as an honest edge in the changelog), not a correctness need.
_sid_cache: tuple[ctypes.c_void_p, str] | None = None
_granted_tool_dirs: set[str] = set()
_context_cache: dict[str, "SandboxContext"] = {}


@dataclass
class SandboxContext:
    sid_pointer: ctypes.c_void_p
    sid_str: str
    io_dir: str  # granted (inheritable) dir; launch writes per-command stdout/stderr under it


def _win_last_error(context: str) -> SandboxUnavailable:
    return SandboxUnavailable(f"{context} failed (GetLastError={ctypes.get_last_error()})")


def _ensure_profile() -> tuple[ctypes.c_void_p, str]:
    global _sid_cache
    if _sid_cache is not None:
        return _sid_cache
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    sid = ctypes.c_void_p()
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    hr = userenv.CreateAppContainerProfile(
        _PROFILE_NAME, _PROFILE_NAME, "asteria runtime shell sandbox", None, 0, ctypes.byref(sid)
    )
    if hr < 0:
        if (hr & 0xFFFF) == _ERROR_ALREADY_EXISTS:
            userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
            if (
                userenv.DeriveAppContainerSidFromAppContainerName(_PROFILE_NAME, ctypes.byref(sid))
                < 0
            ):
                raise SandboxUnavailable("DeriveAppContainerSidFromAppContainerName failed")
        else:
            raise SandboxUnavailable(
                f"CreateAppContainerProfile failed (HRESULT={hr & 0xFFFFFFFF:#010x})"
            )

    out = wintypes.LPWSTR()
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(out)):
        raise _win_last_error("ConvertSidToStringSidW")
    sid_str = out.value or ""
    kernel32.LocalFree(out)
    _sid_cache = (sid, sid_str)
    return _sid_cache


def _icacls_grant(path: str, spec: str) -> None:
    result = subprocess.run(
        ["icacls", path, "/grant", spec, "/T", "/C", "/Q"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise SandboxUnavailable(
            f"icacls grant on {path} failed ({result.returncode}): {result.stderr.strip()[:200]}"
        )


def toolchain_ready(tool_dir: str | None = None) -> bool:
    """Fast probe (single-file icacls query): does the interpreter dir already carry the
    ALL_APPLICATION_PACKAGES ACL an AppContainer needs to launch it? Cheap enough for the hot path,
    unlike the recursive grant that sets it."""
    if sys.platform != "win32":
        return False
    exe = os.path.join(tool_dir, "python.exe") if tool_dir else sys.executable
    try:
        result = subprocess.run(["icacls", exe], capture_output=True, text=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return False
    text = result.stdout
    return ALL_APPLICATION_PACKAGES_SID in text or "APPLICATION PACKAGES" in text


def provision_toolchain(tool_dir: str | None = None) -> str:
    """One-time, EXPLICIT setup: grant the interpreter dir ALL_APPLICATION_PACKAGES read/exec so an
    AppContainer can launch it. This is the slow, persistent step the spike flagged — a recursive
    `icacls /T` over site-packages takes minutes — so it is kept OUT of the per-command hot path and
    made an operator action (`asteria sandbox provision`). Idempotent: skips if already granted.

    Returns a human status line. Raises SandboxUnavailable if the grant fails."""
    if sys.platform != "win32":
        raise SandboxUnavailable("AppContainer sandbox is Windows-only")
    target = tool_dir or os.path.dirname(sys.executable)
    if toolchain_ready(target):
        _granted_tool_dirs.add(target)
        return f"already provisioned: {target}"
    _icacls_grant(target, f"*{ALL_APPLICATION_PACKAGES_SID}:(OI)(CI)(RX)")
    _granted_tool_dirs.add(target)
    return f"provisioned (granted ALL_APPLICATION_PACKAGES read/exec): {target}"


def ensure_sandbox(workspace: str) -> SandboxContext:
    """Provision (idempotently) and return a ready SandboxContext for `workspace`. Raises
    SandboxUnavailable on any failure — the caller must then fail the command, not run it unsandboxed.

    Does NOT grant the toolchain (that is the explicit, slow provision_toolchain step); it verifies
    readiness cheaply and fails-closed with a fix hint if the toolchain was never provisioned. The
    per-workspace + io grants ARE done here (and cached), because they are the confinement itself.
    launch mkdtemp's a per-command subdir under io_dir, inheriting the container ACL, so concurrent
    commands never share output files."""
    if sys.platform != "win32":
        raise SandboxUnavailable("AppContainer sandbox is Windows-only")

    if not toolchain_ready():
        raise SandboxUnavailable(
            "sandbox toolchain not provisioned — run `asteria sandbox provision` once to grant the "
            f"interpreter dir ({os.path.dirname(sys.executable)}) AppContainer read access"
        )

    key = os.path.normcase(os.path.abspath(workspace))
    cached = _context_cache.get(key)
    if cached is not None:
        return cached

    sid, sid_str = _ensure_profile()
    _icacls_grant(workspace, f"*{sid_str}:(OI)(CI)(F)")

    io_dir = tempfile.mkdtemp(prefix="asteria-sbx-io-")
    _icacls_grant(io_dir, f"*{sid_str}:(OI)(CI)(F)")
    ctx = SandboxContext(sid_pointer=sid, sid_str=sid_str, io_dir=io_dir)
    _context_cache[key] = ctx
    return ctx


def sandbox_supported() -> bool:
    """Cheap capability probe: can this platform even attempt a sandbox? (Does not provision.)"""
    return sys.platform == "win32"
