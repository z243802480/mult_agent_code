from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.workspaces_command import WorkspacesCommand, resolve_studio_launch_root


def test_workspaces_register_initializes_missing_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    global_dir = tmp_path / "global"
    command = WorkspacesCommand(global_config_dir=global_dir)
    result = command.register(workspace)
    assert result.ok is True
    assert result.initialized is True
    assert (workspace / ".asteria" / "project.json").exists()
    registry = command.list_registry().registry or {}
    assert registry.get("current_workspace_root") == str(workspace.resolve())


def test_workspaces_register_existing_workspace_without_reinit(tmp_path: Path) -> None:
    workspace = tmp_path / "existing"
    workspace.mkdir()
    agent_dir = workspace / ".asteria"
    agent_dir.mkdir()
    project_path = agent_dir / "project.json"
    project_path.write_text('{"schema_version":"0.1.0","project_name":"keep-me"}', encoding="utf-8")
    global_dir = tmp_path / "global"
    command = WorkspacesCommand(global_config_dir=global_dir)
    result = command.register(workspace)
    assert result.ok is True
    assert result.initialized is False
    assert "keep-me" in project_path.read_text(encoding="utf-8")


def test_workspaces_list_returns_registry(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    workspace = tmp_path / "one"
    workspace.mkdir()
    command = WorkspacesCommand(global_config_dir=global_dir)
    command.register(workspace)
    listed = command.list_registry()
    assert listed.ok is True
    recent = (listed.registry or {}).get("recent_workspaces") or []
    assert recent[0]["workspace_root"] == str(workspace.resolve())


def test_workspaces_describe_reports_project_signals(tmp_path: Path) -> None:
    workspace = tmp_path / "demo"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("# Demo", encoding="utf-8")
    command = WorkspacesCommand()
    described = command.describe(workspace)
    assert described.ok is True
    profile = described.profile or {}
    assert profile.get("has_agents_md") is True
    assert profile.get("initialized") is False


def test_resolve_studio_launch_root_uses_remembered_workspace(tmp_path: Path, monkeypatch) -> None:
    launch_cwd = tmp_path / "repo"
    launch_cwd.mkdir()
    remembered = tmp_path / "project"
    remembered.mkdir()
    global_dir = tmp_path / "global"
    WorkspacesCommand(global_config_dir=global_dir).register(remembered)
    monkeypatch.chdir(launch_cwd)
    resolved = resolve_studio_launch_root(Path("."), global_config_dir=global_dir)
    assert resolved == remembered.resolve()
