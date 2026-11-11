from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from asteria_runtime.agents.planner import RequirementPlanner
from asteria_runtime.commands.replan_command import ReplanCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.agent_tool_surface import model_tool_surface
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.task_verification import declared_commands, declared_observations
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.core.verification_revision import load_method_authority, method_provenance, revise_method
from asteria_runtime.core.worker_transport import tool_definitions_for
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator
from asteria_runtime.tools.defaults import create_default_tool_registry
from tests.unit.test_goal_spec_agent import valid_goal_spec_json
from tests.unit.test_replan_verified_noop import _evidence


OLD = f'"{sys.executable}" -c "raise RuntimeError(\'defective method\')"'
NEW = f'"{sys.executable}" -c "assert 2 + 2 == 4"'
REQUIRED = "python -m pytest original_tests -q"
ARGS = {"original_command": OLD, "replacement_command": NEW,
        "reason": "The proposed checker raises unconditionally instead of exercising the claim",
        "coverage": "Retain the same arithmetic claim and the separate original project suite"}


def setup_run(tmp_path, *, kind="implementation"):
    (tmp_path / "AGENTS.md").write_text("Preserve the requested artifact and original checks.\n", encoding="utf-8")
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    project = JsonStore(validator).read(tmp_path / ".asteria" / "project.json", "project_config")
    goal = json.loads(valid_goal_spec_json())
    goal["verification_strategy"] = [REQUIRED]
    task = RequirementPlanner().finalize_model_tasks([{
        "title": "Check arithmetic artifact", "description": "Check the scoped claim",
        "task_kind": kind, "acceptance": ["Arithmetic claim and original suite pass"],
        "expected_artifacts": ["answer.txt"], "expected_changed_files": ["answer.txt"],
        "validation_commands": [OLD, REQUIRED],
        "verification_policy": {"method_provenance": {"revisable_commands": [REQUIRED]}},
    }], goal, {"root_guidance": {"content": (tmp_path / "AGENTS.md").read_text(encoding="utf-8"),
                               "truncated": False}, "project_commands": project["commands"]})[0]
    task["status"] = "in_progress"
    if kind == "verification":
        task["write_scope"] = []
        task["expected_changed_files"] = []
        task["parallel_safety"] = "readonly"
    validator = SchemaValidator(Path("schemas"))
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    store = JsonStore(validator)
    store.write(run_dir / "goal_spec.json", goal, "goal_spec")
    store.write(run_dir / "task_plan.json", {"schema_version": "0.1.0", "tasks": [task]}, "task_board")
    context = RuntimeContext(tmp_path, "run-1", {
        "permissions": {"allow_shell": True}, "protected_paths": [], "permission_mode": "auto",
    }, validator)
    gateway = ToolExecutionGateway(create_default_tool_registry(), ToolPermissionPolicy(tmp_path, validator))
    return task, goal, context, gateway


def run_commands(task, context, gateway):
    return gateway.run_tool_calls([
        {"tool_name": "run_command", "args": {"command": OLD}},
        {"tool_name": "run_command", "args": {"command": NEW}},
    ], task, context, stop_on_failure=False)


def records(context):
    return JsonlStore(context.validator).read_all(context.run_dir / "tool_observations.jsonl", "tool_observation")


def test_explicit_revision_updates_live_contract_and_preserves_failure(tmp_path):
    task, goal, context, gateway = setup_run(tmp_path)
    before = deepcopy(task)
    results = run_commands(task, context, gateway)
    assert not results[0].ok and results[1].ok
    observations = [r.harness_observation for r in results]
    assert not declared_observations(task, observations)[0].ok
    prefix = (context.run_dir / "tool_observations.jsonl").read_bytes()
    result = gateway.run_tool_calls([
        {"tool_name": "revise_verification", "args": ARGS},
    ], task, context, stop_on_failure=False)[0]
    assert result.ok, result.error
    assert declared_commands(task) == [NEW, REQUIRED]
    selected = declared_observations(task, observations)
    assert selected[0].ok and not selected[1].ok  # user suite still mandatory
    assert selected[1].data["command"] == REQUIRED
    durable = TaskBoard(context.run_dir / "task_plan.json", context.validator).get_task(task["task_id"])
    assert durable["verification_policy"] == task["verification_policy"]
    history = durable["verification_policy"]["method_revisions"]
    assert history[0]["failed_observation_id"] == records(context)[0]["observation_id"]
    assert history[0]["passed_observation_id"] == records(context)[1]["observation_id"]
    assert (context.run_dir / "tool_observations.jsonl").read_bytes().startswith(prefix)
    for key in ("acceptance", "completion_contract", "write_scope", "expected_changed_files"):
        assert task[key] == before[key]
    assert JsonStore(context.validator).read(context.run_dir / "goal_spec.json", "goal_spec") == goal


def test_planner_provenance_ignores_model_grants_and_protects_quoted_user_checks(tmp_path):
    task, goal, _, _ = setup_run(tmp_path)
    assert task["verification_policy"]["method_provenance"]["revisable_commands"] == [OLD]
    goal["original_goal"] = f"Run the exact check `{OLD}` unchanged"
    assert method_provenance([OLD, REQUIRED], goal, {"root_guidance": {}, "project_commands": {}})["revisable_commands"] == []
    provenance = method_provenance([OLD, REQUIRED], goal, {
        "root_guidance": {"content": REQUIRED, "truncated": False},
        "project_commands": {},
    })
    assert provenance["revisable_commands"] == []
    assert method_provenance([OLD], goal, {}) is None
    assert method_provenance([OLD], goal, {"root_guidance": {"content": "x", "truncated": True}}) is None
    goal["original_goal"] = "A generic goal"
    assert method_provenance([OLD], goal, {"root_guidance": {}, "project_commands": {"test": OLD}})["revisable_commands"] == []
    assert method_provenance(["python -m pytest -q"], goal, {
        "root_guidance": {}, "project_commands": {"test": "python -m pytest"},
    })["revisable_commands"] == []


@pytest.mark.parametrize("case", [
    "legacy", "protected", "changed_goal", "changed_guidance", "other_task", "missing",
    "not_executed", "nonzero_replacement", "expected_nonzero", "replacement_before_failure",
    "stale", "side_effect", "unknown_scan", "already_fixed", "blank_reason", "blank_coverage",
    "terminal", "inconsistent", "duplicate", "changed_project_commands",
])
def test_revision_refuses_missing_authority_or_inadequate_evidence(tmp_path, case):
    task, goal, context, gateway = setup_run(tmp_path)
    run_commands(task, context, gateway)
    rows = deepcopy(records(context))
    initial_guidance = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    initial_commands = JsonStore(context.validator).read(context.asteria_dir / "project.json", "project_config")["commands"]
    assert revise_method(task, goal, initial_guidance, initial_commands, rows, **ARGS)["validation_commands"] == [NEW, REQUIRED]
    args = dict(ARGS)
    guidance = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    project_commands = JsonStore(context.validator).read(context.asteria_dir / "project.json", "project_config")["commands"]
    if case == "legacy":
        task["verification_policy"].pop("method_provenance")
    elif case == "protected":
        args["original_command"] = REQUIRED
    elif case == "changed_goal":
        goal["constraints"].append("new requirement")
    elif case == "changed_guidance":
        guidance = "new project instructions"
    elif case == "other_task":
        rows[1]["task_id"] = "other"
    elif case == "missing":
        rows.pop()
    elif case == "not_executed":
        rows[0]["observation"]["data"]["returncode"] = None
    elif case == "nonzero_replacement":
        rows[1]["observation"]["data"]["returncode"] = 1
    elif case == "expected_nonzero":
        rows[0]["observation"]["ok"] = True
    elif case == "replacement_before_failure":
        rows.reverse()
    elif case == "stale":
        row = deepcopy(rows[1])
        row["observation"]["tool_name"] = "write_file"
        rows.append(row)
    elif case == "side_effect":
        rows[1]["observation"]["data"]["workspace_changes"]["created"] = ["db.json"]
    elif case == "unknown_scan":
        rows[1]["observation"]["data"]["workspace_scan"] = "unavailable"
    elif case == "already_fixed":
        rows[0]["observation"]["ok"] = True
    elif case == "blank_reason":
        args["reason"] = " "
    elif case == "blank_coverage":
        args["coverage"] = " "
    elif case == "terminal":
        task["status"] = "done"
    elif case == "inconsistent":
        task["verification_policy"]["commands"] = []
    elif case == "duplicate":
        args["replacement_command"] = REQUIRED
    elif case == "changed_project_commands":
        project_commands["test"] = "new-test-command"
    before = deepcopy(task)
    with pytest.raises((PermissionError, ValueError)):
        revise_method(task, goal, guidance, project_commands, rows, **args)
    assert task == before


def test_legacy_task_and_budget_denial_leave_board_unchanged(tmp_path):
    task, _, context, gateway = setup_run(tmp_path)
    run_commands(task, context, gateway)
    path = context.run_dir / "task_plan.json"
    before = path.read_bytes()
    budget = BudgetController({"budgets": {"max_tool_calls_per_goal": 0}}, "run-1")
    result = gateway.run_tool_calls([{"tool_name": "revise_verification", "args": ARGS}],
                                    task, replace(context, budget=budget), stop_on_failure=False)[0]
    assert not result.ok and path.read_bytes() == before
    assert budget.usage.tool_calls == 1
    # A spoofed task_id argument cannot select another task at the registry boundary.
    result = gateway.run_tool_calls([
        {"tool_name": "revise_verification", "args": {**ARGS, "task_id": "other"}},
    ], task, context, stop_on_failure=False)[0]
    assert result.ok and result.data["task_id"] == task["task_id"]
    assert path.read_bytes() != before


def test_readonly_revision_has_no_artifact_write_authority_and_replan_keeps_history(tmp_path):
    task, goal, context, gateway = setup_run(tmp_path, kind="verification")
    run_commands(task, context, gateway)
    result = gateway.run_tool_calls([{"tool_name": "revise_verification", "args": ARGS}],
                                    task, context, stop_on_failure=False)[0]
    assert result.ok, result.error
    assert not task["write_scope"] and "write_file" not in task["allowed_tools"]
    board = TaskBoard(context.run_dir / "task_plan.json", context.validator)
    child = ReplanCommand(tmp_path, "run-1")._task_from_failure(board, task, _evidence([]))
    assert child["verification_policy"]["method_provenance"] == task["verification_policy"]["method_provenance"]
    assert child["verification_policy"]["method_revisions"] == task["verification_policy"]["method_revisions"]
    assert declared_commands(child) == [NEW, REQUIRED]
    assert not child["write_scope"]
    assert goal["verification_strategy"] == [REQUIRED]


def test_revision_schema_rejects_missing_evidence_reference(tmp_path):
    task, _, context, _ = setup_run(tmp_path)
    task["verification_policy"]["method_revisions"] = [{"reason": "bad"}]
    with pytest.raises(SchemaValidationError):
        context.validator.validate("task", task)


def test_revision_is_exposed_in_json_and_native_surfaces_only_with_a_backend():
    registry = create_default_tool_registry()
    tools = {t["name"]: t for t in model_tool_surface(registry.names(), allow_shell=True)}
    assert tools["revise_verification"]["status"] == "available"
    native = tool_definitions_for(["revise_verification"])
    assert native[0]["function"]["name"] == "revise_verification"
    assert set(native[0]["function"]["parameters"]["required"]) == set(ARGS)
    assert tool_definitions_for([]) == []


def test_guidance_tail_is_protected_without_expanding_model_prompt(tmp_path):
    goal = {"original_goal": "Preserve all checks"}
    (tmp_path / "AGENTS.md").write_text("x" * 4500 + "\n" + OLD, encoding="utf8")
    authority = load_method_authority(tmp_path, {})
    provenance = method_provenance([OLD, NEW], goal, {"verification_authority": authority})
    assert provenance["revisable_commands"] == [NEW]
    (tmp_path / "AGENTS.md").write_text("x" * 262_145, encoding="utf8")
    assert load_method_authority(tmp_path, {}) is None
    assert method_provenance([OLD], goal, {"verification_authority": None}) is None


def test_adopting_a_protected_check_never_grants_future_revision_authority(tmp_path):
    task, goal, context, gateway = setup_run(tmp_path)
    run_commands(task, context, gateway)
    goal["definition_of_done"].append(f"Preserve the exact command `{NEW}`")
    guidance = (tmp_path / "AGENTS.md").read_text(encoding="utf8")
    project_commands = JsonStore(context.validator).read(context.asteria_dir / "project.json", "project_config")["commands"]
    task["verification_policy"]["method_provenance"] = method_provenance([OLD, REQUIRED], goal, {
        "root_guidance": {"content": guidance, "truncated": False}, "project_commands": project_commands,
    })
    changed = revise_method(task, goal, guidance, project_commands, records(context), **ARGS)
    assert changed["validation_commands"] == [NEW, REQUIRED]
    assert NEW not in changed["verification_policy"]["method_provenance"]["revisable_commands"]
