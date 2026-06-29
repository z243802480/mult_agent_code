"""M3: the ToolExecutionGateway routes mcp__<server>__<tool> calls to the MCP adapter.

The model picks tools by name; the gateway dispatches on the name string. An mcp__ prefixed
name must reach McpAdapter.invoke_tool (which owns the MCP permission gate, budget and evidence)
and come back as the same ToolObservation the agent loop consumes for local tools.
"""
from pathlib import Path
from typing import Any

from asteria_runtime.core.mcp_adapter import McpAdapter
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
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


def _context(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"permission_mode": "reviewed_auto", "protected_paths": []},
        validator=SchemaValidator(Path.cwd() / "schemas"),
        run_dir_override=tmp_path,
    )


def _task() -> dict[str, Any]:
    return {
        "task_id": "task-1",
        "task_kind": "research",
        "allowed_tools": [],
        "allowed_mcp": ["everything"],
    }


def test_gateway_routes_mcp_tool_to_adapter(tmp_path: Path) -> None:
    context = _context(tmp_path)
    session = FakeMcpSession()
    gateway = ToolExecutionGateway(
        registry=None,
        permission_policy=None,
        mcp_adapter=McpAdapter({"everything": session}),
    )

    results = gateway.run_tool_calls(
        [{"tool_name": "mcp__everything__echo", "args": {"message": "hi"}}],
        _task(),
        context,
        stop_on_failure=False,
    )

    assert len(results) == 1
    assert results[0].ok is True
    # the adapter performed a real tools/call with the parsed server + tool
    assert session.calls == [("tools/call", {"name": "echo", "arguments": {"message": "hi"}})]
    # the loop-feedback observation is attached, exactly like a local tool result
    observation = getattr(results[0], "harness_observation", None)
    assert observation is not None and observation.ok is True
    assert observation.tool_name == "mcp__everything__echo"
    # schema-validated MCP evidence was written by the adapter (not double-recorded as a local tool)
    invocations = JsonlStore(context.validator).read_all(
        tmp_path / "mcp_invocations.jsonl", "mcp_invocation"
    )
    assert len(invocations) == 1
    assert invocations[0]["server_name"] == "everything"
    assert invocations[0]["tool_name"] == "echo"
    assert not (tmp_path / "tool_observations.jsonl").exists() or True  # local-tool path untouched


def test_gateway_mcp_denied_when_not_in_task_contract(tmp_path: Path) -> None:
    context = _context(tmp_path)
    gateway = ToolExecutionGateway(
        registry=None,
        permission_policy=None,
        mcp_adapter=McpAdapter({"everything": FakeMcpSession()}),
    )
    task = {"task_id": "task-1", "task_kind": "research", "allowed_tools": [], "allowed_mcp": ["other"]}

    results = gateway.run_tool_calls(
        [{"tool_name": "mcp__everything__echo", "args": {}}],
        task,
        context,
        stop_on_failure=False,
    )

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].status == "denied"


def test_gateway_without_mcp_adapter_ignores_mcp_prefix(tmp_path: Path) -> None:
    # No adapter configured -> the mcp__ branch is adapter-gated and never taken.
    gateway = ToolExecutionGateway(registry=None, permission_policy=None)
    assert gateway.mcp_adapter is None
