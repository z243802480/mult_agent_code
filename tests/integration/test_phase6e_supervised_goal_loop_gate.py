from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.supervised_goal_loop_command import SupervisedGoalLoopCommand
from asteria_runtime.core.goal_queue import GoalQueueStore
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.core.supervised_goal_loop import (
    SUPERVISED_LOOP_EVIDENCE_FILE,
    kill_file_path,
    loop_state_path,
    prepare_accept_ready_run,
    run_supervised_goal_loop,
    run_supervised_goal_loop_band,
    SupervisedSliceOutcome,
)
from asteria_runtime.storage.schema_validator import SchemaValidator

pytestmark = pytest.mark.workflow

GATE = json.loads(
    Path("benchmarks/phase6e_supervised_goal_loop_gate.json").read_text(encoding="utf-8")
)


def test_phase6e_gate_manifest_is_wired() -> None:
    assert GATE["phase"] == "6"
    assert GATE["wave"] == "5"
    assert Path(GATE["depends_on_gate"]).exists()
    assert Path(GATE["plan"]).exists()
    for rel in GATE["reference_briefs"]:
        assert Path(rel).exists()
    for rel in GATE["contract_tests"]:
        assert Path(rel).exists()
    scope = GATE["loop_scope"]
    assert scope["kill_file"] == ".asteria/STOP"
    assert scope["requires_accept_per_slice"] is True


def test_supervised_goal_loop_band_completes_bounded_slices(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    band = run_supervised_goal_loop_band(tmp_path, validator, max_slices=2)
    assert band.ok is True
    assert band.slices_completed == 2
    assert band.slices_attempted == 2
    assert band.stop_reason == "max_slices_reached"
    assert loop_state_path(tmp_path).exists()
    queue = GoalQueueStore(tmp_path, validator).read()
    assert queue is not None
    done_count = len([item for item in queue["items"] if item["status"] == "done"])
    assert done_count == 2
    for run_id in band.slice_run_ids:
        evidence = tmp_path / ".asteria" / "runs" / run_id / SUPERVISED_LOOP_EVIDENCE_FILE
        assert evidence.exists()


def test_kill_switch_stops_supervised_loop_before_slices(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    InitCommand(tmp_path).run()
    NorthStarStore(tmp_path, validator).create_default(
        title="Kill switch",
        statement="Stop before slices",
        milestone_titles=["Slice A", "Slice B"],
    )
    kill_file_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    kill_file_path(tmp_path).write_text("operator stop\n", encoding="utf-8")

    def slice_runner(goal_text: str, _item: dict) -> SupervisedSliceOutcome:
        run_id = prepare_accept_ready_run(tmp_path, validator, goal_text)
        return SupervisedSliceOutcome(run_id=run_id, status="completed")

    def accept_runner(run_id: str) -> bool:
        from asteria_runtime.commands.accept_command import AcceptCommand

        return AcceptCommand(tmp_path, run_id=run_id, skip_review=True).run().accepted

    band = run_supervised_goal_loop(
        tmp_path,
        validator,
        max_slices=3,
        slice_runner=slice_runner,
        accept_runner=accept_runner,
    )
    assert band.slices_completed == 0
    assert band.slices_attempted == 0
    assert band.stop_reason == "kill_switch"


def test_supervised_command_writes_user_progress(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    InitCommand(tmp_path).run()
    NorthStarStore(tmp_path, validator).create_default(
        title="Progress narrative",
        statement="Supervised progress",
        milestone_titles=["Progress slice 1", "Progress slice 2"],
    )

    def slice_runner(goal_text: str, _item: dict) -> SupervisedSliceOutcome:
        run_id = prepare_accept_ready_run(tmp_path, validator, goal_text)
        return SupervisedSliceOutcome(run_id=run_id, status="completed")

    def accept_runner(run_id: str) -> bool:
        from asteria_runtime.commands.accept_command import AcceptCommand

        return AcceptCommand(tmp_path, run_id=run_id, skip_review=True).run().accepted

    result = SupervisedGoalLoopCommand(
        tmp_path,
        max_slices=1,
        slice_runner=slice_runner,
        accept_runner=accept_runner,
        validator=validator,
    ).run()
    assert result.slices_completed == 1
    run_dir = tmp_path / ".asteria" / "runs" / result.slice_run_ids[0]
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any("监督续跑 slice" in event.get("title", "") for event in progress)
    assert any("监督 slice" in event.get("title", "") for event in progress)
