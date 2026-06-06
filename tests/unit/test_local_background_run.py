from __future__ import annotations

from pathlib import Path

from unittest.mock import patch

from asteria_runtime.commands.background_run_command import BackgroundRunCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.local_background_run import (
    BackgroundRunRegistry,
    background_run_projection,
    build_background_goal_argv,
    registry_path,
)


def test_build_background_goal_argv_includes_root_and_no_research(tmp_path: Path) -> None:
    argv = build_background_goal_argv(tmp_path, "demo goal")
    assert "goal" in argv
    assert "demo goal" in argv
    assert "--no-research" in argv
    assert str(tmp_path.resolve()) in argv


def test_registry_append_and_projection(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    registry = BackgroundRunRegistry(tmp_path)
    registry.append_run(
        {
            "background_run_id": "bg-test",
            "status": "running",
            "goal": "demo",
            "pid": 1001,
            "local_subprocess": True,
            "cloud_vm": False,
            "started_at": "2026-06-06T12:00:00+08:00",
            "updated_at": "2026-06-06T12:00:00+08:00",
        }
    )
    assert registry_path(tmp_path).exists()
    with patch("asteria_runtime.core.local_background_run._pid_is_alive", return_value=True):
        projection = background_run_projection(tmp_path)
    assert projection["running_count"] == 1
    assert projection["cloud_vm"] is False


def test_background_command_start_requires_goal(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    try:
        BackgroundRunCommand(tmp_path, action="start", goal=None).run()
        raised = False
    except ValueError:
        raised = True
    assert raised is True
