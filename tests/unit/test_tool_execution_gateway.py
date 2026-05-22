from pathlib import Path

import pytest

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_hooks import RuntimeHookManager
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.agent_harness import load_harness_observations
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


class FakeRegistry:
    def call(self, tool_name: str, _context: RuntimeContext, **kwargs: object) -> object:
        data = kwargs.get("data") if isinstance(kwargs.get("data"), dict) else {}
        if tool_name == "write_file" and isinstance(kwargs.get("path"), str):
            data = {"path": kwargs["path"], "bytes": 8, "backup_id": "backup-0001"}
        return FakeResult(
            ok=bool(kwargs.get("ok", True)),
            summary=str(kwargs.get("summary", f"called {tool_name}")),
            error=kwargs.get("error") if isinstance(kwargs.get("error"), str) else None,
            data=data,
        )


class FakeResult:
    def __init__(
        self,
        *,
        ok: bool,
        summary: str,
        error: str | None = None,
        data: dict | None = None,
    ) -> None:
        self.ok = ok
        self.summary = summary
        self.error = error
        self.data = data or {}


def test_tool_gateway_rejects_disallowed_tool(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    with pytest.raises(PermissionError, match="Tool is not allowed"):
        gateway.run_tool_calls(
            [{"tool_name": "write_file", "args": {}}],
            {"task_id": "task-0001", "allowed_tools": []},
            context,
        )


def test_tool_gateway_accepts_expected_diagnostic_failure(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)
    task = {
        "task_id": "task-0001",
        "allowed_tools": ["run_command"],
        "completion_contract": {"allows_expected_failure": True},
    }

    results = gateway.run_tool_calls(
        [{"tool_name": "run_command", "args": {"ok": False, "error": "nonzero_exit"}}],
        task,
        context,
    )

    assert results[0].ok is True
    assert results[0].summary.startswith("Diagnostic failure accepted")


def test_tool_gateway_records_runtime_hooks(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )
    gateway = ToolExecutionGateway(
        FakeRegistry(),
        ToolPermissionPolicy(tmp_path, validator),
        hook_manager=RuntimeHookManager(validator),
    )

    gateway.run_tool_calls(
        [{"tool_name": "read_file", "args": {"path": "README.md"}}],
        {"task_id": "task-0001", "allowed_tools": ["read_file"]},
        context,
    )

    hooks = JsonlStore(validator).read_all(tmp_path / "runtime_hooks.jsonl", "runtime_hook_event")
    assert [hook["hook_name"] for hook in hooks] == ["before_tool_call", "after_tool_call"]
    assert hooks[0]["tool_name"] == "read_file"
    assert hooks[0]["data"] == {"arg_keys": ["path"]}
    assert hooks[1]["data"]["ok"] is True


def test_tool_gateway_records_user_progress_tool_events(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    results = gateway.run_tool_calls(
        [
            {
                "tool_name": "run_command",
                "args": {"command": "pytest -q", "summary": "tests passed"},
            }
        ],
        {"task_id": "task-0001", "allowed_tools": ["run_command"]},
        context,
    )

    events = JsonlStore(context.validator).read_all(
        tmp_path / "user_progress.jsonl",
        "user_progress_event",
    )
    assert [(event["channel"], event["event_type"]) for event in events] == [
        ("execution_chain", "turn_start"),
        ("tool", "tool_call"),
        ("tool", "tool_output"),
        ("execution_chain", "tool_observation"),
        ("execution_chain", "turn_end"),
    ]
    assert events[0]["tool_call_id"] == "toolcall-0001"
    assert events[0]["data"]["turn_event"]["event_type"] == "turn_start"
    assert events[1]["command"] == ["pytest -q"]
    assert events[2]["status"] == "completed"
    assert events[2]["parent_event_id"] == events[1]["event_id"]
    assert events[3]["display_level"] == "main"
    assert events[3]["data"]["observation"]["tool_name"] == "run_command"
    assert events[3]["data"]["observation"]["ok"] is True
    assert events[4]["data"]["turn_event"]["event_type"] == "turn_end"
    assert events[4]["parent_event_id"] == events[0]["event_id"]
    assert getattr(results[0], "harness_observation").model_summary() == (
        "run_command ok: tests passed"
    )


def test_tool_gateway_records_user_progress_file_events(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    gateway.run_tool_calls(
        [{"tool_name": "write_file", "args": {"path": "src/app.py"}}],
        {
            "task_id": "task-0001",
            "allowed_tools": ["write_file"],
            "parallel_safety": "serial",
            "write_scope": ["src/app.py"],
        },
        context,
    )

    events = JsonlStore(context.validator).read_all(
        tmp_path / "user_progress.jsonl",
        "user_progress_event",
    )
    file_events = [event for event in events if event["channel"] == "file"]
    observations = [event for event in events if event["event_type"] == "tool_observation"]
    assert len(file_events) == 1
    assert file_events[0]["event_type"] == "file_created"
    assert file_events[0]["display_level"] == "main"
    assert file_events[0]["file_changes"][0]["path"] == "src/app.py"
    assert observations[0]["data"]["observation"]["artifact_refs"] == ["src/app.py"]
    assert observations[0]["data"]["observation"]["file_changes"][0]["path"] == "src/app.py"


def test_tool_gateway_records_user_progress_errors(tmp_path: Path) -> None:
    gateway, context = _gateway(tmp_path)

    with pytest.raises(RuntimeError, match="Tool failed"):
        gateway.run_tool_calls(
            [{"tool_name": "run_command", "args": {"ok": False, "summary": "boom"}}],
            {"task_id": "task-0001", "allowed_tools": ["run_command"]},
            context,
        )

    events = JsonlStore(context.validator).read_all(
        tmp_path / "user_progress.jsonl",
        "user_progress_event",
    )
    assert events[-3]["channel"] == "tool"
    assert events[-3]["event_type"] == "error"
    assert events[-3]["status"] == "failed"
    assert events[-3]["data"]["error_type"] == "RuntimeError"
    assert events[-2]["channel"] == "execution_chain"
    assert events[-2]["event_type"] == "tool_observation"
    assert events[-2]["data"]["observation"]["ok"] is False
    assert events[-2]["data"]["observation"]["tool_name"] == "run_command"
    assert events[-2]["data"]["observation"]["data"]["error_type"] == "RuntimeError"
    assert events[-1]["status"] == "failed"
    assert events[-1]["event_type"] == "turn_end"
    assert events[-1]["data"]["observation"]["ok"] is False
    assert events[-1]["data"]["error_type"] == "RuntimeError"
    assert load_harness_observations(tmp_path)[-1]["observation"]["ok"] is False


def _gateway(tmp_path: Path) -> tuple[ToolExecutionGateway, RuntimeContext]:
    validator = SchemaValidator(Path.cwd() / "schemas")
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )
    return ToolExecutionGateway(FakeRegistry(), ToolPermissionPolicy(tmp_path, validator)), context
