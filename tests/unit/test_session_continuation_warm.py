from __future__ import annotations

from pathlib import Path

import pytest

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.task_plan_quality_gate import TaskPlanQualityGate
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.session_continuation import (
    assess_session_continuation,
    prepare_session_follow_up,
)
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.session_result_service import SessionResultService
from asteria_runtime.tools.file_tools import ReadFileTool
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


from tests.integration.test_plan_command import FakePlanClient


def _write_accepted_session(root: Path, *, run_id: str | None = None) -> str:
    InitCommand(root).run()
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    plan = PlanCommand(root, "Add --version", model_client=FakePlanClient()).run()
    run_id = run_id or plan.run_id
    run_store = RunStore(root / ".asteria", validator)
    store = JsonStore(validator)
    run_dir = run_store.run_dir(run_id)
    run = run_store.load_run(run_id)
    run["status"] = "completed"
    run["current_phase"] = "ACCEPTED"
    run["summary"] = "Accepted"
    run_store.update_run(run)
    task_plan = store.read(run_dir / "task_plan.json", "task_board")
    for task in task_plan.get("tasks") or []:
        task["status"] = "done"
    store.write(run_dir / "task_plan.json", task_plan, "task_board")
    run_store.set_current_session(run_id, "test_accepted")
    return run_id


def test_assess_session_continuation_requires_accepted_session(tmp_path: Path) -> None:
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    InitCommand(tmp_path).run()
    assert assess_session_continuation(tmp_path, validator=validator) is None

    _write_accepted_session(tmp_path)
    eligibility = assess_session_continuation(tmp_path, validator=validator)
    assert eligibility is not None
    assert eligibility.run_id.startswith("run-")


def test_prepare_session_follow_up_requeues_task_without_new_run(tmp_path: Path) -> None:
    run_id = _write_accepted_session(tmp_path)
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    store = JsonStore(validator)

    prepare_session_follow_up(
        tmp_path,
        run_id,
        "Add --quiet and a pytest for it.",
        validator=validator,
    )

    task_plan = store.read(tmp_path / ".asteria" / "runs" / run_id / "task_plan.json", "task_board")
    # A follow-up appends a FRESH task; the prior task keeps its completed status (never hijacked).
    prior = task_plan["tasks"][0]
    assert prior["status"] in {"done", "completed", "accepted"}
    follow = task_plan["tasks"][-1]
    assert follow["task_id"] != prior["task_id"]
    assert follow["status"] == "ready"
    assert "quiet" in follow["description"].lower()
    # The new task must NOT inherit the prior goal's write scope — it gets an open implementation
    # scope so the model can create whatever files the new instruction needs.
    assert "implementation artifact" in follow["write_scope"]

    run = store.read(tmp_path / ".asteria" / "runs" / run_id / "run.json", "run")
    assert run["status"] == "running"
    assert run["current_phase"] == "EXECUTE"

    goal_spec = store.read(tmp_path / ".asteria" / "runs" / run_id / "goal_spec.json", "goal_spec")
    assert goal_spec["continuation_goal"] == "Add --quiet and a pytest for it."


def test_follow_up_can_read_workspace_context_without_granting_extra_writes(tmp_path: Path) -> None:
    run_id = _write_accepted_session(tmp_path)
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    prepare_session_follow_up(tmp_path, run_id, "Use the design in context/spec.rst.", validator=validator)
    task_plan = JsonStore(validator).read(
        tmp_path / ".asteria/runs" / run_id / "task_plan.json", "task_board")
    follow = task_plan["tasks"][-1]
    policy = ToolPermissionPolicy(tmp_path, validator)
    policy.enforce_tool_permission_profile(follow, "read_file", {"path": "context/spec.rst"})
    with pytest.raises(PermissionError):
        policy.enforce_tool_permission_profile(follow, "write_file", {"path": "context/spec.rst"})
    context = RuntimeContext(root=tmp_path, run_id=run_id, policy={"protected_paths": [".env"]},
                             validator=validator)
    for path in (".env", "../outside.md"):
        with pytest.raises(PermissionError):
            ReadFileTool().run(context, path)


def test_follow_up_preserves_completed_tasks_ledger_and_cumulative_budget(tmp_path: Path) -> None:
    run_id = _write_accepted_session(tmp_path)
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    store = JsonStore(validator)
    run_dir = tmp_path / ".asteria/runs" / run_id
    previous = store.read(run_dir / "task_plan.json", "task_board")["tasks"]
    budget = BudgetController({"budgets": {"max_model_calls_per_goal": 200}}, run_id=run_id)
    budget.record_model_call(input_tokens=12, output_tokens=3)
    store.write(run_dir / "cost_report.json", budget.cost_report(), "cost_report")
    ledger = run_dir / "model_calls.jsonl"
    JsonlStore(validator).append(ledger, {
        "schema_version": "0.1.0", "model_call_id": "modelcall-0001", "run_id": run_id,
        "model_name": "fixture", "model_provider": "fake", "model_tier": "medium",
        "purpose": "prior execution", "status": "success", "created_at": "2026-11-11T00:00:00Z",
        "input_tokens": 12, "output_tokens": 3,
    }, "model_call")
    before = {p.name: p.read_bytes() for p in (run_dir / "cost_report.json", ledger)}
    prepare_session_follow_up(tmp_path, run_id, "Add another feature.", validator=validator)
    tasks = store.read(run_dir / "task_plan.json", "task_board")["tasks"]
    assert tasks[:-1] == previous
    assert {p.name: p.read_bytes() for p in (run_dir / "cost_report.json", ledger)} == before
    restored = BudgetController.from_report(budget.policy,
        store.read(run_dir / "cost_report.json", "cost_report"))
    restored.record_model_call(input_tokens=7, output_tokens=2)
    assert restored.usage.model_calls == 2
    assert restored.usage.estimated_input_tokens == budget.usage.estimated_input_tokens + 7


def test_follow_up_criteria_and_verification_do_not_reuse_the_previous_goal(tmp_path: Path) -> None:
    run_id = _write_accepted_session(tmp_path)
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    store = JsonStore(validator)
    path = tmp_path / ".asteria/runs" / run_id / "task_plan.json"
    plan = store.read(path, "task_board")
    plan["tasks"][0]["verification_policy"] = {
        "required": True, "commands": ["python previous.py"], "command_source": "planner_task",
        "readback_paths": ["previous.py"],
    }
    store.write(path, plan, "task_board")
    before = plan["tasks"][:]
    goal = "Create a calculator and test its addition behavior."
    prepare_session_follow_up(tmp_path, run_id, goal, validator=validator)
    TaskPlanQualityGate(tmp_path, validator).check(run_id, blocking=False)
    tasks = store.read(path, "task_board")["tasks"]
    assert tasks[:-1] == before
    assert goal in tasks[-1]["acceptance"][0]
    assert tasks[-1]["expected_artifacts"] == ["implementation artifact"]
    assert tasks[-1]["verification_policy"] == {"required": True, "allow_expected_failure": False,
                                               "commands": []}


def test_follow_up_archives_previous_review_without_claiming_new_work_passed(tmp_path: Path) -> None:
    run_id = _write_accepted_session(tmp_path)
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    store = JsonStore(validator)
    run_dir = tmp_path / ".asteria/runs" / run_id
    report = {"schema_version": "0.1.0", "run_id": run_id,
              "overall": {"status": "pass", "score": 1.0, "reason": "previous goal"},
              **{key: {} for key in ("goal_eval", "artifact_eval", "outcome_eval", "trajectory_eval", "cost_eval")}}
    store.write(run_dir / "eval_report.json", report, "eval_report")
    old = (run_dir / "eval_report.json").read_bytes()
    service = SessionResultService(tmp_path, validator)
    assert service.latest_review_status(run_id) == "pass"
    prepare_session_follow_up(tmp_path, run_id, "Add new behavior and tests.", validator=validator)
    assert service.latest_review_status(run_id) == "unknown"
    task_id = store.read(run_dir / "task_plan.json", "task_board")["tasks"][-1]["task_id"]
    assert (run_dir / "continuations" / task_id / "eval_report.json").read_bytes() == old
    report["overall"] = {"status": "partial", "score": 0.5, "reason": "new goal"}
    store.write(run_dir / "eval_report.json", report, "eval_report")
    assert service.latest_review_status(run_id) == "partial"


def test_follow_up_supports_observed_flat_package_without_granting_system_directories(tmp_path):
    run_id = _write_accepted_session(tmp_path)
    for name in ('tinydb', 'notes', 'secrets', '.private', 'node_modules', 'build'):
        (tmp_path / name).mkdir()
    validator = SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")
    prepare_session_follow_up(tmp_path, run_id, "Implement snapshot and add tests.", validator=validator)
    task = JsonStore(validator).read(
        tmp_path / '.asteria/runs' / run_id / 'task_plan.json', 'task_board')['tasks'][-1]
    policy = ToolPermissionPolicy(tmp_path, validator)
    for path in ('tinydb/database.py', 'notes/helper.py', 'tests/test_snapshot.py'):
        policy.enforce_tool_permission_profile(task, 'write_file', {'path': path})
    for path in ('secrets/key.py', '.private/config.py', 'node_modules/pkg/a.py',
                 'build/output.py', 'unknown_package/a.py', '.asteria/policy.py'):
        with pytest.raises(PermissionError):
            policy.enforce_tool_permission_profile(task, 'write_file', {'path': path})
