from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.studio_command import StudioCommand, _installed_studio_dir, resolve_studio_dir


def test_resolve_studio_dir_prefers_env(monkeypatch) -> None:
    custom = Path("studio")
    monkeypatch.setenv("ASTERIA_STUDIO_DIR", str(custom))
    assert resolve_studio_dir() == custom.resolve()


def test_installed_studio_dir_reads_current_pointer(tmp_path: Path, monkeypatch) -> None:
    studio_home = tmp_path / ".asteria" / "studio"
    bundle = studio_home / "0.1.0"
    bundle.mkdir(parents=True)
    (bundle / "server.mjs").write_text("// stub", encoding="utf-8")
    (studio_home / "current").write_text(str(bundle), encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("ASTERIA_STUDIO_DIR", raising=False)
    resolved = _installed_studio_dir()
    assert resolved == bundle.resolve()


def test_studio_command_uses_bundled_ui_without_vite(tmp_path: Path) -> None:
    fake_studio = tmp_path / "studio"
    fake_studio.mkdir()
    (fake_studio / "server.mjs").write_text("// stub", encoding="utf-8")
    dist = fake_studio / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    preview = StudioCommand(tmp_path, studio_dir=fake_studio, skip_install=True).preview()
    assert preview.api_url == preview.ui_url
    assert preview.backend_only is True


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
