import json

import pytest

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.core.agent_tool_surface import model_tool_surface
from asteria_runtime.core.worker_transport import tool_definitions_for
from asteria_runtime.tools.command_tools import RunCommandTool, RunTestsTool
from tests.integration.test_plan_command import FakePlanClient
from tests.integration.test_execute_command import FakeModelDrivenClient
from tests.integration.test_tool_registry import context


def test_timeout_is_exposed_in_model_and_native_contracts():
    native = {s["function"]["name"]: s["function"] for s in tool_definitions_for(["run_command", "run_tests"])}
    for name in native:
        assert native[name]["parameters"]["properties"]["timeout_seconds"]["minimum"] == 1
    surface = {s["name"]: s for s in model_tool_surface(["run_command", "run_tests"])}
    assert "timeout_seconds" in surface["shell"]["parameter_contract"]
    assert "timeout_seconds" in surface["run_tests"]["parameter_contract"]


@pytest.mark.parametrize("timeout", [0, -1, True, "10", float("inf")])
def test_invalid_timeout_does_not_execute_command(tmp_path, timeout):
    result = RunCommandTool().run(context(tmp_path),
        'python -c "from pathlib import Path; Path(\'must-not-run\').write_text(\'bad\')"',
        timeout_seconds=timeout)
    assert not result.ok and result.error == "invalid_timeout"
    assert not (tmp_path / "must-not-run").exists()


def test_actual_timeout_stays_failed_and_defaults_are_unchanged(tmp_path):
    assert RunCommandTool().default_timeout_seconds == 60
    assert RunTestsTool().command_tool.default_timeout_seconds == 120
    result = RunTestsTool().run(context(tmp_path), 'python -c "import time; time.sleep(2)"', timeout_seconds=1)
    assert not result.ok and result.error == "timeout"


def test_declared_timeout_reaches_the_original_tool_without_command_rewrite(tmp_path, monkeypatch):
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run_dir = tmp_path / ".asteria/runs" / plan.run_id
    path = run_dir / "task_plan.json"
    board = json.loads(path.read_text(encoding="utf-8"))
    task = board["tasks"][0]
    command = 'python -c "from src.notes_tool import add_note; assert add_note([], chr(120)) == [chr(120)]"'
    task["validation_commands"] = [command]
    task["verification_policy"].update({"command_source": "planner_task", "timeout_seconds": 321})
    path.write_text(json.dumps(board), encoding="utf-8")
    actual = RunTestsTool.run
    seen = []
    def capture(self, context, command, timeout_seconds=None):
        seen.append((command, timeout_seconds))
        return actual(self, context, command, timeout_seconds=timeout_seconds)
    monkeypatch.setattr(RunTestsTool, "run", capture)
    result = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeModelDrivenClient()).run()
    assert result.completed == 1
    assert (command, 321) in seen
