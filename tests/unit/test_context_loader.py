from pathlib import Path

from agent_runtime.core.context_loader import ContextLoader
from agent_runtime.storage.schema_validator import SchemaValidator


def validator() -> SchemaValidator:
    return SchemaValidator(Path.cwd() / "schemas")


def test_context_loader_includes_small_workspace_files_and_skips_secrets(tmp_path: Path) -> None:
    (tmp_path / ".agent" / "context").mkdir(parents=True)
    (tmp_path / "buggy_math.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "api.txt").write_text("secret", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=secret", encoding="utf-8")

    context = ContextLoader(tmp_path, validator()).load()

    files = {item["path"]: item for item in context["workspace_files"]}
    assert files["buggy_math.py"]["content"] == "def add(a, b):\n    return a - b\n"
    assert files["notes.md"]["content"] == "# Notes\n"
    assert "secrets/api.txt" not in files
    assert ".env" not in files
