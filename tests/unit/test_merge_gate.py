from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core.merge_gate import MergeGate


@dataclass(frozen=True)
class Result:
    ok: bool
    summary: str = "ok"


def test_merge_gate_allows_changes_inside_write_scope() -> None:
    task = {"write_scope": ["src/tool.py"]}

    result = MergeGate().evaluate(task, ["src/tool.py"], [Result(ok=True)])

    assert result.ok
    assert result.promotable_files == ["src/tool.py"]
    assert result.violations == []


def test_merge_gate_blocks_changes_outside_write_scope() -> None:
    task = {"write_scope": ["src/tool.py"]}

    result = MergeGate().evaluate(task, ["src/tool.py", "docs/notes.md"], [Result(ok=True)])

    assert not result.ok
    assert result.promotable_files == []
    assert result.violations == ["changed files outside write_scope: docs/notes.md"]


def test_merge_gate_blocks_empty_or_unverified_promotion() -> None:
    task = {
        "write_scope": ["src/"],
        "completion_contract": {
            "requires_changed_artifact": True,
            "requires_verification": True,
            "allows_expected_failure": False,
        },
    }

    result = MergeGate().evaluate(task, [], [Result(ok=False, summary="tests failed")])

    assert not result.ok
    assert "no changed files were proposed for promotion" in result.violations
    assert "verification failed before promotion" in result.violations


def test_merge_gate_allows_readonly_verified_noop() -> None:
    task = {
        "write_scope": [],
        "completion_contract": {
            "requires_changed_artifact": False,
            "requires_verification": True,
            "allows_expected_failure": False,
        },
    }

    result = MergeGate().evaluate(task, [], [Result(ok=True)])

    assert result.ok
    assert result.promotable_files == []
