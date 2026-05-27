from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.workspace_registry import WorkspaceRegistry
from asteria_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_workspace_registry_records_recent_and_current_workspace(tmp_path: Path) -> None:
    global_dir = tmp_path / "home" / ".asteria"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = WorkspaceRegistry(global_dir, SchemaValidator(SCHEMA_DIR))

    data = registry.record_workspace(workspace_root=workspace, name="demo")

    assert data["current_workspace_root"] == str(workspace.resolve())
    assert data["recent_workspaces"][0]["name"] == "demo"
    assert data["recent_workspaces"][0]["workspace_root"] == str(workspace.resolve())
    assert data["recent_workspaces"][0]["artifact_root"] == str(
        (workspace / ".asteria" / "artifacts").resolve()
    )
    assert registry.path == global_dir / "workspaces.json"
    assert registry.path.exists()


def test_init_updates_global_workspace_registry_without_runtime_evidence(
    tmp_path: Path,
) -> None:
    global_dir = tmp_path / "home" / ".asteria"
    workspace = tmp_path / "project"

    InitCommand(workspace, global_config_dir=global_dir).run()

    data = WorkspaceRegistry(global_dir, SchemaValidator(SCHEMA_DIR)).read()
    assert data["current_workspace_root"] == str(workspace.resolve())
    assert data["recent_workspaces"][0]["output_root"] == str(workspace.resolve())
    assert not (global_dir / "runs").exists()
    assert not (global_dir / "current_session.json").exists()
