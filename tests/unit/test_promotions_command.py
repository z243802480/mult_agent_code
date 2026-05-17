from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.promotions_command import PromotionsCommand
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


def test_promotions_command_lists_and_approves_pending_candidate(tmp_path: Path) -> None:
    root, run_dir, candidate = _workspace_with_pending_promotion(tmp_path)
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")

    listed = PromotionsCommand(root=root, action="list").run()
    approved = PromotionsCommand(
        root=root,
        action="approve",
        promotion_id="promotion-0001",
    ).run()

    assert listed.promotions[0]["status"] == "pending_manual_approval"
    assert approved.promotions[0]["status"] == "promoted"
    assert (root / "tool.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    rows = [
        json.loads(line)
        for line in (run_dir / "candidate_promotions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["status"] for row in rows] == [
        "pending_manual_approval",
        "approved",
        "promoted",
    ]


def test_promotions_command_records_failed_promotion_without_polluting_source(
    tmp_path: Path,
) -> None:
    root, run_dir, candidate = _workspace_with_pending_promotion(tmp_path)
    (candidate.root / "tool.py").unlink()

    result = PromotionsCommand(
        root=root,
        action="approve",
        promotion_id="promotion-0001",
    ).run()

    assert result.promotions[0]["status"] == "promotion_failed"
    assert result.promotions[0]["failure"]["type"] == "RuntimeError"
    assert (root / "tool.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    latest = _latest_promotions(run_dir)
    assert latest[-1]["status"] == "promotion_failed"


def test_promotions_command_rejects_and_discards_candidate(tmp_path: Path) -> None:
    root, run_dir, candidate = _workspace_with_pending_promotion(tmp_path)

    rejected = PromotionsCommand(
        root=root,
        action="reject",
        promotion_id="promotion-0001",
        reason="Needs human review.",
    ).run()
    discarded = PromotionsCommand(
        root=root,
        action="discard",
        promotion_id="promotion-0001",
        reason="No longer needed.",
    ).run()

    assert rejected.promotions[0]["status"] == "rejected"
    assert discarded.promotions[0]["status"] == "discarded"
    assert not candidate.root.exists()
    latest = _latest_promotions(run_dir)
    assert latest[-2]["status"] == "rejected"
    assert latest[-1]["status"] == "discarded"


def _workspace_with_pending_promotion(tmp_path: Path) -> tuple[Path, Path, CandidateWorkspace]:
    validator = SchemaValidator(Path.cwd() / "schemas")
    root = tmp_path / "workspace"
    root.mkdir()
    agent_dir = root / ".asteria"
    run_store = RunStore(agent_dir, validator)
    run = run_store.create_run("test")
    run_store.set_current_session(run["run_id"], "test")
    run_dir = run_store.run_dir(run["run_id"])
    (root / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    candidate = CandidateWorkspace.create(root, run_dir, "task-0001")
    _write_pending_promotion(validator, run_dir, run["run_id"], candidate)
    return root, run_dir, candidate


def _write_pending_promotion(
    validator: SchemaValidator,
    run_dir: Path,
    run_id: str,
    candidate: CandidateWorkspace,
) -> None:
    JsonlStore(validator).append(
        run_dir / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": run_id,
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


def _latest_promotions(run_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (run_dir / "candidate_promotions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
