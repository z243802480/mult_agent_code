from copy import deepcopy
import json
from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_pause_checkpoint import (
    clear_pause_changes,
    previous_pause_changes,
    record_pause_changes,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def context(root: Path, run_id: str = "run-pause") -> RuntimeContext:
    return RuntimeContext(
        root=root, run_id=run_id, policy={}, validator=SchemaValidator(Path("schemas"))
    )


def task() -> dict:
    return {
        "task_id": "task-0001",
        "title": "Create files",
        "description": "Create and check files",
        "task_kind": "implementation",
        "write_scope": ["a.py", "b.py"],
        "expected_changed_files": ["a.py", "b.py"],
        "validation_commands": ["python -m pytest"],
    }


def test_same_task_pause_carries_only_unchanged_files(tmp_path: Path) -> None:
    ctx, t = context(tmp_path), task()
    record_pause_changes(ctx, t, {}, {"a.py": (10, 3), "b.py": (11, 4)})
    assert previous_pause_changes(ctx, t, {"a.py": (10, 3), "b.py": (12, 4)}) == ["a.py"]
    assert previous_pause_changes(ctx, t, {}) == []
    assert previous_pause_changes(ctx, t, None) == []


def test_edit_boundary_change_invalidates_prior_progress(tmp_path: Path) -> None:
    ctx, original = context(tmp_path), task()
    original["edit_boundary"] = {"mode": "restricted", "paths": ["a.py", "b.py"]}
    record_pause_changes(ctx, original, {}, {"a.py": (10, 3)})
    narrowed = {**original, "edit_boundary": {"mode": "restricted", "paths": ["b.py"]}}
    assert previous_pause_changes(ctx, narrowed, {"a.py": (10, 3)}) == []


def test_existing_file_without_any_pause_change_is_not_progress(tmp_path: Path) -> None:
    ctx, t = context(tmp_path), task()
    state = {"a.py": (10, 3)}
    record_pause_changes(ctx, t, state, state)
    assert previous_pause_changes(ctx, t, state) == []


def test_task_contract_or_run_change_cannot_reuse_pause(tmp_path: Path) -> None:
    ctx, t = context(tmp_path), task()
    state = {"a.py": (10, 3)}
    record_pause_changes(ctx, t, {}, state)
    for key, value in [
        ("write_scope", []),
        ("validation_commands", ["different"]),
        ("task_kind", "verification"),
        ("acceptance", ["new goal"]),
    ]:
        changed = {**t, key: value}
        assert previous_pause_changes(ctx, changed, state) == []
    assert previous_pause_changes(context(tmp_path, "run-other"), t, state) == []
    assert previous_pause_changes(ctx, {**t, "task_id": "task-0002"}, state) == []


def test_repeated_pause_keeps_prior_changes_and_clears_after_completion(tmp_path: Path) -> None:
    ctx, t = context(tmp_path), task()
    first = {"a.py": (10, 3)}
    second = {**first, "b.py": (20, 5)}
    record_pause_changes(ctx, t, {}, first)
    record_pause_changes(ctx, t, first, second)
    assert previous_pause_changes(ctx, t, second) == ["a.py", "b.py"]
    clear_pause_changes(ctx, t)
    assert previous_pause_changes(ctx, t, second) == []


def test_empty_or_unavailable_new_checkpoint_does_not_fall_back_to_older_green(
    tmp_path: Path,
) -> None:
    ctx, t = context(tmp_path), task()
    state = {"a.py": (10, 3)}
    record_pause_changes(ctx, t, {}, state)
    record_pause_changes(ctx, t, None, None)
    assert previous_pause_changes(ctx, t, state) == []


def test_large_rename_delta_degrades_without_breaking_pause(tmp_path: Path) -> None:
    ctx, t = context(tmp_path), task()
    before = {f"old-{i}.py": (1, 1) for i in range(2501)}
    after = {f"new-{i}.py": (2, 1) for i in range(2501)}
    record_pause_changes(ctx, t, before, after)
    assert previous_pause_changes(ctx, t, after) == []


def test_checkpoint_is_schema_validated_on_read(tmp_path: Path) -> None:
    ctx, t = context(tmp_path), task()
    state = {"a.py": (10, 3)}
    record_pause_changes(ctx, t, {}, state)
    path = next((ctx.run_dir / "task_pause_checkpoints").glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    for change in [{"changes": {"a.py": [True, 3]}}, {"run_id": "run-other"}]:
        bad = {**deepcopy(data), **change}
        path.write_text(json.dumps(bad), encoding="utf-8")
        assert previous_pause_changes(ctx, t, state) == []
