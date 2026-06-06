from __future__ import annotations

from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.goal_queue import GoalQueueStore
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.core.supervised_goal_loop import (
    kill_file_path,
    prepare_accept_ready_run,
    run_supervised_goal_loop,
    should_stop_supervised_loop,
    SupervisedSliceOutcome,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_should_stop_when_kill_file_present(tmp_path: Path) -> None:
    kill_file_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    kill_file_path(tmp_path).write_text("stop", encoding="utf-8")
    stopped, reason = should_stop_supervised_loop(tmp_path)
    assert stopped is True
    assert reason == "kill_switch"


def test_goal_queue_mark_in_progress(tmp_path: Path) -> None:
    store = GoalQueueStore(tmp_path)
    store.seed_goals(["A", "B"], source="test")
    item = store.mark_in_progress("gq-0001")
    assert item is not None
    assert item["status"] == "in_progress"


def test_prepare_accept_ready_run_creates_run(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_id = prepare_accept_ready_run(tmp_path, validator, "band goal")
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    assert (run_dir / "eval_report.json").exists()


def test_supervised_loop_requires_north_star(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    InitCommand(tmp_path).run()
    with pytest.raises(RuntimeError, match="North Star"):
        from asteria_runtime.commands.supervised_goal_loop_command import (
            SupervisedGoalLoopCommand,
        )

        SupervisedGoalLoopCommand(tmp_path, max_slices=1, validator=validator).run()
