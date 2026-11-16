import hashlib
from pathlib import Path

import pytest

from asteria_runtime.core import review_artifacts as module
from asteria_runtime.core.review_artifacts import collect_review_artifacts
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator


def context(root):
    return RuntimeContext(root, "run-review", {"protected_paths": []}, SchemaValidator(Path("schemas")))


def test_snapshot_reads_current_artifact_without_writing_or_guessing_file_type(tmp_path):
    path = tmp_path / "result.custom"
    path.write_text("old result\n", encoding="utf8")
    goal = {"target_outputs": [path.name]}
    board = {"tasks": [{"expected_artifacts": [path.name]},
                        {"status": "discarded", "expected_artifacts": ["obsolete"]}]}
    old = collect_review_artifacts(context(tmp_path), goal, board)
    path.write_text("current result\n", encoding="utf8")
    current = collect_review_artifacts(context(tmp_path), goal, board)
    row = current["files"][0]
    assert current["complete"] and len(current["files"]) == 1
    assert row["content"].splitlines() == path.read_text(encoding="utf8").splitlines()
    assert row["content_sha256"] == hashlib.sha256(row["content"].encode("utf8")).hexdigest()
    assert old["files"][0]["content_sha256"] != row["content_sha256"]
    assert current["evidence_id"] != old["evidence_id"]
    assert list(tmp_path.iterdir()) == [path]


def test_file_that_fits_byte_budget_is_not_silently_cut_to_default_line_page(tmp_path):
    text = "current line\n" * 900
    (tmp_path / "large-line-count").write_text(text, encoding="utf8")
    snapshot = collect_review_artifacts(context(tmp_path), {"target_outputs": ["large-line-count"]}, {})
    assert snapshot["complete"]
    assert snapshot["files"][0]["content"].splitlines() == text.splitlines()


@pytest.mark.parametrize("path", [".env", "nested/.env.local", "secrets/token", ".asteria/run.json", "private.key", "../outside.txt"])
def test_protected_or_outside_targets_never_open(tmp_path, monkeypatch, path):
    target = (tmp_path / path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fake protected test fixture", encoding="utf8")
    read_text = Path.read_text
    def guarded_read(self, *args, **kwargs):
        assert self.resolve() != target, "Protected artifact must not be opened"
        return read_text(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded_read)
    snapshot = collect_review_artifacts(context(tmp_path), {"target_outputs": [path]}, {})
    assert not snapshot["complete"]
    assert snapshot["files"][0]["status"] == "unavailable"
    assert snapshot["files"][0]["content"] is None


def test_capacity_preserves_unknown_and_omissions(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_FILES", 2)
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 8)
    monkeypatch.setattr(module, "MAX_TOTAL_CONTENT_BYTES", 10)
    for name, text in [("large", "abcdefghijk\n"), ("small", "xy"), ("omitted", "z")]:
        (tmp_path / name).write_text(text, encoding="utf8")
    snapshot = collect_review_artifacts(context(tmp_path), {"target_outputs": ["large", "small", "omitted"]}, {})
    assert not snapshot["complete"]
    assert snapshot["files"][0]["status"] == "partial"
    assert sum(len(row["content"].encode("utf8")) for row in snapshot["files"]) <= 10
    assert snapshot["omitted_paths"] == ["omitted"]


def test_missing_directory_and_non_text_targets_are_explicitly_unavailable(tmp_path):
    (tmp_path / "directory").mkdir()
    (tmp_path / "binary").write_bytes(b"\xff\xfe")
    snapshot = collect_review_artifacts(context(tmp_path), {"target_outputs": ["missing", "directory", "binary"]}, {})
    assert not snapshot["complete"]
    assert all(row["status"] == "unavailable" and row["content"] is None for row in snapshot["files"])


def test_legacy_outcome_description_is_not_invented_as_a_missing_file(tmp_path):
    snapshot = collect_review_artifacts(context(tmp_path), {"target_outputs": ["workflow evidence"]}, {})
    assert snapshot["files"] == [] and snapshot["complete"]


def test_task_declared_artifact_with_spaces_still_requires_current_content(tmp_path):
    snapshot = collect_review_artifacts(context(tmp_path), {}, {"tasks": [{"expected_artifacts": ["My report.txt"]}]})
    assert not snapshot["complete"] and snapshot["files"][0]["path"] == "My report.txt"
