from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.file_tools import WriteFileTool


def _context(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=SchemaValidator(Path.cwd() / "schemas"),
        run_dir_override=tmp_path,
    )


def test_write_file_refusal_tells_the_model_how_to_retry(tmp_path: Path) -> None:
    # Round 2 dogfood: a dead-end refusal made the doer give up and replan instead of retrying,
    # so the whole run finished with zero completed tasks. The message must carry the way out.
    target = tmp_path / "taskman.py"
    target.write_text("old", encoding="utf-8")

    result = WriteFileTool().run(
        _context(tmp_path), path="taskman.py", content="new", overwrite=False
    )

    assert result.ok is False
    assert "overwrite=true" in result.summary
    assert target.read_text(encoding="utf-8") == "old", "a refused write must not touch the file"


def test_write_file_overwrite_replaces_content_and_says_so(tmp_path: Path) -> None:
    target = tmp_path / "taskman.py"
    target.write_text("old", encoding="utf-8")

    result = WriteFileTool().run(
        _context(tmp_path), path="taskman.py", content="new", overwrite=True
    )

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "new"
    # The doer needs to be able to tell "created" from "modified" (ADR-0024 §5 #1).
    assert "Overwrote existing" in result.summary
