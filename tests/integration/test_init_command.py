import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_init_creates_agent_workspace(tmp_path: Path) -> None:
    result = InitCommand(tmp_path).run()

    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".asteria" / "project.json").exists()
    assert (tmp_path / ".asteria" / "policies.json").exists()
    assert (tmp_path / ".asteria" / "context" / "root_snapshot.json").exists()
    assert (tmp_path / ".asteria" / "tasks" / "backlog.json").exists()
    assert "AGENTS.md" in result.created

    validator = SchemaValidator(Path("schemas"))
    validator.validate(
        "project_config", json.loads((tmp_path / ".asteria" / "project.json").read_text())
    )
    validator.validate(
        "policy_config", json.loads((tmp_path / ".asteria" / "policies.json").read_text())
    )
    validator.validate(
        "context_snapshot",
        json.loads((tmp_path / ".asteria" / "context" / "root_snapshot.json").read_text()),
    )
    validator.validate(
        "task_board", json.loads((tmp_path / ".asteria" / "tasks" / "backlog.json").read_text())
    )


def test_init_preserves_existing_agents_file(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("custom guidance", encoding="utf-8")

    result = InitCommand(tmp_path).run()

    assert agents.read_text(encoding="utf-8") == "custom guidance"
    assert "AGENTS.md" in result.preserved


def test_init_migrates_legacy_agent_state_to_asteria(tmp_path: Path) -> None:
    legacy_dir = tmp_path / ".agent"
    (legacy_dir / "context").mkdir(parents=True)
    (legacy_dir / "context" / "root_snapshot.json").write_text("{}", encoding="utf-8")

    result = InitCommand(tmp_path).run()

    assert (tmp_path / ".asteria" / "context" / "root_snapshot.json").exists()
    assert any("Migrated legacy .agent/" in warning for warning in result.warnings)


def test_init_reinit_preserves_user_edited_managed_files(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    policies_path = tmp_path / ".asteria" / "policies.json"
    edited = json.loads(policies_path.read_text(encoding="utf-8"))
    edited["_user_marker"] = "keep-me"
    policies_path.write_text(json.dumps(edited), encoding="utf-8")

    result = InitCommand(tmp_path).run()

    reloaded = json.loads(policies_path.read_text(encoding="utf-8"))
    assert reloaded.get("_user_marker") == "keep-me"
    assert any("policies.json" in rel for rel in result.preserved)


def test_init_force_regenerates_managed_files(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    policies_path = tmp_path / ".asteria" / "policies.json"
    edited = json.loads(policies_path.read_text(encoding="utf-8"))
    edited["_user_marker"] = "overwrite-me"
    policies_path.write_text(json.dumps(edited), encoding="utf-8")

    result = InitCommand(tmp_path, force=True).run()

    reloaded = json.loads(policies_path.read_text(encoding="utf-8"))
    assert "_user_marker" not in reloaded
    assert any("policies.json" in rel for rel in result.updated)
