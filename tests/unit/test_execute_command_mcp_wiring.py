"""M1: ExecuteCommand wires the MCP adapter from policy into the gateway + model surface.

These exercise the additive integration points without a real MCP subprocess: a fake adapter
is substituted for McpAdapter.from_adapter_config so the policy->adapter->gateway->surface path
and the lifecycle (build / discover / inject / close) are verified deterministically.
"""
from pathlib import Path
from typing import Any

from asteria_runtime.commands import execute_command as ec
from asteria_runtime.core.agent_tool_surface import mcp_model_tools
from asteria_runtime.core.mcp_adapter import McpAdapter


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "tools/list":
            return {"tools": [{"name": "echo", "description": "e", "inputSchema": {"type": "object"}}]}
        return {"content": [{"type": "text", "text": "ok"}]}

    def close(self) -> None:
        self.closed = True


def test_wire_mcp_adapter_injects_discovers_and_closes(tmp_path: Path, monkeypatch) -> None:
    session = _FakeSession()
    fake_adapter = McpAdapter({"everything": session})
    monkeypatch.setattr(
        ec.McpAdapter, "from_adapter_config", classmethod(lambda cls, config: fake_adapter)
    )

    cmd = ec.ExecuteCommand(root=tmp_path)
    assert cmd.tool_gateway.mcp_adapter is None  # default run has no MCP

    cmd._wire_mcp_adapter({"mcp": {"servers": [{"name": "everything", "command": ["noop"]}]}})

    assert cmd.tool_gateway.mcp_adapter is fake_adapter
    assert any(t["model_name"] == "mcp__everything__echo" for t in cmd.mcp_discovered_tools)

    # the per-task surface merge would expose the discovered tool to the model
    surface = mcp_model_tools(cmd.mcp_discovered_tools, {"allowed_mcp": ["everything"]})
    assert any(t["name"] == "mcp__everything__echo" and t["task_allowed"] for t in surface)

    cmd._close_mcp_adapter()
    assert cmd.tool_gateway.mcp_adapter is None
    assert session.closed is True


def test_wire_mcp_adapter_is_noop_without_servers(tmp_path: Path) -> None:
    cmd = ec.ExecuteCommand(root=tmp_path)
    cmd._wire_mcp_adapter({"mcp": {"servers": []}})
    assert cmd.tool_gateway.mcp_adapter is None
    assert cmd.mcp_discovered_tools == []
    cmd._wire_mcp_adapter({})  # no mcp key at all
    assert cmd.tool_gateway.mcp_adapter is None
    assert cmd.mcp_discovered_tools == []
