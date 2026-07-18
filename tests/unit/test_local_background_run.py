from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

from asteria_runtime.commands.background_run_command import BackgroundRunCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.local_background_run import (
    BackgroundGoalOptions,
    BackgroundRunRegistry,
    _pid_is_alive,
    background_run_projection,
    build_background_goal_argv,
    registry_path,
    start_local_background_run,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_build_background_goal_argv_includes_root_and_no_research(tmp_path: Path) -> None:
    argv = build_background_goal_argv(tmp_path, "demo goal")
    assert "goal" in argv
    assert "demo goal" in argv
    assert "--no-research" in argv
    assert str(tmp_path.resolve()) in argv


def test_build_background_goal_argv_threads_explicit_flags(tmp_path: Path) -> None:
    # dogfood friction #2: --permission-level (and other explicit run flags) used to be dropped
    # when rebuilding the background child argv, silently degrading the user's choice to `balanced`.
    argv = build_background_goal_argv(
        tmp_path,
        "demo goal",
        BackgroundGoalOptions(
            permission_level="auto", enable_research=True, model_strategy="economy"
        ),
    )
    assert argv[argv.index("--permission-level") + 1] == "auto"
    assert argv[argv.index("--model-strategy") + 1] == "economy"
    # enable_research=True honours the user's choice → the forced --no-research is gone.
    assert "--no-research" not in argv


def test_build_background_goal_argv_defaults_preserve_legacy_behaviour(tmp_path: Path) -> None:
    # No options → byte-for-byte the historical argv (research off, no permission flag).
    assert build_background_goal_argv(tmp_path, "g") == build_background_goal_argv(
        tmp_path, "g", BackgroundGoalOptions()
    )
    argv = build_background_goal_argv(tmp_path, "g", BackgroundGoalOptions())
    assert "--no-research" in argv
    assert "--permission-level" not in argv


def test_start_local_background_run_threads_options_into_spawned_command(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    captured: dict[str, list[str]] = {}

    class _FakeProcess:
        pid = 727272
        returncode: int | None = None

    def fake_spawn(command: list[str], **kwargs: object) -> _FakeProcess:
        captured["command"] = list(command)
        return _FakeProcess()

    entry = start_local_background_run(
        tmp_path,
        "add a json flag",
        validator,
        spawn=fake_spawn,
        options=BackgroundGoalOptions(permission_level="auto"),
    )
    # The permission level must reach both the spawned process argv and the recorded registry entry.
    assert captured["command"][captured["command"].index("--permission-level") + 1] == "auto"
    assert "--permission-level" in entry["command"]


def test_background_argv_module_is_a_real_entry_point(tmp_path: Path) -> None:
    # The spawned module used to be a silent no-op: asteria_runtime.cli had no
    # `__main__` guard, so `python -m asteria_runtime.cli goal …` imported, ran
    # nothing, and exited 0 — background runs never executed their goal (S88).
    argv = build_background_goal_argv(tmp_path, "demo goal")
    module = argv[argv.index("-m") + 1]
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip(), "module entry produced no output — silent no-op"


def test_pid_is_alive_observes_without_killing() -> None:
    # os.kill(pid, 0) on Windows is TerminateProcess: the old probe killed the very
    # process it was checking. The probe must observe, never touch.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert _pid_is_alive(proc.pid) is True
        time.sleep(0.2)
        assert proc.poll() is None, "probe killed the process it was checking"
    finally:
        proc.kill()
        proc.wait(timeout=10)
    assert _pid_is_alive(proc.pid) is False
    assert _pid_is_alive(0) is False
    assert _pid_is_alive(-1) is False


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


def test_start_local_background_run_writes_log_path(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")

    class _FakeProcess:
        pid = 616161
        returncode: int | None = None

    def fake_spawn(command: list[str], **kwargs: object) -> _FakeProcess:
        stdout = kwargs.get("stdout")
        if stdout is not None and hasattr(stdout, "write"):
            stdout.write("spawn ok\n")
        return _FakeProcess()

    entry = start_local_background_run(
        tmp_path,
        "log me",
        validator,
        spawn=fake_spawn,
    )
    assert entry.get("log_path")
    log_file = tmp_path / str(entry["log_path"])
    assert log_file.exists()
    assert "spawn ok" in log_file.read_text(encoding="utf-8")


def test_background_command_start_requires_goal(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    try:
        BackgroundRunCommand(tmp_path, action="start", goal=None).run()
        raised = False
    except ValueError:
        raised = True
    assert raised is True


def test_refresh_attaches_log_tail_on_completion(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    log_dir = tmp_path / ".asteria" / "background_logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "bg-test.log"
    log_path.write_text("line1\nline2\nfinal line\n", encoding="utf-8")
    registry = BackgroundRunRegistry(tmp_path)
    registry.append_run(
        {
            "background_run_id": "bg-test",
            "status": "running",
            "goal": "demo",
            "pid": 9999,
            "local_subprocess": True,
            "cloud_vm": False,
            "log_path": ".asteria/background_logs/bg-test.log",
            "started_at": "2026-06-06T12:00:00+08:00",
            "updated_at": "2026-06-06T12:00:00+08:00",
        }
    )
    with patch("asteria_runtime.core.local_background_run._pid_is_alive", return_value=False):
        with patch("asteria_runtime.core.local_background_run._poll_exit_code", return_value=0):
            data = registry.refresh_statuses()
    run = data["runs"][0]
    assert run["status"] == "completed"
    assert "final line" in str(run.get("log_tail"))
    assert "final line" in run["summary"]
