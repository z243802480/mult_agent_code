import json
from pathlib import Path

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.storage.schema_validator import SchemaValidator


def test_init_creates_agent_workspace(tmp_path: Path) -> None:
    result = InitCommand(tmp_path).run()

    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".agent" / "project.json").exists()
    assert (tmp_path / ".agent" / "policies.json").exists()
    assert (tmp_path / ".agent" / "context" / "root_snapshot.json").exists()
    assert (tmp_path / ".agent" / "tasks" / "backlog.json").exists()
    assert "AGENTS.md" in result.created

    validator = SchemaValidator(Path("schemas"))
    validator.validate("project_config", json.loads((tmp_path / ".agent" / "project.json").read_text()))
    validator.validate("policy_config", json.loads((tmp_path / ".agent" / "policies.json").read_text()))
    validator.validate(
        "context_snapshot",
        json.loads((tmp_path / ".agent" / "context" / "root_snapshot.json").read_text()),
    )
    validator.validate("task_board", json.loads((tmp_path / ".agent" / "tasks" / "backlog.json").read_text()))


def test_init_preserves_existing_agents_file(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("custom guidance", encoding="utf-8")

    result = InitCommand(tmp_path).run()

    assert agents.read_text(encoding="utf-8") == "custom guidance"
    assert "AGENTS.md" in result.preserved
