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

# NUL device access (ADR-0030 S-B-fix, changelog 1.2.139/1.2.140). An AppContainer token does NOT
# honour the World (Everyone) ACE the NUL device carries by default — git (opens /dev/null RDWR at
# startup) and pytest (FDCapture opens os.devnull RDWR) both fail with "Permission denied: 'nul'"
# until the NUL device DACL names ALL_APPLICATION_PACKAGES explicitly. `AC` is the SDDL alias for it.
_NUL_AC_ACE = "(A;;FA;;;AC)"
_nul_access_ensured = False  # process-scoped: NON-PERSISTENT (kernel recreates \Device\Null at boot)

# Win32 handle/DACL constants used by the NUL grant.
_READ_CONTROL = 0x00020000
_WRITE_DAC = 0x00040000
_FILE_SHARE_RW = 0x03
_OPEN_EXISTING = 3
_SE_KERNEL_OBJECT = 6
_DACL_SECURITY_INFORMATION = 0x00000004
_SDDL_REVISION_1 = 1

# Process-scoped caches. A warm worker is long-lived, so paying provisioning once per process is
# cheap in aggregate; a cold spawn pays it once. Persistent cross-process caching is a later
# optimisation (recorded as an honest edge in the changelog), not a correctness need.
_sid_cache: tuple[ctypes.c_void_p, str] | None = None
_granted_tool_dirs: set[str] = set()
_context_cache: dict[str, "SandboxContext"] = {}


def _nul_dacl_has_app_packages(dacl_sddl: str) -> bool:
    """Is an ALL_APPLICATION_PACKAGES allow ace already present in the NUL DACL? (idempotency check)
    ConvertSecurityDescriptorToStringSecurityDescriptor renders it either as the `AC` alias or the
    raw SID, so accept both."""
    return ";;AC)" in dacl_sddl or f";;{ALL_APPLICATION_PACKAGES_SID})" in dacl_sddl


def ensure_nul_device_access() -> str:
    """Idempotently add an ALL_APPLICATION_PACKAGES ace to the NUL device DACL so AppContainer'd
    git/pytest can open NUL (ADR-0030 S-B-fix). Best-effort by design: a failure here (e.g. not
    admin, so no WRITE_DAC on the device) degrades functionality — git/pytest break with their own
    errors, exactly the pre-fix state — but does NOT compromise the sandbox's confinement (network/
    write are the security guarantees, NUL is a bit-bucket), so it must not fail-close the whole
    sandbox. Non-persistent: the kernel recreates \\Device\\Null with the default DACL at every boot,
    so this is ensured once per PROCESS (not a durable operator step) — a reboot silently re-requires
    it and the next fresh process re-adds it. Returns a human status line; never raises."""
    global _nul_access_ensured
    if sys.platform != "win32" or _nul_access_ensured:
        return "already ensured" if _nul_access_ensured else "not applicable (non-Windows)"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    handle = kernel32.CreateFileW(
        r"\\.\NUL", _READ_CONTROL | _WRITE_DAC, _FILE_SHARE_RW, None, _OPEN_EXISTING, 0, None
    )
    if handle == wintypes.HANDLE(-1).value or not handle:
        return f"skipped: cannot open NUL for WRITE_DAC (GetLastError={ctypes.get_last_error()}; run as admin)"
    try:
        current = _read_kernel_object_dacl_sddl(advapi32, kernel32, handle)
        if current is None:
            return "skipped: could not read NUL DACL"
        if _nul_dacl_has_app_packages(current):
            _nul_access_ensured = True
            return "already granted"
        if _set_kernel_object_dacl_from_sddl(advapi32, kernel32, handle, current + _NUL_AC_ACE):
            _nul_access_ensured = True
            return "granted ALL_APPLICATION_PACKAGES on NUL device"
        return "skipped: SetSecurityInfo on NUL failed"
    finally:
        kernel32.CloseHandle(handle)


def _read_kernel_object_dacl_sddl(advapi32, kernel32, handle) -> str | None:
    psd = ctypes.c_void_p()
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    if advapi32.GetSecurityInfo(
        handle, _SE_KERNEL_OBJECT, _DACL_SECURITY_INFORMATION, None, None, None, None,
        ctypes.byref(psd),
    ) != 0:
        return None
    sddl = wintypes.LPWSTR()
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG),
    ]
    if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        psd, _SDDL_REVISION_1, _DACL_SECURITY_INFORMATION, ctypes.byref(sddl), None
    ):
        return None
    value = sddl.value or ""
    kernel32.LocalFree(sddl)
    return value


def _set_kernel_object_dacl_from_sddl(advapi32, kernel32, handle, dacl_sddl: str) -> bool:
    psd = ctypes.c_void_p()
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
    ]
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        dacl_sddl, _SDDL_REVISION_1, ctypes.byref(psd), None
    ):
        return False
    present = wintypes.BOOL()
    pdacl = ctypes.c_void_p()
    defaulted = wintypes.BOOL()
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL),
    ]
    if not advapi32.GetSecurityDescriptorDacl(
        psd, ctypes.byref(present), ctypes.byref(pdacl), ctypes.byref(defaulted)
    ):
        kernel32.LocalFree(psd)
        return False
    advapi32.SetSecurityInfo.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    rc = advapi32.SetSecurityInfo(
        handle, _SE_KERNEL_OBJECT, _DACL_SECURITY_INFORMATION, None, None, pdacl, None
    )
    kernel32.LocalFree(psd)
    return rc == 0


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
    # Ensure NUL device access here too so an operator `asteria sandbox provision` warms it (though it
    # is also auto-ensured per-process in ensure_sandbox, since the kernel resets it at boot).
    nul_status = ensure_nul_device_access()
    if toolchain_ready(target):
        _granted_tool_dirs.add(target)
        return f"already provisioned: {target}; NUL: {nul_status}"
    _icacls_grant(target, f"*{ALL_APPLICATION_PACKAGES_SID}:(OI)(CI)(RX)")
    _granted_tool_dirs.add(target)
    return f"provisioned (granted ALL_APPLICATION_PACKAGES read/exec): {target}; NUL: {nul_status}"


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

    # ADR-0030 S-B-fix: ensure the container can open NUL (git/pytest need it). Best-effort +
    # process-cached: it does not raise, because a NUL-grant failure only degrades git/pytest, never
    # the network/write confinement. Ensured HERE (not in the explicit provision step) because the
    # kernel resets \Device\Null's DACL at boot — this re-adds the ace once per fresh process.
    ensure_nul_device_access()

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
