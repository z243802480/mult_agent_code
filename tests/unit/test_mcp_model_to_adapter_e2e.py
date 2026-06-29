"""Full-chain e2e: a model emits an mcp__ tool_call that flows propose_action -> gateway -> adapter.

The other MCP tests inject the tool_call list by hand at the gateway. This closes the missing
link the audit flagged: a (stub) provider *selects* an mcp__<server>__<tool> native tool call,
CoderAgent.propose_action turns the provider response into an execution action, and the same
action's tool_calls route through the ToolExecutionGateway to McpAdapter — producing a
schema-validated invocation and the loop-feedback observation, exactly like a local tool.
"""
import json
from pathlib import Path
from typing import Any

from asteria_runtime.agents.coder_agent import CoderAgent
from asteria_runtime.core.mcp_adapter import McpAdapter
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


class McpToolCallModel:
    """A tool_use provider that selects mcp__everything__echo as its native tool call."""

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        raw = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "mcp__everything__echo",
                                    "arguments": json.dumps({"message": "hi"}),
                                },
                            }
                        ],
                    }
                }
            ]
        }
        return ChatResponse(
            content="",
            finish_reason="tool_calls",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            model_provider="fake",
            model_name="fake",
            raw_response=raw,
        )


class FakeMcpSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        return {"content": [{"type": "text", "text": "echoed: hi"}]}

    def close(self) -> None:
        pass


def _context(tmp_path: Path) -> RuntimeContext:
    return RuntimeContext(
        root=tmp_path,
        run_id="run-1",
        policy={"permission_mode": "reviewed_auto", "protected_paths": []},
        validator=SchemaValidator(Path("schemas")),
        run_dir_override=tmp_path,
    )


def _task() -> dict[str, Any]:
    return {
        "task_id": "task-1",
        "task_kind": "research",  # research intent permits MCP at the call-boundary gate
        "allowed_tools": [],
        "allowed_mcp": ["everything"],
        "write_scope": [],
        "expected_artifacts": [],
    }


def test_model_emitted_mcp_call_flows_through_loop_to_adapter(tmp_path: Path) -> None:
    # 1) The model selects an mcp__ tool; propose_action turns the response into an action.
    agent = CoderAgent(McpToolCallModel(), SchemaValidator(Path("schemas")))
    surface = {
        "tools": [
            {
                "name": "mcp__everything__echo",
                "task_allowed": True,
                "description": "echo",
                "parameter_contract": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
            }
        ],
        "task_allowed_model_tools": ["mcp__everything__echo"],
    }
    action = agent.propose_action(
        task=_task(),
        goal_spec={"goal_id": "goal-1", "original_goal": "use the echo MCP tool"},
        project_config={"name": "demo"},
        available_tools=[],
        run_id="run-1",
        runtime_context={
            "agent_role_contract": {"worker_transport": "tool_use"},
            "model_tool_surface": surface,
        },
    )
    assert action["tool_calls"][0]["tool_name"] == "mcp__everything__echo"
    assert action["tool_calls"][0]["args"] == {"message": "hi"}

    # 2) The same action's tool_calls route through the gateway to the MCP adapter.
    ctx = _context(tmp_path)
    session = FakeMcpSession()
    gateway = ToolExecutionGateway(
        registry=None,
        permission_policy=None,
        mcp_adapter=McpAdapter({"everything": session}),
    )
    results = gateway.run_tool_calls(action["tool_calls"], _task(), ctx, stop_on_failure=False)

    assert len(results) == 1 and results[0].ok is True
    assert session.calls == [("tools/call", {"name": "echo", "arguments": {"message": "hi"}})]
    observation = getattr(results[0], "harness_observation", None)
    assert observation is not None and observation.tool_name == "mcp__everything__echo"
    # the adapter wrote schema-validated MCP evidence (full chain, not a hand-injected call)
    invocations = JsonlStore(ctx.validator).read_all(
        tmp_path / "mcp_invocations.jsonl", "mcp_invocation"
    )
    assert len(invocations) == 1 and invocations[0]["tool_name"] == "echo"
