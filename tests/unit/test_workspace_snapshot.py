"""Workspace change scan (disk truth for the completion contract) — dogfood 1.2.136."""

from pathlib import Path

from asteria_runtime.core.task_contract import check_completion_contract
from asteria_runtime.core.workspace_snapshot import changed_paths, snapshot_workspace
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.command_tools import RunCommandTool


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_snapshot_diff_reports_created_modified_and_deleted(tmp_path: Path) -> None:
    _touch(tmp_path / "keep.py", "same")
    _touch(tmp_path / "edit.py", "before")
    _touch(tmp_path / "gone.py", "bye")
    before = snapshot_workspace(tmp_path)

    _touch(tmp_path / "edit.py", "after-with-different-size")
    _touch(tmp_path / "new.py", "hello")
    (tmp_path / "gone.py").unlink()
    after = snapshot_workspace(tmp_path)

    assert changed_paths(before, after) == ["edit.py", "gone.py", "new.py"]


def test_snapshot_skips_runtime_and_junk_directories(tmp_path: Path) -> None:
    _touch(tmp_path / "src" / "app.py")
    _touch(tmp_path / ".asteria" / "runs" / "run-1" / "events.jsonl")
    _touch(tmp_path / ".git" / "HEAD")
    _touch(tmp_path / "__pycache__" / "app.cpython-313.pyc")
    snap = snapshot_workspace(tmp_path)
    assert snap is not None
    assert list(snap) == ["src/app.py"]


def test_snapshot_bails_out_on_oversized_workspace(tmp_path: Path) -> None:
    for i in range(6):
        _touch(tmp_path / f"f{i}.txt")
    assert snapshot_workspace(tmp_path, max_files=5) is None
    # A bailed-out side yields no diff — the feature degrades to tool-ledger-only, never noise.
    assert changed_paths(None, {"a.py": (1, 1)}) == []


def test_contract_carries_unscoped_changed_files_as_disclosure_not_violation(
    tmp_path: Path,
) -> None:
    task = {
        "task_id": "task-0001",
        "task_kind": "implementation",
        "completion_contract": {"requires_verification": False, "requires_changed_artifact": True},
    }
    check = check_completion_contract(
        task,
        ["src/app.py"],
        [],
        unscoped_changed_files=["stray_data.bin"],
    )
    assert check.ok
    assert check.to_dict()["unscoped_changed_files"] == ["stray_data.bin"]


def test_shell_observation_discloses_unobserved_cache_without_exempting_user_files(tmp_path):
    before = snapshot_workspace(tmp_path)
    _touch(tmp_path / ".pytest_cache" / "v" / "cache" / "nodeids")
    _touch(tmp_path / "user-result.bin")
    context = RuntimeContext(tmp_path, "run-scan", {}, SchemaValidator(Path("schemas")))
    data = RunCommandTool()._workspace_observation(context, before)
    assert data["workspace_changes"]["created"] == ["user-result.bin"]
    coverage = data["workspace_scan_coverage"]
    assert ".pytest_cache" in coverage["excluded_directories"]
    assert coverage["exclusions_grant_permission"] is False
    assert data["workspace_scan"] == "stat_only"
    unavailable = RunCommandTool()._workspace_observation(context, None)
    assert unavailable["workspace_changes"] is None
    assert unavailable["workspace_scan_coverage"] == coverage
