"""ADR-0030 S-B: the sandbox wiring is fail-closed (a required sandbox that can't be built fails the
command, never runs it unsandboxed), and — on Windows — a real AppContainer denies network egress
and confines writes to the workspace at the OS layer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from asteria_runtime.core import sandbox_provision
from asteria_runtime.tools import command_tools
from asteria_runtime.tools.command_tools import RunCommandTool

_PERMS = {
    "allow_network": False,
    "allow_shell": True,
    "allow_destructive_shell": False,
    "allow_global_package_install": False,
    "allow_secret_file_read": False,
    "allow_remote_push": False,
    "allow_deploy": False,
    "allow_restore_delete_created_files": True,
}


def _ctx(root: Path, **perm_overrides: object) -> SimpleNamespace:
    perms = dict(_PERMS)
    perms.update(perm_overrides)
    return SimpleNamespace(root=root, policy={"permissions": perms, "protected_paths": []})


def test_sandbox_off_uses_the_fence_not_the_sandbox(tmp_path: Path, monkeypatch) -> None:
    calls = {"fenced": 0, "sandboxed": 0}
    monkeypatch.setattr(
        command_tools,
        "run_fenced",
        lambda *a, **k: (
            calls.__setitem__("fenced", calls["fenced"] + 1)
            or subprocess.CompletedProcess("x", 0, "ok", "")
        ),
    )
    monkeypatch.setattr(
        command_tools,
        "run_sandboxed",
        lambda *a, **k: calls.__setitem__("sandboxed", calls["sandboxed"] + 1),
    )
    result = RunCommandTool().run(_ctx(tmp_path, sandbox_shell=False), "echo hi")
    assert result.ok
    assert calls == {"fenced": 1, "sandboxed": 0}


def test_sandbox_required_but_unsupported_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_tools, "sandbox_supported", lambda: False)

    def boom(*a: object, **k: object) -> None:
        pytest.fail("must not run the command when the sandbox is unavailable")

    monkeypatch.setattr(command_tools, "run_fenced", boom)
    monkeypatch.setattr(command_tools, "run_sandboxed", boom)
    result = RunCommandTool().run(_ctx(tmp_path, sandbox_shell=True), "echo hi")
    assert not result.ok
    assert result.error == "sandbox_unavailable"


def test_sandbox_provision_failure_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_tools, "sandbox_supported", lambda: True)

    def _raise(_ws: str):
        raise sandbox_provision.SandboxUnavailable("toolchain not provisioned")

    monkeypatch.setattr(command_tools, "ensure_sandbox", _raise)
    monkeypatch.setattr(
        command_tools,
        "run_sandboxed",
        lambda *a, **k: pytest.fail("must not run when provision failed"),
    )
    result = RunCommandTool().run(_ctx(tmp_path, sandbox_shell=True), "echo hi")
    assert not result.ok
    assert result.error == "sandbox_unavailable"
    assert "toolchain not provisioned" in result.data["reason"]


def test_sandbox_on_routes_through_appcontainer_and_passes_allow_network(
    tmp_path: Path, monkeypatch
) -> None:
    seen = {}
    monkeypatch.setattr(command_tools, "sandbox_supported", lambda: True)
    monkeypatch.setattr(command_tools, "ensure_sandbox", lambda ws: SimpleNamespace(io_dir="x"))
    monkeypatch.setattr(
        command_tools,
        "run_fenced",
        lambda *a, **k: pytest.fail("sandbox on must not use the fence"),
    )

    def _sandboxed(ctx, command, *, cwd, env, timeout, allow_network):
        seen["allow_network"] = allow_network
        return subprocess.CompletedProcess(command, 0, "done", "")

    monkeypatch.setattr(command_tools, "run_sandboxed", _sandboxed)
    result = RunCommandTool().run(_ctx(tmp_path, sandbox_shell=True, allow_network=True), "echo hi")
    assert result.ok
    assert seen["allow_network"] is True


def test_toolchain_ready_parses_icacls(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        sandbox_provision.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess("x", 0, "APPLICATION PACKAGES:(RX)\n", ""),
    )
    assert sandbox_provision.toolchain_ready("C:\\fake") is True
    monkeypatch.setattr(
        sandbox_provision.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess("x", 0, "BUILTIN\\Users:(RX)\n", ""),
    )
    assert sandbox_provision.toolchain_ready("C:\\fake") is False


# --- Windows-only real integration: the mechanism itself ------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows-only")
def test_real_sandbox_denies_network_and_confines_writes(tmp_path: Path) -> None:
    import os

    if not sandbox_provision.toolchain_ready():
        pytest.skip("sandbox toolchain not provisioned (run `asteria sandbox provision`)")

    from asteria_runtime.core.sandbox_launch import run_sandboxed

    ctx = sandbox_provision.ensure_sandbox(str(tmp_path))
    env = dict(os.environ)
    sys32 = os.path.join(os.environ["SystemRoot"], "System32")
    curl = os.path.join(sys32, "curl.exe")

    # Network egress denied at the OS layer (default-deny is the security-critical guarantee).
    net = run_sandboxed(
        ctx,
        f'"{curl}" -s -o out.html --max-time 8 http://example.com',
        cwd=str(tmp_path),
        env=env,
        timeout=30,
        allow_network=False,
    )
    downloaded = (tmp_path / "out.html").stat().st_size if (tmp_path / "out.html").exists() else 0
    assert net.returncode != 0 and downloaded == 0, "network egress was NOT blocked"

    # Write inside the workspace works; write outside is refused and does not land.
    inside = run_sandboxed(
        ctx,
        "cmd /c echo x> inside.txt",
        cwd=str(tmp_path),
        env=env,
        timeout=30,
        allow_network=False,
    )
    assert inside.returncode == 0 and (tmp_path / "inside.txt").exists()

    escape = Path(os.environ["SystemRoot"]) / "asteria_sbx_test_escape.txt"
    if escape.exists():
        escape.unlink()
    out = run_sandboxed(
        ctx, f"cmd /c echo x> {escape}", cwd=str(tmp_path), env=env, timeout=30, allow_network=False
    )
    escaped = escape.exists()
    if escaped:
        escape.unlink()
    assert out.returncode != 0 and not escaped, "write escaped the workspace"
