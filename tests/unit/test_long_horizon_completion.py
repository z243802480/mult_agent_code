from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.long_horizon_completion import (
    DEFAULT_SLICE_COMPLETION_POLICY,
    evaluate_slice_completion,
    resolve_slice_completion_policy,
)
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_resolve_slice_completion_policy_merges_north_star() -> None:
    north_star = {
        "slice_completion_policy": {
            "requires_all_tasks_done": True,
            "min_review_score": 0.8,
        }
    }
    policy = resolve_slice_completion_policy(north_star)
    assert policy["requires_accepted_run"] is True
    assert policy["requires_review_pass"] is True
    assert policy["requires_all_tasks_done"] is True
    assert policy["min_review_score"] == 0.8


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
    assert DEFAULT_SLICE_COMPLETION_POLICY["min_review_score"] is None


def test_evaluate_slice_completion_fails_when_score_below_min(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = NorthStarStore(tmp_path, validator)
    store.create_default(title="Score gate", statement="Require min review score")
    north_star = store.read()
    assert north_star is not None
    north_star["slice_completion_policy"] = {"min_review_score": 0.8}
    store.write(north_star)

    run_dir = tmp_path / ".asteria" / "runs" / "run-0001"
    run_dir.mkdir(parents=True)
    eval_report = {
        "schema_version": "0.1.0",
        "run_id": "run-0001",
        "goal_eval": {},
        "artifact_eval": {},
        "outcome_eval": {},
        "trajectory_eval": {},
        "cost_eval": {},
        "overall": {"status": "partial", "score": 0.65, "reason": "below threshold"},
    }
    (run_dir / "eval_report.json").write_text(json.dumps(eval_report), encoding="utf-8")

    result = evaluate_slice_completion(
        tmp_path,
        "run-0001",
        validator=validator,
        accepted=True,
        review_status="pass",
    )
    assert result["slice_complete"] is False
    assert result["signals"]["review_score"] == 0.65
    assert result["signals"]["review_score_pass"] is False
    assert "0.65" in result["summary"]
