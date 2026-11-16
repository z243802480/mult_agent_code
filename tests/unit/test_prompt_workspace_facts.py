import json
from pathlib import Path

from asteria_runtime.agents.goal_spec_agent import GoalSpecAgent
from asteria_runtime.agents.plan_agent import PlanAgent
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.execution_environment import command_execution_context
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.unit.test_goal_spec_agent import FakeClient, valid_goal_spec_json


def test_planning_uses_explicit_workspace_even_when_process_cwd_differs(tmp_path, monkeypatch):
    workspace = tmp_path / "actual project"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    runtime = ContextLoader(workspace, validator).load()
    facts = runtime["execution_environment"]
    assert facts["run_command_working_directory"] == str(workspace.resolve())
    client = FakeClient(valid_goal_spec_json())
    GoalSpecAgent(client, validator).generate("Add a section", {"runtime_context": runtime}, "run-1")
    goal_environment = json.loads(client.requests[0].messages[1].content.split("Execution environment: ", 1)[1].splitlines()[0])
    plan_prompt = PlanAgent(client, validator)._user_prompt({}, runtime, "session_agent")
    plan_environment = json.loads(plan_prompt.split("Execution environment: ", 1)[1].splitlines()[0])
    assert goal_environment == plan_environment == facts


def test_execution_uses_mounted_workspace_and_unknown_root_is_not_invented(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    facts = command_execution_context(candidate)
    _, user = ExecuteCommand(tmp_path)._model_driven_prompts(
        {}, {}, {}, [], {"execution_environment": facts},
    )
    assert json.loads(user)["execution_environment"] == facts
    assert "run_command_working_directory" not in command_execution_context()
