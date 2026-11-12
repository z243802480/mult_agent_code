from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from asteria_runtime.core.content_preservation import (
    capture_content_preservation,
    content_preservation_violations,
    normalize_content_preservation,
)
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_contract import check_completion_contract
from asteria_runtime.storage.schema_validator import SchemaValidator, SchemaValidationError


def setup(tmp_path, content=b"first\nsecond\n"):
    (tmp_path / "note.txt").write_bytes(content)
    ctx = RuntimeContext(
        tmp_path, "run-1", {"protected_paths": []}, SchemaValidator(Path("schemas"))
    )
    goal = {
        "goal_id": "goal-1",
        "content_preservation": [{"path": "note.txt", "mode": "existing_lines"}],
    }
    capture_content_preservation(ctx, goal)
    return ctx, goal


@pytest.mark.parametrize(
    "before,after,ok",
    [
        (b"a\nb\n", b"heading\na\nnew\nb\nfooter\n", True),
        (b"a\na\n", b"a\n", False),
        (b"a\nb\n", b"b\na\n", False),
        (b"a\nb\n", b"a # ignored\nb\n", False),
        (b"a\r\nb\r\n", b"a\nb\n", False),
        (b"a", b"a\n", False),
        (b"a", b"new\na", True),
        (b"", b"new\n", True),
        (b"\xff\n", b"new\n\xff\n", True),
    ],
)
def test_complete_byte_lines_are_preserved_in_order(tmp_path, before, after, ok):
    ctx, goal = setup(tmp_path, before)
    (tmp_path / "note.txt").write_bytes(after)
    assert (not content_preservation_violations(ctx, goal)) == ok


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        [{"path": "../x", "mode": "existing_lines"}],
        [{"path": "notes/", "mode": "existing_lines"}],
        [{"path": "*.txt", "mode": "existing_lines"}],
        [{"path": "note.txt", "mode": "open"}],
        [{"path": "note.txt", "mode": "existing_lines", "extra": True}],
    ],
)
def test_invalid_contract_is_not_a_grant(bad):
    with pytest.raises(SchemaValidationError):
        normalize_content_preservation(bad)


def test_snapshot_is_durable_and_cannot_rebase_on_bad_edit(tmp_path):
    ctx, goal = setup(tmp_path)
    path = ctx.run_dir / "content_preservation.json"
    before = path.read_bytes()
    (tmp_path / "note.txt").write_text("first # disabled\nsecond\n", encoding="utf8")
    capture_content_preservation(ctx, goal)
    assert path.read_bytes() == before
    assert content_preservation_violations(replace(ctx), goal)
    (tmp_path / "note.txt").write_bytes(b"first\nnew\nsecond\n")
    assert not content_preservation_violations(replace(ctx), goal)


@pytest.mark.parametrize(
    "case", ["missing", "damaged", "changed_goal", "changed_paths", "deleted_file"]
)
def test_unavailable_or_changed_evidence_fails_closed(tmp_path, case):
    ctx, goal = setup(tmp_path)
    p = ctx.run_dir / "content_preservation.json"
    if case == "missing":
        p.unlink()
    elif case == "damaged":
        data = json.loads(p.read_text())
        data["files"][0]["line_sha256"] = []
        p.write_text(json.dumps(data))
    elif case == "changed_goal":
        goal["goal_id"] = "other"
    elif case == "changed_paths":
        goal["content_preservation"][0]["path"] = "other.txt"
    else:
        (tmp_path / "note.txt").unlink()
    assert content_preservation_violations(ctx, goal)


def test_legacy_and_verified_noop_do_not_bypass_explicit_preservation(tmp_path):
    ctx, goal = setup(tmp_path)
    assert content_preservation_violations(ctx, {"goal_id": "legacy"}) == []
    (tmp_path / "note.txt").write_text("first # skip\nsecond\n")
    task = {"task_kind": "verification", "completion_contract": {"requires_verification": True}}
    green = [SimpleNamespace(ok=True)]
    assert check_completion_contract(task, [], green, allow_verified_noop=True).ok
    check = check_completion_contract(
        task,
        [],
        green,
        allow_verified_noop=True,
        content_preservation_violations=content_preservation_violations(ctx, goal),
    )
    assert not check.ok and "existing lines" in check.violations[0]


def test_protected_inputs_and_oversized_files_are_not_captured(tmp_path):
    ctx, goal = setup(tmp_path)
    goal["content_preservation"][0]["path"] = ".env"
    with pytest.raises(PermissionError):
        capture_content_preservation(replace(ctx, run_id="run-2"), goal)
    goal["content_preservation"][0]["path"] = "note.txt"
    (tmp_path / "note.txt").write_bytes(b"x" * 1_048_577)
    with pytest.raises(ValueError):
        capture_content_preservation(replace(ctx, run_id="run-2"), goal)
