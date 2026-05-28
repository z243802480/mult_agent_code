import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.mcp_adapter import (
    McpAdapter,
    mcp_adapter_config_from_policy,
    mcp_invocation_summary,
)
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


class FlakyMcpSession:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary server closed stdout")
        return {"content": [{"type": "text", "text": "ok"}]}

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
    assert session.calls == [("tools/call", {"name": "search", "arguments": {"query": "runtime"}})]
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
    assert invocations[0]["status"] == "timeout"
    assert invocations[0]["error_class"] == "timeout"


def test_mcp_adapter_retries_retryable_session_failures(tmp_path: Path) -> None:
    context = _context(tmp_path)
    session = FlakyMcpSession()
    adapter = McpAdapter({"docs": session}, retry_attempts=1)

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
    assert result.ok is True
    assert session.calls == 2
    assert invocations[0]["retry_attempts"] == 1
    assert invocations[0]["data"]["attempts"] == 2


def test_mcp_adapter_loads_server_config_from_policy(tmp_path: Path) -> None:
    config = mcp_adapter_config_from_policy(
        {
            "mcp": {
                "session_call_timeout_seconds": 12,
                "retry_attempts": 2,
                "servers": [
                    {
                        "name": "docs",
                        "command": ["node", "server.mjs"],
                        "cwd": "tools/mcp",
                        "env": {"MODE": "test"},
                        "framing": "content-length",
                    }
                ],
            }
        },
        root=tmp_path,
    )

    assert config.session_call_timeout_seconds == 12
    assert config.retry_attempts == 2
    assert config.servers[0].name == "docs"
    assert config.servers[0].cwd == (tmp_path / "tools" / "mcp").resolve()
    assert config.servers[0].env == {"MODE": "test"}
    assert config.servers[0].framing == "content-length"


def test_mcp_invocation_summary_groups_statuses(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    (tmp_path / "mcp_invocations.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "mcp_invocation_id": "mcp-0001",
                        "server_name": "docs",
                        "tool_name": "echo",
                        "ok": True,
                        "status": "success",
                        "summary": "ok",
                        "created_at": "2026-05-28T00:00:00+08:00",
                    }
                ),
                json.dumps(
                    {
                        "mcp_invocation_id": "mcp-0002",
                        "server_name": "docs",
                        "tool_name": "search",
                        "ok": False,
                        "status": "timeout",
                        "summary": "timed out",
                        "created_at": "2026-05-28T00:01:00+08:00",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = mcp_invocation_summary(tmp_path, validator)

    assert summary["total"] == 2
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["by_status"] == {"success": 1, "timeout": 1}
    assert "failures by status" in summary["consumer_summary"]
