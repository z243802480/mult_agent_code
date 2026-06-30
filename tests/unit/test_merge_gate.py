from __future__ import annotations

from dataclasses import dataclass

import pytest

from asteria_runtime.core.merge_gate import MergeGate, classify_change_risk

pytestmark = pytest.mark.contract


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


def test_merge_gate_flags_sensitive_path_without_blocking() -> None:
    task = {"write_scope": ["package.json"]}

    result = MergeGate().evaluate(task, ["package.json"], [Result(ok=True)])

    assert result.ok  # risk annotates, it never blocks the gate
    assert result.promotable_files == ["package.json"]
    assert result.risky_files == ["package.json"]
    assert result.risk_level == "high"


def test_merge_gate_ordinary_change_is_not_risky() -> None:
    task = {"write_scope": ["src/tool.py"]}

    result = MergeGate().evaluate(task, ["src/tool.py"], [Result(ok=True)])

    assert result.ok
    assert result.risky_files == []
    assert result.risk_level == "low"


def test_classify_change_risk_high_risk_task_and_sensitive_paths() -> None:
    assert classify_change_risk({"risk": "high"}, "src/tool.py") is True
    assert classify_change_risk({}, ".github/workflows/ci.yml") is True
    assert classify_change_risk({}, "package-lock.json") is True
    assert classify_change_risk({}, "deploy/main.tf") is True
    assert classify_change_risk({}, "config/secret-keys.json") is True
    assert classify_change_risk({}, "requirements.txt") is True
    assert classify_change_risk({}, "src/feature.py") is False
    assert classify_change_risk({"risk": "low"}, "docs/readme.md") is False
