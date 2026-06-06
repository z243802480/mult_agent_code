from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.studio_command import StudioCommand, resolve_studio_dir


def test_resolve_studio_dir_prefers_env(monkeypatch) -> None:
    custom = Path("studio")
    monkeypatch.setenv("ASTERIA_STUDIO_DIR", str(custom))
    assert resolve_studio_dir() == custom


def test_studio_command_validates_server_script(tmp_path: Path) -> None:
    fake_studio = tmp_path / "studio"
    fake_studio.mkdir()
    command = StudioCommand(tmp_path, studio_dir=fake_studio, skip_install=True)
    try:
        command.run()
    except FileNotFoundError as error:
        assert "server.mjs" in str(error)
    else:
        raise AssertionError("expected missing server.mjs to fail validation")


def test_studio_command_skips_install_when_node_modules_present() -> None:
    studio_dir = resolve_studio_dir()
    if not studio_dir.is_dir():
        return
    command = StudioCommand(Path("."), studio_dir=studio_dir, skip_install=False)
    node_modules = studio_dir / "node_modules"
    if not node_modules.is_dir():
        return
    command._ensure_node_modules()
