from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.core.session_continuation import (
    assess_session_continuation,
    prepare_session_follow_up,
)
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
    assert follow["write_scope"] == ["implementation artifact"]

    run = store.read(tmp_path / ".asteria" / "runs" / run_id / "run.json", "run")
    assert run["status"] == "running"
    assert run["current_phase"] == "EXECUTE"

    goal_spec = store.read(tmp_path / ".asteria" / "runs" / run_id / "goal_spec.json", "goal_spec")
    assert goal_spec["continuation_goal"] == "Add --quiet and a pytest for it."
