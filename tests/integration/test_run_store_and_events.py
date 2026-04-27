from pathlib import Path

from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


def test_run_store_creates_loads_and_updates_run(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    store = RunStore(tmp_path / ".agent", validator)

    run = store.create_run('agent run "hello"', goal_id="goal-0001")
    assert run["status"] == "running"
    assert (tmp_path / ".agent" / "runs" / run["run_id"] / "run.json").exists()

    loaded = store.load_run(run["run_id"])
    loaded["current_phase"] = "PLAN"
    store.update_run(loaded)

    assert store.load_run(run["run_id"])["current_phase"] == "PLAN"


def test_event_logger_records_jsonl_events(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path / "events.jsonl", SchemaValidator(Path("schemas")))

    logger.record("run-1", "run_started", "orchestrator", "Run started")
    logger.record("run-1", "phase_changed", "orchestrator", "INIT -> PLAN", {"from": "INIT", "to": "PLAN"})

    events = logger.read_all()
    assert [event["event_id"] for event in events] == ["event-0001", "event-0002"]
    assert events[1]["data"]["to"] == "PLAN"
