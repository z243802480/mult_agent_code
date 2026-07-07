from pathlib import Path

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_hooks import RuntimeHookManager
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_runtime_hook_manager_records_hook_and_event(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)
    manager = RuntimeHookManager(validator)

    record = manager.emit(
        context,
        "before_worker",
        "worker",
        "WorkerRunner",
        "Starting worker",
        task={"task_id": "task-0001"},
        worker_invocation_id="worker-0001",
    )

    hooks = JsonlStore(validator).read_all(tmp_path / "runtime_hooks.jsonl", "runtime_hook_event")
    events = JsonlStore(validator).read_all(tmp_path / "events.jsonl", "event")
    assert record == hooks[0]
    assert hooks[0]["hook_name"] == "before_worker"
    assert hooks[0]["task_id"] == "task-0001"
    assert events[0]["type"] == "runtime_hook_emitted"


def test_runtime_hook_handler_failure_is_audited_not_raised(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)

    def failing_handler(_record: dict) -> None:
        raise RuntimeError("boom")

    manager = RuntimeHookManager(validator, handlers=[failing_handler])

    manager.emit(context, "after_worker", "worker", "WorkerRunner", "Done")

    events = JsonlStore(validator).read_all(tmp_path / "events.jsonl", "event")
    assert [event["type"] for event in events] == [
        "runtime_hook_emitted",
        "runtime_hook_handler_failed",
    ]
    assert events[1]["data"]["error"] == "boom"


def test_runtime_hook_manager_redacts_sensitive_data(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)
    manager = RuntimeHookManager(validator)

    manager.emit(
        context,
        "after_tool_call",
        "tool",
        "ToolExecutionGateway",
        "Finished tool",
        data={
            "api_key": "secret-value",
            "nested": {"token": "also-secret", "safe": "visible"},
        },
    )

    hooks = JsonlStore(validator).read_all(tmp_path / "runtime_hooks.jsonl", "runtime_hook_event")
    assert hooks[0]["data"]["api_key"] == "<redacted>"
    assert hooks[0]["data"]["nested"]["token"] == "<redacted>"
    assert hooks[0]["data"]["nested"]["safe"] == "visible"


def test_runtime_hook_manager_blocks_disallowed_hook_name(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)
    manager = RuntimeHookManager(validator)
    manager.configure({"hooks": {"allowed_hook_names": ["after_tool_call"]}})

    record = manager.emit(
        context,
        "before_tool_call",
        "tool",
        "ToolExecutionGateway",
        "Starting tool",
    )

    assert record is None
    assert not (tmp_path / "runtime_hooks.jsonl").exists()
    events = JsonlStore(validator).read_all(tmp_path / "events.jsonl", "event")
    assert events[0]["type"] == "runtime_hook_blocked"


def test_dispatch_control_merges_handler_decisions(tmp_path: Path) -> None:
    from asteria_runtime.core.runtime_hooks import RuntimeHookDecision

    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)

    def reminder(_record: dict) -> RuntimeHookDecision:
        return RuntimeHookDecision(additional_context="remember to verify")

    def guardrail(_record: dict) -> RuntimeHookDecision:
        return RuntimeHookDecision(additional_context="artifact missing", continue_turn=True)

    manager = RuntimeHookManager(validator, control_handlers=[reminder, guardrail])

    decision = manager.dispatch_control(
        context, "pre_final", "execute", "ExecuteCommand", "model wants to stop",
        task={"task_id": "task-0001"},
    )

    assert decision.continue_turn is True
    assert "remember to verify" in decision.additional_context
    assert "artifact missing" in decision.additional_context
    # The control event is still recorded like any hook (audit trail).
    hooks = JsonlStore(validator).read_all(tmp_path / "runtime_hooks.jsonl", "runtime_hook_event")
    assert hooks[0]["hook_name"] == "pre_final"


def test_dispatch_control_returns_empty_when_no_handlers(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)
    manager = RuntimeHookManager(validator)

    decision = manager.dispatch_control(context, "turn_start", "execute", "ExecuteCommand", "turn")

    assert decision.continue_turn is False and decision.additional_context == ""


def test_dispatch_control_handler_failure_is_audited_not_raised(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = _context(tmp_path, validator)

    def boom(_record: dict):
        raise RuntimeError("control boom")

    manager = RuntimeHookManager(validator, control_handlers=[boom])
    decision = manager.dispatch_control(context, "turn_start", "execute", "ExecuteCommand", "turn")

    assert decision.continue_turn is False
    events = JsonlStore(validator).read_all(tmp_path / "events.jsonl", "event")
    assert any(event["type"] == "runtime_hook_control_failed" for event in events)


def _context(tmp_path: Path, validator: SchemaValidator) -> RuntimeContext:
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        event_logger=EventLogger(tmp_path / "events.jsonl", validator),
        run_dir_override=tmp_path,
    )
