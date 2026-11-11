import json

import pytest

from asteria_runtime.commands.replan_command import ReplanCommand
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.task_contract import with_goal_edit_boundary, write_scope
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidationError
from asteria_runtime.tools.file_tools import WriteFileTool
from asteria_runtime.tools.registry import ToolRegistry
from tests.unit.test_goal_spec_agent import valid_goal_spec_json
from tests.unit.test_replan_verified_noop import _board, _evidence


def restricted(*paths):
    return {"mode": "restricted", "paths": list(paths)}


OPEN = {"mode": "open", "paths": []}


def repair(root, parent_boundary=None, goal_boundary=None):
    board = _board(root)
    source = _evidence([])["task"]
    if parent_boundary is not None:
        source["edit_boundary"] = parent_boundary
    if goal_boundary is not None:
        goal = json.loads(valid_goal_spec_json())
        goal["edit_boundary"] = goal_boundary
        JsonStore(board.validator).write(board.path.parent / "goal_spec.json", goal, "goal_spec")
    command = ReplanCommand(root, "run-1")
    child = command._task_from_failure(board, source, _evidence(["verification did not pass"]))
    return board, command, source, child


@pytest.mark.parametrize("parent,goal,expected", [
    (None, None, None),
    (restricted("docs/usage.rst"), None, restricted("docs/usage.rst")),
    (None, restricted("docs/usage.rst"), restricted("docs/usage.rst")),
    (OPEN, restricted("docs/usage.rst"), restricted("docs/usage.rst")),
    (restricted("docs/usage.rst"), OPEN, restricted("docs/usage.rst")),
    (restricted("docs/"), restricted("docs/usage.rst"), restricted("docs/usage.rst")),
    (restricted("docs/usage.rst"), restricted("docs/"), restricted("docs/usage.rst")),
    (restricted("docs/a.rst"), restricted("docs/b.rst"), restricted()),
    (restricted(), restricted("docs/"), restricted()),
    (None, OPEN, OPEN),
])
def test_replan_keeps_the_intersection_of_parent_and_goal_authority(tmp_path, parent, goal, expected):
    board, command, source, child = repair(tmp_path, parent, goal)
    assert child.get("edit_boundary") == expected
    board.add_task(child)
    grandchild = command._task_from_failure(board, child, _evidence(["verification did not pass"]))
    assert grandchild.get("edit_boundary") == expected
    assert source.get("edit_boundary") == parent


def test_inherited_ceiling_survives_a_broader_request_and_real_write_tool(tmp_path):
    board, _, _, child = repair(tmp_path, restricted("docs/"), restricted("docs/usage.rst"))
    child["write_scope"] = ["docs/", "tests/"]  # A requested scope is not a new authorization.
    assert write_scope(child) == ["docs/usage.rst"]
    tools = ToolRegistry()
    tools.register(WriteFileTool())
    context = RuntimeContext(tmp_path, "run-1", {"permission_mode": "auto", "permissions": {},
        "protected_paths": []}, board.validator)
    gateway = ToolExecutionGateway(tools, ToolPermissionPolicy(tmp_path, board.validator))
    with pytest.raises(PermissionError, match="edit_boundary"):
        gateway.run_tool_calls([{"tool_name": "write_file", "args": {
            "path": "docs/unrequested.rst", "content": "must not write"}}], child, context)
    assert not (tmp_path / "docs/unrequested.rst").exists()
    gateway.run_tool_calls([{"tool_name": "write_file", "args": {
        "path": "docs/usage.rst", "content": "authorized"}}], child, context)
    assert (tmp_path / "docs/usage.rst").read_text() == "authorized"


def test_invalid_parent_boundary_cannot_silently_become_open(tmp_path):
    with pytest.raises(SchemaValidationError):
        repair(tmp_path, {"mode": "restricted", "paths": ["../outside"]})


def test_readonly_recovery_stays_readonly_with_a_goal_boundary(tmp_path):
    board, command, source, _ = repair(tmp_path, None, restricted("docs/"))
    source.update(task_kind="verification", write_scope=[])
    child = command._task_from_failure(board, source, _evidence(["verification did not pass"]))
    assert child["edit_boundary"] == restricted("docs/")
    assert child["write_scope"] == [] and child["parallel_safety"] == "readonly"


def test_execution_binding_restores_missing_or_open_task_ceiling_without_mutating_input():
    goal = {"edit_boundary": restricted("docs/usage.rst")}
    for task in ({"write_scope": ["docs/"]}, {"write_scope": ["docs/"], "edit_boundary": OPEN}):
        original = json.dumps(task)
        bound = with_goal_edit_boundary(task, goal)
        assert bound["edit_boundary"] == restricted("docs/usage.rst")
        assert write_scope(bound) == ["docs/usage.rst"]
        assert json.dumps(task) == original


def test_actual_execute_entry_enforces_goal_when_a_legacy_task_omits_the_ceiling(tmp_path):
    from asteria_runtime.commands.execute_command import ExecuteCommand
    from asteria_runtime.commands.init_command import InitCommand
    from asteria_runtime.commands.plan_command import PlanCommand
    from asteria_runtime.models.base import ChatResponse, TokenUsage
    from asteria_runtime.storage.jsonl_store import JsonlStore
    from tests.integration.test_plan_command import FakePlanClient

    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a tiny notes tool", model_client=FakePlanClient()).run()
    run = tmp_path / ".asteria/runs" / plan.run_id
    command = ExecuteCommand(tmp_path)
    store = JsonStore(command.validator)
    goal = store.read(run / "goal_spec.json", "goal_spec")
    goal["edit_boundary"] = restricted("docs/usage.rst")
    store.write(run / "goal_spec.json", goal, "goal_spec")
    original_goal = (run / "goal_spec.json").read_bytes()
    board = store.read(run / "task_plan.json", "task_board")
    board["tasks"][0].pop("edit_boundary", None)
    store.write(run / "task_plan.json", board, "task_board")
    policy_path = tmp_path / ".asteria/policies.json"
    policy = store.read(policy_path, "policy_config")
    policy["active_budget_profile"] = ""
    policy["permission_mode"] = "auto"
    policy["budgets"]["max_model_calls_per_goal"] = 8
    store.write(policy_path, policy, "policy_config")

    class Client:
        calls = 0

        def chat(self, request):
            self.calls += 1
            calls = [{"tool_name": "write_file", "args": {"path": "src/notes_tool.py",
                     "content": "unauthorized"}}] if self.calls == 1 else []
            return ChatResponse(json.dumps({"narration": "inspect", "tool_calls": calls,
                "done": not calls}), "stop", TokenUsage(1, 1, 2), "fake", "boundary-test", {})

    ExecuteCommand(tmp_path, model_client=Client()).run()
    records = JsonlStore(command.validator).read_all(run / "tool_calls.jsonl", "tool_call")
    assert any(row["tool_name"] == "write_file" and "edit_boundary" in (row.get("error") or "")
               for row in records)
    assert not (tmp_path / "src/notes_tool.py").exists()
    assert (run / "goal_spec.json").read_bytes() == original_goal
