"""M2: MCP tool discovery (tools/list) and the model-facing surface filter."""
from typing import Any

from asteria_runtime.core.agent_tool_surface import mcp_model_tools
from asteria_runtime.core.mcp_adapter import McpAdapter


class ListToolsSession:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "tools/list":
            return {"tools": self._tools}
        return {"content": [{"type": "text", "text": "ok"}]}

    def close(self) -> None:
        pass


class DeadSession:
    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("MCP server closed stdout")

    def close(self) -> None:
        pass


def test_discover_tools_lists_servers_as_mcp_names() -> None:
    adapter = McpAdapter(
        {
            "everything": ListToolsSession(
                [
                    {
                        "name": "echo",
                        "description": "Echo back",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"message": {"type": "string"}},
                        },
                    },
                    {"name": "add", "description": "Add numbers"},
                ]
            )
        }
    )
    discovered = adapter.discover_tools()
    assert {d["model_name"] for d in discovered} == {
        "mcp__everything__echo",
        "mcp__everything__add",
    }
    echo = next(d for d in discovered if d["tool"] == "echo")
    assert echo["input_schema"]["properties"]["message"]["type"] == "string"


def test_discover_tools_degrades_on_dead_server() -> None:
    adapter = McpAdapter({"dead": DeadSession()})
    assert adapter.discover_tools() == []


def test_mcp_model_tools_filters_by_allowed_mcp() -> None:
    discovered = [
        {"server": "everything", "tool": "echo", "model_name": "mcp__everything__echo", "input_schema": {}},
        {"server": "other", "tool": "run", "model_name": "mcp__other__run", "input_schema": {}},
    ]
    by_name = {t["name"]: t for t in mcp_model_tools(discovered, {"allowed_mcp": ["everything"]})}
    assert by_name["mcp__everything__echo"]["task_allowed"] is True
    assert by_name["mcp__other__run"]["task_allowed"] is False
    assert by_name["mcp__other__run"]["permission"] == "deny"

    # empty allowed_mcp => every configured tool is allowed (matches capability-decision contract)
    assert all(t["task_allowed"] for t in mcp_model_tools(discovered, {}))

    # server/tool granularity
    fine = {t["name"]: t for t in mcp_model_tools(discovered, {"allowed_mcp": ["other/run"]})}
    assert fine["mcp__other__run"]["task_allowed"] is True
    assert fine["mcp__everything__echo"]["task_allowed"] is False
