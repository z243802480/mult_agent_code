import json
from pathlib import Path

from asteria_runtime.agents.debug_agent import DebugAgent
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


class WrappedRepairClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        content = json.dumps(
            {
                "repair_action": {
                    "task_id": "task-0001",
                    "summary": "write repaired file",
                    "tool_calls": [
                        {
                            "tool": "write_file",
                            "args": {"path": "out/result.txt", "content": "ok"},
                        }
                    ],
                    "verification": [],
                }
            }
        )
        return ChatResponse(
            content=content,
            finish_reason="stop",
            usage=TokenUsage(10, 10, 20),
            model_provider="fake",
            model_name="fake-debug",
            raw_response={},
        )


def test_debug_agent_accepts_wrapped_repair_action() -> None:
    task = {
        "task_id": "task-0001",
        "title": "Repair result",
        "description": "Create out/result.txt",
        "allowed_tools": ["write_file", "run_command"],
        "expected_artifacts": ["out/result.txt"],
        "acceptance": ["file exists"],
    }

    action = DebugAgent(
        WrappedRepairClient(),
        SchemaValidator(Path.cwd() / "schemas"),
    ).propose_repair(
        task=task,
        goal_spec={"normalized_goal": "Create out/result.txt"},
        failure_evidence={"summary": "missing file"},
        available_tools=["write_file", "run_command"],
        run_id="run-1",
    )

    assert action["task_id"] == "task-0001"
    assert action["tool_calls"][0]["tool_name"] == "write_file"
    assert action["tool_calls"][0]["args"]["path"] == "out/result.txt"
