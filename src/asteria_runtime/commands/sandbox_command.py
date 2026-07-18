"""`asteria sandbox` — maintainer preflight for the ADR-0030 S-B AppContainer sandbox.

Two actions:
  * `status`  — is the sandbox supported here, and is the toolchain already provisioned? (fast)
  * `provision` — the one-time, slow, explicit grant of ALL_APPLICATION_PACKAGES read/exec on the
    interpreter dir so an AppContainer can launch it. Kept out of the per-command hot path on
    purpose (a recursive icacls over site-packages takes minutes); the operator runs it once.
"""

from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core import sandbox_provision


@dataclass
class SandboxResult:
    action: str
    supported: bool
    toolchain_ready: bool
    message: str

    def to_text(self) -> str:
        lines = [
            f"sandbox: {'supported' if self.supported else 'not supported on this platform'}",
            f"toolchain provisioned: {self.toolchain_ready}",
            self.message,
        ]
        return "\n".join(lines)


class SandboxCommand:
    def __init__(self, action: str = "status") -> None:
        self.action = action

    def run(self) -> SandboxResult:
        supported = sandbox_provision.sandbox_supported()
        if not supported:
            return SandboxResult(
                self.action,
                False,
                False,
                "The AppContainer sandbox (ADR-0030 S-B) is Windows-only.",
            )
        if self.action == "provision":
            try:
                message = sandbox_provision.provision_toolchain()
            except sandbox_provision.SandboxUnavailable as exc:
                return SandboxResult(self.action, True, False, f"provision failed: {exc}")
            return SandboxResult(self.action, True, True, message)
        ready = sandbox_provision.toolchain_ready()
        hint = "" if ready else " — run `asteria sandbox provision` once to enable sandbox_shell"
        return SandboxResult(self.action, True, ready, f"ready to sandbox: {ready}{hint}")
