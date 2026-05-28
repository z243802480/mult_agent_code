from pathlib import Path
from typing import Any

from asteria_runtime.core.mcp_adapter import McpAdapter
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


class FakeMcpSession:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.response = response or {"content": [{"type": "text", "text": "ok"}]}
        self.closed = False

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        return self.response

    def close(self) -> None:
        self.closed = True


class HangingMcpSession:
    def __init__(self) -> None:
        self.closed = False

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        import time

        time.sleep(5)
        return {}

    def close(self) -> None:
        self.closed = True


def _context(tmp_path: Path) -> RuntimeContext:
    validator = SchemaValidator(Path.cwd() / "schemas")
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"permission_mode": "reviewed_auto", "protected_paths": []},
        validator=validator,
        run_dir_override=tmp_path,
    )


def test_mcp_adapter_invokes_session_and_records_decision_and_progress(tmp_path: Path) -> None:
    context = _context(tmp_path)
    session = FakeMcpSession()
    adapter = McpAdapter({"docs": session})
    task = {
        "task_id": "task-1",
        "task_kind": "research",
        "allowed_mcp": ["docs"],
    }

    result = adapter.invoke_tool(
        context=context,
        task=task,
        server_name="docs",
        tool_name="search",
        arguments={"query": "runtime"},
    )

    assert result.ok is True
    assert session.calls == [
        ("tools/call", {"name": "search", "arguments": {"query": "runtime"}})
    ]
    decisions = JsonlStore(context.validator).read_all(
        tmp_path / "capability_decisions.jsonl",
        schema_name=None,
    )
    invocations = JsonlStore(context.validator).read_all(
        tmp_path / "mcp_invocations.jsonl",
        schema_name=None,
    )
    progress = JsonlStore(context.validator).read_all(
        tmp_path / "user_progress.jsonl",
        "user_progress_event",
    )

    assert decisions[0]["capability_type"] == "mcp"
    assert decisions[0]["mcp_invocation_id"] == "mcp-0001"
    assert decisions[0]["decision"]["decision"] == "ask"
    assert invocations[0]["server_name"] == "docs"
    assert invocations[0]["tool_name"] == "search"
    assert invocations[0]["status"] == "success"
    assert [(event["channel"], event["event_type"]) for event in progress] == [
        ("permission", "permission_decision"),
        ("tool", "tool_output"),
    ]
    assert progress[1]["data"]["capability_type"] == "mcp"


def test_mcp_adapter_denies_unlisted_server_before_session_call(tmp_path: Path) -> None:
    context = _context(tmp_path)
    session = FakeMcpSession()
    adapter = McpAdapter({"docs": session})

    result = adapter.invoke_tool(
        context=context,
        task={
            "task_id": "task-1",
            "task_kind": "research",
            "allowed_mcp": ["approved"],
        },
        server_name="docs",
        tool_name="search",
        arguments={"api_token": "secret"},
    )

    invocations = JsonlStore(context.validator).read_all(
        tmp_path / "mcp_invocations.jsonl",
        schema_name=None,
    )

    assert result.ok is False
    assert result.status == "denied"
    assert session.calls == []
    assert invocations[0]["arguments"] == {"api_token": "<redacted>"}
    assert invocations[0]["capability_decision"]["decision"] == "deny"


def test_mcp_adapter_times_out_hung_session_and_records_failure(tmp_path: Path) -> None:
    context = _context(tmp_path)
    session = HangingMcpSession()
    adapter = McpAdapter({"docs": session}, session_call_timeout_seconds=1)

    result = adapter.invoke_tool(
        context=context,
        task={
            "task_id": "task-1",
            "task_kind": "research",
            "allowed_mcp": ["docs"],
        },
        server_name="docs",
        tool_name="search",
        arguments={},
    )

    invocations = JsonlStore(context.validator).read_all(
        tmp_path / "mcp_invocations.jsonl",
        schema_name=None,
    )
    assert result.ok is False
    assert "timed out" in str(result.error)
    assert session.closed is True
    assert invocations[0]["status"] == "failure"
