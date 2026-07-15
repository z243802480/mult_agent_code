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


def test_studio_command_skips_install_when_node_modules_present(tmp_path, monkeypatch) -> None:
    """node_modules 存在时必须真的跳过安装。原测试零断言、且靠真实 studio 目录双早退空转——在任何
    没有 node_modules 的环境(含 CI)里彻底 no-op,改一行安装逻辑都不会让它变红。"""
    studio_dir = tmp_path / "studio"
    (studio_dir / "node_modules").mkdir(parents=True)
    calls: list = []
    monkeypatch.setattr(
        "asteria_runtime.commands.studio_command.subprocess.run",
        lambda *a, **k: calls.append(a),
    )
    command = StudioCommand(tmp_path, studio_dir=studio_dir, skip_install=False)
    command._ensure_node_modules()
    assert calls == [], "node_modules 已存在时不应发起 npm install"


def test_studio_command_build_previews_single_port(tmp_path: Path) -> None:
    """--build 意图 = 会产出 dist → 单口托管(UI+API 同 URL·无 dev server)。preview 必须在真正
    构建前就如实反映这一点(供 --json 用),即使当前还没有 dist/index.html。"""
    fake_studio = tmp_path / "studio"
    fake_studio.mkdir()
    (fake_studio / "server.mjs").write_text("// stub", encoding="utf-8")
    # 故意不建 dist —— 靠 build 意图而非现存 dist 判定单口
    preview = StudioCommand(
        tmp_path, studio_dir=fake_studio, skip_install=True, build=True
    ).preview()
    assert preview.api_url == preview.ui_url, "build 后 UI 由 API 服务器同口托管"
    assert preview.backend_only is True, "单口模式不起 vite dev server"


def test_studio_command_build_ui_invokes_npm_build(tmp_path, monkeypatch) -> None:
    """--build 必须真的发起一次 `npm run build`(否则单口托管没有 dist 可服务)。"""
    studio_dir = tmp_path / "studio"
    studio_dir.mkdir(parents=True)
    calls: list = []
    monkeypatch.setattr(
        "asteria_runtime.commands.studio_command.shutil.which", lambda _name: "npm"
    )
    monkeypatch.setattr(
        "asteria_runtime.commands.studio_command.subprocess.run",
        lambda *a, **k: calls.append(a[0]),
    )
    command = StudioCommand(tmp_path, studio_dir=studio_dir, skip_install=True, build=True)
    command._build_ui()
    assert calls == [["npm", "run", "build"]], "应发起一次 npm run build"


def test_studio_command_installs_when_node_modules_missing(tmp_path, monkeypatch) -> None:
    """反向:node_modules 缺失时必须发起一次 npm install(锁死上一条不是因为压根没跑安装路径)。"""
    studio_dir = tmp_path / "studio"
    studio_dir.mkdir(parents=True)  # 没有 node_modules
    calls: list = []
    monkeypatch.setattr(
        "asteria_runtime.commands.studio_command.shutil.which", lambda _name: "npm"
    )
    monkeypatch.setattr(
        "asteria_runtime.commands.studio_command.subprocess.run",
        lambda *a, **k: calls.append(a),
    )
    command = StudioCommand(tmp_path, studio_dir=studio_dir, skip_install=False)
    command._ensure_node_modules()
    assert len(calls) == 1, "node_modules 缺失时应发起一次 npm install"
