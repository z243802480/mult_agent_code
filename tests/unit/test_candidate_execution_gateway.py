import json
from pathlib import Path

import pytest

from asteria_runtime.core.candidate_execution_gateway import CandidateExecutionGateway
from asteria_runtime.core.candidate_promotion_queue import PromotionPendingManualApproval
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.storage.schema_validator import SchemaValidator


def _risk_routing_context(tmp_path: Path, policy: dict):
    validator = SchemaValidator(Path.cwd() / "schemas")
    source = tmp_path / "source"
    run_dir = source / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    context = RuntimeContext(
        root=source,
        run_id="run-1",
        policy=policy,
        validator=validator,
        run_dir_override=run_dir,
    )
    gateway = CandidateExecutionGateway()
    candidate = gateway.create_workspace(context, {"task_id": "task-0001"})
    candidate_context = gateway.candidate_context(context, candidate)
    (candidate_context.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    return gateway, context, candidate, source, run_dir


def test_candidate_gateway_creates_context_and_promotes_changes(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    source = tmp_path / "source"
    run_dir = source / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (source / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    context = RuntimeContext(
        root=source,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=run_dir,
    )
    gateway = CandidateExecutionGateway()

    candidate = gateway.create_workspace(context, {"task_id": "task-0001"})
    candidate_context = gateway.candidate_context(context, candidate)
    (candidate_context.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    promoted = gateway.promote_changes(
        context,
        candidate,
        ["tool.py"],
        task_id="task-0001",
        merge_gate={"ok": True},
    )

    assert candidate_context.root == candidate.root
    assert promoted == ["tool.py"]
    assert (source / "tool.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    queue_rows = [
        json.loads(line)
        for line in (run_dir / "candidate_promotions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["status"] for row in queue_rows] == ["auto_approved", "promoted"]
    assert queue_rows[-1]["task_id"] == "task-0001"


def test_candidate_gateway_completes_task_after_promotion(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    board = TaskBoard(tmp_path / "task_plan.json", validator)
    board.store.write(
        board.path,
        {
            "schema_version": "0.1.0",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Task",
                    "description": "Do it",
                    "status": "testing",
                    "depends_on": [],
                    "allowed_tools": [],
                    "expected_artifacts": [],
                    "acceptance": [],
                    "completion_contract": {"requires_verification": False},
                    "verification_policy": {"required": False, "commands": []},
                    "parallel_safety": "serial",
                    "write_scope": [],
                    "created_at": "2026-05-17T10:00:00+08:00",
                    "updated_at": "2026-05-17T10:00:00+08:00",
                }
            ],
        },
        "task_board",
    )

    CandidateExecutionGateway().complete_after_promotion(board, "task-0001", "done")

    task = board.get_task("task-0001")
    assert task["status"] == "done"
    assert task["notes"] == "done"


def test_reviewed_auto_holds_risky_change_for_manual_approval(tmp_path: Path) -> None:
    gateway, context, candidate, source, run_dir = _risk_routing_context(
        tmp_path, {"protected_paths": [], "permission_mode": "reviewed_auto"}
    )

    with pytest.raises(PromotionPendingManualApproval):
        gateway.promote_changes(
            context,
            candidate,
            ["tool.py"],
            task_id="task-0001",
            merge_gate={"ok": True, "risky_files": ["tool.py"], "risk_level": "high"},
        )

    # The risky change is held, not promoted to the real workspace.
    assert (source / "tool.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    rows = [
        json.loads(line)
        for line in (run_dir / "candidate_promotions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert "pending" in rows[-1]["status"]


def test_auto_mode_auto_promotes_risky_change(tmp_path: Path) -> None:
    gateway, context, candidate, source, _ = _risk_routing_context(
        tmp_path, {"protected_paths": [], "permission_mode": "auto"}
    )

    promoted = gateway.promote_changes(
        context,
        candidate,
        ["tool.py"],
        task_id="task-0001",
        merge_gate={"ok": True, "risky_files": ["tool.py"], "risk_level": "high"},
    )

    # Full autopilot does not hold for risk — edits land directly.
    assert promoted == ["tool.py"]
    assert (source / "tool.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_manual_approval_default_holds_even_non_risky(tmp_path: Path) -> None:
    gateway, context, candidate, source, _ = _risk_routing_context(
        tmp_path, {"protected_paths": [], "promotion": {"manual_approval_default": True}}
    )

    with pytest.raises(PromotionPendingManualApproval):
        gateway.promote_changes(
            context,
            candidate,
            ["tool.py"],
            task_id="task-0001",
            merge_gate={"ok": True},
        )

    assert (source / "tool.py").read_text(encoding="utf-8") == "VALUE = 1\n"
