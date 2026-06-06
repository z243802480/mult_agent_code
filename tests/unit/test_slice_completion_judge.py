from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.long_horizon_completion import evaluate_slice_completion
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.core.slice_completion_judge import (
    apply_model_judge,
    build_judge_context,
    run_slice_completion_judge,
)
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_apply_model_judge_vetoes_complete_slice() -> None:
    evaluation = {
        "slice_complete": True,
        "summary": "本 slice 已达成完成契约。",
        "signals": {"accepted_run": True},
        "policy": {"enable_model_judge": True},
    }
    judge = {
        "slice_complete": False,
        "confidence": 0.91,
        "reason": "Milestone acceptance criteria not met.",
        "mode": "model",
    }
    merged = apply_model_judge(evaluation, judge)
    assert merged["slice_complete"] is False
    assert merged["signals"]["model_judge_pass"] is False
    assert "模型判定未完成" in merged["summary"]


def test_run_slice_completion_judge_skips_when_disabled(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-0001"
    run_dir.mkdir(parents=True)
    rule_eval = {"slice_complete": True, "policy": {"enable_model_judge": False}}
    result = run_slice_completion_judge(
        run_dir,
        rule_eval,
        validator=SchemaValidator(Path.cwd() / "schemas"),
    )
    assert result is None


def test_fake_model_judge_confirms_complete_slice(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = NorthStarStore(tmp_path, validator)
    store.create_default(title="Judge", statement="Confirm slice")
    north_star = store.read()
    assert north_star is not None
    north_star["slice_completion_policy"] = {"enable_model_judge": True}
    store.write(north_star)

    run_dir = tmp_path / ".asteria" / "runs" / "run-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "goal_spec.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "goal_id": "g1",
                "original_goal": "demo",
                "normalized_goal": "demo goal",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "eval_report.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "run_id": "run-0001",
                "goal_eval": {},
                "artifact_eval": {},
                "outcome_eval": {},
                "trajectory_eval": {},
                "cost_eval": {},
                "overall": {"status": "pass", "score": 0.9, "reason": "ok"},
            }
        ),
        encoding="utf-8",
    )

    evaluation = evaluate_slice_completion(
        tmp_path,
        "run-0001",
        validator=validator,
        accepted=True,
        review_status="pass",
        model_client=FakeModelClient(),
    )
    assert evaluation["slice_complete"] is True
    assert evaluation.get("model_judge") is not None
    assert evaluation["model_judge"]["mode"] == "model"


def test_build_judge_context_includes_open_tasks(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "task_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "tasks": [
                    {"task_id": "t1", "title": "Finish tests", "status": "pending"},
                ],
            }
        ),
        encoding="utf-8",
    )
    rule_eval = {"run_id": "run-0001", "slice_complete": True, "summary": "ok", "signals": {}}
    context = build_judge_context(
        run_dir,
        rule_eval,
        validator=SchemaValidator(Path.cwd() / "schemas"),
    )
    assert "Finish tests" in context["open_tasks"]
