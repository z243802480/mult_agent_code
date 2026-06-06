from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.long_horizon_completion import (
    DEFAULT_SLICE_COMPLETION_POLICY,
    evaluate_slice_completion,
    resolve_slice_completion_policy,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_resolve_slice_completion_policy_merges_north_star() -> None:
    north_star = {
        "slice_completion_policy": {
            "requires_all_tasks_done": True,
        }
    }
    policy = resolve_slice_completion_policy(north_star)
    assert policy["requires_accepted_run"] is True
    assert policy["requires_review_pass"] is True
    assert policy["requires_all_tasks_done"] is True


def test_evaluate_slice_completion_passes_when_accepted_and_review_pass(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    result = evaluate_slice_completion(
        tmp_path,
        "run-0001",
        validator=validator,
        accepted=True,
        review_status="pass",
        north_star_link={"milestone_id": "ms-0001"},
    )
    assert result["slice_complete"] is True
    assert result["signals"]["accepted_run"] is True
    assert result["north_star_milestone_id"] == "ms-0001"


def test_evaluate_slice_completion_fails_when_review_not_pass(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    result = evaluate_slice_completion(
        tmp_path,
        "run-0001",
        validator=validator,
        accepted=False,
        review_status="partial",
    )
    assert result["slice_complete"] is False
    assert "未达成" in result["summary"]


def test_default_policy_matches_contract() -> None:
    assert DEFAULT_SLICE_COMPLETION_POLICY["requires_accepted_run"] is True
    assert DEFAULT_SLICE_COMPLETION_POLICY["requires_review_pass"] is True
