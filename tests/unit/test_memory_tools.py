import json
from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.memory_tools import (
    MAX_ENTRIES_PER_RUN,
    RecallMemoryTool,
    RememberTool,
)


def _context(tmp_path: Path, run_id: str | None = "run-1") -> RuntimeContext:
    (tmp_path / ".asteria").mkdir(parents=True, exist_ok=True)
    return RuntimeContext(
        root=tmp_path,
        run_id=run_id,
        policy={"protected_paths": []},
        validator=SchemaValidator(Path("schemas")),
    )


def _notes_path(tmp_path: Path) -> Path:
    return tmp_path / ".asteria" / "memory" / "model_notes.jsonl"


def test_remember_writes_schema_valid_entry_with_model_provenance(tmp_path: Path) -> None:
    context = _context(tmp_path)

    result = RememberTool().run(
        context,
        content="pytest must run with -p no:cacheprovider in this repo.",
        type="tool_knowledge",
        tags=["pytest"],
        confidence=0.9,
    )

    assert result.ok is True
    assert result.data["memory_id"] == "note-0001"
    rows = [
        json.loads(line)
        for line in _notes_path(tmp_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["type"] == "tool_knowledge"
    assert rows[0]["source"] == {"kind": "model", "run_id": "run-1"}
    assert rows[0]["confidence"] == 0.9


def test_remember_rejects_invalid_type_and_empty_content(tmp_path: Path) -> None:
    context = _context(tmp_path)

    bad_type = RememberTool().run(context, content="something", type="diary")
    assert bad_type.ok is False
    assert bad_type.error == "invalid_memory_type"
    assert "tool_knowledge" in bad_type.summary  # error teaches the valid vocabulary

    empty = RememberTool().run(context, content="   ")
    assert empty.ok is False
    assert empty.error == "empty_content"
    assert not _notes_path(tmp_path).exists()


def test_remember_rejects_oversized_content(tmp_path: Path) -> None:
    context = _context(tmp_path)

    result = RememberTool().run(context, content="x" * 5000)

    assert result.ok is False
    assert result.error == "content_too_long"


def test_remember_is_idempotent_for_identical_content(tmp_path: Path) -> None:
    context = _context(tmp_path)
    first = RememberTool().run(context, content="GLM json mode strips the substring json.")
    second = RememberTool().run(context, content="GLM json mode strips the substring json.")

    assert first.ok is True and first.data["deduplicated"] is False
    assert second.ok is True and second.data["deduplicated"] is True
    assert second.data["memory_id"] == first.data["memory_id"]
    lines = [
        line
        for line in _notes_path(tmp_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1


def test_remember_enforces_per_run_write_budget(tmp_path: Path) -> None:
    context = _context(tmp_path)
    for index in range(MAX_ENTRIES_PER_RUN):
        assert RememberTool().run(context, content=f"lesson {index}").ok is True

    over = RememberTool().run(context, content="one lesson too many")

    assert over.ok is False
    assert over.error == "memory_write_budget_exhausted"

    # A different run still has its own budget — the bound is per run, not per workspace.
    other = _context(tmp_path, run_id="run-2")
    assert RememberTool().run(other, content="a later run's lesson").ok is True


def test_recall_memory_returns_full_entry_with_source_file(tmp_path: Path) -> None:
    context = _context(tmp_path)
    long_content = "B" * 800
    RememberTool().run(context, content=long_content, type="research_claim")

    result = RecallMemoryTool().run(context, memory_id="note-0001")

    assert result.ok is True
    matches = result.data["matches"]
    assert len(matches) == 1
    assert matches[0]["content"] == long_content
    assert matches[0]["source_file"] == "model_notes.jsonl"


def test_recall_memory_returns_all_matches_when_ids_collide_across_files(
    tmp_path: Path,
) -> None:
    # decisions.jsonl and failures.jsonl both number from memory-0001, so a bare id can be
    # ambiguous; recall returns every match with its file rather than silently picking one.
    context = _context(tmp_path)
    memory_dir = tmp_path / ".asteria" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in [
        ("decisions.jsonl", "Decision content."),
        ("failures.jsonl", "Failure content."),
    ]:
        (memory_dir / filename).write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "memory_id": "memory-0001",
                    "type": "project_decision",
                    "content": content,
                    "source": {"kind": "test"},
                    "tags": [],
                    "confidence": 1.0,
                    "created_at": "2026-06-01T00:00:00+08:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    result = RecallMemoryTool().run(context, memory_id="memory-0001")

    assert result.ok is True
    assert {match["source_file"] for match in result.data["matches"]} == {
        "decisions.jsonl",
        "failures.jsonl",
    }


def test_recall_memory_reports_missing_id_and_skips_damaged_rows(tmp_path: Path) -> None:
    context = _context(tmp_path)
    memory_dir = tmp_path / ".asteria" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "failures.jsonl").write_text(
        "not json at all\n" + json.dumps({"schema_version": "0.1.0"}) + "\n",
        encoding="utf-8",
    )

    result = RecallMemoryTool().run(context, memory_id="memory-9999")

    assert result.ok is False
    assert result.error == "memory_not_found"
