from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


def test_accept_command_promotes_pending_candidate_and_finalizes_run(tmp_path: Path) -> None:
    root, run_dir, candidate = _workspace_ready_for_accept(tmp_path)
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")

    result = AcceptCommand(root, skip_review=True).run()

    assert result.accepted is True
    assert result.status == "completed"
    assert result.review_status == "pass"
    assert result.promoted_files == ["tool.py"]
    assert (root / "tool.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert result.final_report_path.exists()
    assert result.final_report_summary_path == run_dir / "final_report_summary.json"
    assert result.final_report_summary["status"] == "completed"
    assert result.to_dict()["final_report_summary"] == result.final_report_summary
    assert "Final report summary:" in result.to_text()
    run = JsonStore(SchemaValidator(Path.cwd() / "schemas")).read(run_dir / "run.json", "run")
    assert run["current_phase"] == "ACCEPTED"
    assert "Accepted by operator" in run["summary"]


def test_accept_command_blocks_when_review_has_not_passed(tmp_path: Path) -> None:
    root, run_dir, _candidate = _workspace_ready_for_accept(tmp_path, review_status="partial")

    result = AcceptCommand(root, skip_review=True, promote_all=False).run()

    assert result.accepted is False
    assert result.status == "blocked"
    assert any("review status is partial" in blocker for blocker in result.blockers)
    assert result.primary_blocker is not None
    assert "review status is partial" in result.primary_blocker
    assert result.recommended_next_command == "debug"
    payload = result.to_dict()
    assert "primary_blocker" in payload
    assert payload["recommended_next_command"] == "debug"
    assert payload["final_report_summary_path"] == str(run_dir / "final_report_summary.json")
    assert payload["final_report_summary"]["status"] == "blocked"
    assert payload["final_report_summary"]["recommended_next_command"] == "debug"
    text = result.to_text()
    assert "Primary blocker: " in text
    assert "Recommended next command: asteria debug" in text
    run = JsonStore(SchemaValidator(Path.cwd() / "schemas")).read(run_dir / "run.json", "run")
    assert run["current_phase"] == "ACCEPT"


def _workspace_ready_for_accept(
    tmp_path: Path,
    *,
    review_status: str = "pass",
) -> tuple[Path, Path, CandidateWorkspace]:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    root = tmp_path / "workspace"
    root.mkdir()
    agent_dir = root / ".asteria"
    run_store = RunStore(agent_dir, validator)
    run = run_store.create_run("test accept")
    run_store.set_current_session(run["run_id"], "test")
    run_dir = run_store.run_dir(run["run_id"])
    (root / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    store.write(
        run_dir / "goal_spec.json",
        {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": "update tool",
            "normalized_goal": "update tool",
            "goal_type": "codebase_improvement",
            "assumptions": [],
            "constraints": [],
            "non_goals": [],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": "Update tool.py",
                    "source": "user",
                    "acceptance": ["tool updated"],
                }
            ],
            "target_outputs": ["tool.py"],
            "definition_of_done": ["tool updated"],
            "verification_strategy": ["review pass"],
            "budget": {},
        },
        "goal_spec",
    )
    store.write(
        run_dir / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Update tool",
                    "description": "Update tool.py",
                    "status": "done",
                    "depends_on": [],
                    "acceptance": ["tool.py updated"],
                    "expected_artifacts": ["tool.py"],
                }
            ],
        },
        "task_board",
    )
    store.write(
        run_dir / "cost_report.json",
        {
            "schema_version": "0.1.0",
            "run_id": run["run_id"],
            "model_calls": 1,
            "tool_calls": 1,
            "estimated_input_tokens": 1,
            "estimated_output_tokens": 1,
            "strong_model_calls": 0,
            "cheap_model_calls": 0,
            "repair_attempts": 0,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        },
        "cost_report",
    )
    store.write(
        run_dir / "eval_report.json",
        {
            "schema_version": "0.1.0",
            "run_id": run["run_id"],
            "goal_eval": {},
            "artifact_eval": {},
            "outcome_eval": {},
            "trajectory_eval": {},
            "cost_eval": {},
            "overall": {
                "status": review_status,
                "score": 0.95 if review_status == "pass" else 0.6,
                "reason": "test review",
            },
        },
        "eval_report",
    )
    candidate = CandidateWorkspace.create(root, run_dir, "task-0001")
    JsonlStore(validator).append(
        run_dir / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": run["run_id"],
            "task_id": "task-0001",
            "candidate_id": candidate.candidate_id,
            "workspace": str(candidate.root),
            "strategy": candidate.strategy,
            "workspace_policy": candidate.workspace_policy,
            "backend_reason": candidate.backend_reason,
            "branch_name": candidate.branch_name,
            "promotable_files": ["tool.py"],
            "promoted_files": [],
            "status": "pending_manual_approval",
            "approval_mode": "manual",
            "merge_gate": {"ok": True},
            "failure": None,
            "decision": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        },
        "candidate_promotion",
    )
    return root, run_dir, candidate
