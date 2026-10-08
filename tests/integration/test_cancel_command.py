import json
from pathlib import Path

from asteria_runtime.commands.cancel_command import CancelCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.core.workspace_writer_lock import workspace_writer_lock
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator

from tests.integration.test_plan_command import FakePlanClient


def _validator() -> SchemaValidator:
    return SchemaValidator(Path(__file__).resolve().parents[2] / "schemas")


def _zombie_run(tmp_path: Path) -> str:
    """A run whose loop had work left when its process was killed: status=running, no ended_at."""
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    run_store = RunStore(tmp_path / ".asteria", _validator())
    run = run_store.load_run(plan.run_id)
    if run["status"] != "running":
        run["status"] = "running"
        run["ended_at"] = None
        run_store.update_run(run)
    return plan.run_id


def test_cancel_finalizes_a_zombie_run(tmp_path: Path) -> None:
    run_id = _zombie_run(tmp_path)
    result = CancelCommand(tmp_path).run()
    assert result.ok and result.status == "cancelled"
    run = RunStore(tmp_path / ".asteria", _validator()).load_run(run_id)
    assert run["status"] == "cancelled", "the record must stop claiming a dead run is working"
    assert run["ended_at"], "a cancelled run is terminal and needs its end timestamp"
    events = (tmp_path / ".asteria" / "runs" / run_id / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert "run_cancelled" in events


def test_cancel_refuses_while_the_writer_lock_is_held(tmp_path: Path) -> None:
    # A held lock means the run is genuinely alive — "cancel" must never be how a live run gets
    # declared dead. (In-process the lock is re-entrant, so holding it here simulates exactly that.)
    _zombie_run(tmp_path)
    with workspace_writer_lock(tmp_path, command="execute", goal="still working"):
        result = CancelCommand(tmp_path).run()
    assert result.status == "alive"
    assert RunStore(tmp_path / ".asteria", _validator()).current_session_id() is not None


def test_cancel_is_idempotent_over_a_settled_run(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    result = CancelCommand(tmp_path).run()
    # The plan run settles itself (planning completes) — cancel must leave that record alone.
    assert result.status == "already_settled"
    run = RunStore(tmp_path / ".asteria", _validator()).load_run(plan.run_id)
    assert run["status"] != "cancelled"


def test_cancel_survives_a_missing_current_run(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    result = CancelCommand(tmp_path).run()
    assert result.status == "not_found"
