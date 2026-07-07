"""Full-chain e2e: a model emits an mcp__ tool_call that flows model→extract→gateway→adapter.

The other MCP tests inject the tool_call list by hand at the gateway. This closes the missing
link the audit flagged: a (stub) provider *selects* an mcp__<server>__<tool> native tool call,
the model-driven spine's tool_use transport (``extract_tool_calls`` — exactly what
``run_model_driven_turn`` uses) turns the provider response into runtime tool_calls, and those
route through the ToolExecutionGateway to McpAdapter — producing a schema-validated invocation
and the loop-feedback observation, exactly like a local tool. (RA7b: the FSM ``propose_action``
was deleted with the round loop; the spine extracts native tool calls directly.)
"""
import json
from pathlib import Path
from typing import Any

from asteria_runtime.core.mcp_adapter import McpAdapter
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.tool_execution_gateway import ToolExecutionGateway
from asteria_runtime.core.worker_transport import extract_tool_calls
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
    # 1) The model selects an mcp__ tool; the spine's tool_use transport extracts the native tool
    #    call (extract_tool_calls is exactly what run_model_driven_turn._read_turn uses).
    model = McpToolCallModel()
    response = model.chat(
        ChatRequest(purpose="task_execution", model_tier="strong", messages=[])
    )
    tool_calls = extract_tool_calls(response.raw_response)
    assert tool_calls[0]["tool_name"] == "mcp__everything__echo"
    assert tool_calls[0]["args"] == {"message": "hi"}

    # 2) The same tool_calls route through the gateway to the MCP adapter.
    ctx = _context(tmp_path)
    session = FakeMcpSession()
    gateway = ToolExecutionGateway(
        registry=None,
        permission_policy=None,
        mcp_adapter=McpAdapter({"everything": session}),
    )
    results = gateway.run_tool_calls(tool_calls, _task(), ctx, stop_on_failure=False)

    assert len(results) == 1 and results[0].ok is True
    assert session.calls == [("tools/call", {"name": "echo", "arguments": {"message": "hi"}})]
    observation = getattr(results[0], "harness_observation", None)
    assert observation is not None and observation.tool_name == "mcp__everything__echo"
    # the adapter wrote schema-validated MCP evidence (full chain, not a hand-injected call)
    invocations = JsonlStore(ctx.validator).read_all(
        tmp_path / "mcp_invocations.jsonl", "mcp_invocation"
    )
    assert len(invocations) == 1 and invocations[0]["tool_name"] == "echo"
