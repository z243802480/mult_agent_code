"""P3-1: the model-facing `grep` tool (search_text) supports real regex, not only literal.

The default stays literal substring (non-breaking); regex=true opts into re.search, and an
invalid pattern fails closed instead of silently matching nothing.
"""
from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.search_tools import FindFilesTool, SearchTextTool


def _context(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"permission_mode": "reviewed_auto", "protected_paths": []},
        validator=SchemaValidator(Path("schemas")),
        run_dir_override=tmp_path,
    )


def _write(tmp_path: Path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_search_text_literal_default_treats_metachars_literally(tmp_path: Path) -> None:
    _write(tmp_path, "f.txt", "value a.b here\nvalue axb here\n")
    result = SearchTextTool().run(_context(tmp_path), pattern="a.b", path="f.txt")
    lines = {m["line"] for m in result.data["matches"]}
    assert lines == {1}  # only the literal "a.b" line, NOT "axb"


def test_search_text_regex_matches_pattern(tmp_path: Path) -> None:
    _write(tmp_path, "f.txt", "value a.b here\nvalue axb here\n")
    result = SearchTextTool().run(_context(tmp_path), pattern="a.b", path="f.txt", regex=True)
    lines = {m["line"] for m in result.data["matches"]}
    assert lines == {1, 2}  # regex "a.b" matches both "a.b" and "axb"


def test_search_text_regex_is_case_insensitive_by_default(tmp_path: Path) -> None:
    _write(tmp_path, "f.txt", "Foo\nbar\n")
    result = SearchTextTool().run(_context(tmp_path), pattern="foo", path="f.txt", regex=True)
    assert [m["line"] for m in result.data["matches"]] == [1]


def test_search_text_regex_case_sensitive_respected(tmp_path: Path) -> None:
    _write(tmp_path, "f.txt", "Foo\nfoo\n")
    result = SearchTextTool().run(
        _context(tmp_path), pattern="foo", path="f.txt", case_sensitive=True, regex=True
    )
    assert [m["line"] for m in result.data["matches"]] == [2]  # only lowercase


def test_search_text_invalid_regex_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "f.txt", "anything\n")
    result = SearchTextTool().run(_context(tmp_path), pattern="(", path="f.txt", regex=True)
    assert result.ok is False
    assert result.error == "invalid_regex"


def test_find_files_defaults_glob_when_model_only_supplies_path(tmp_path: Path) -> None:
    (tmp_path / "input").mkdir()
    _write(tmp_path, "input/a.md", "# A\n")

    result = FindFilesTool().run(_context(tmp_path), path="input")

    assert result.ok is True
    assert {"path": "input/a.md", "type": "file"} in result.data["paths"]
