import json
from pathlib import Path

from asteria_runtime.agents.coder_agent import CoderAgent
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_profile_builder import RuntimeProfileBuilder
from asteria_runtime.core.worker_transport import (
    execution_action_from_tool_calls,
    extract_tool_calls,
    resolve_worker_transport,
)
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


class ToolUseCaptureClient:
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
                                    "name": "write_file",
                                    "arguments": json.dumps(
                                        {
                                            "path": "index.html",
                                            "content": "<html></html>",
                                            "overwrite": True,
                                        }
                                    ),
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


def test_coder_agent_tool_use_transport_builds_execution_action_from_native_tools() -> None:
    client = ToolUseCaptureClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))
    task = {
        "task_id": "task-web-1",
        "allowed_tools": ["write_file"],
        "write_scope": ["index.html"],
        "expected_artifacts": ["index.html"],
    }

    action = agent.propose_action(
        task=task,
        goal_spec={"goal_id": "goal-web", "original_goal": "Create index.html"},
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-web",
        runtime_context={"agent_role_contract": {"worker_transport": "tool_use"}},
    )

    request = client.requests[0]
    assert request.worker_transport == "tool_use"
    assert request.response_format is None
    assert request.tools
    assert action["tool_calls"][0]["tool_name"] == "write_file"
    assert action["tool_calls"][0]["args"]["path"] == "index.html"
    assert action["agent_loop_decision"]["next_action"]["action"] == "tool"


def test_extract_tool_calls_reads_openai_shape() -> None:
    raw = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "run_command",
                                "arguments": '{"command": "python -m pytest"}',
                            }
                        }
                    ]
                }
            }
        ]
    }
    calls = extract_tool_calls(raw)
    assert calls[0]["tool_name"] == "run_command"
    assert calls[0]["args"]["command"] == "python -m pytest"


def test_tool_use_execution_action_preserves_preflight_and_verification_order() -> None:
    action = execution_action_from_tool_calls(
        task={"task_id": "task-0001"},
        run_id="run-0001",
        sequence=1,
        tool_calls=[
            {
                "tool_name": "run_command",
                "args": {"command": "python -c \"print('approval required')\" && echo ok"},
            },
            {
                "tool_name": "write_file",
                "args": {"path": "complete_module.py", "content": "def answer():\n    return 42\n"},
            },
            {
                "tool_name": "run_command",
                "args": {"command": "python -c \"from complete_module import answer\""},
            },
        ],
    )

    assert [call["tool_name"] for call in action["tool_calls"]] == [
        "run_command",
        "write_file",
    ]
    assert [call["tool_name"] for call in action["verification"]] == ["run_command"]


def test_resolve_worker_transport_prefers_tool_use_for_single_file_fast_path() -> None:
    task = {
        "task_id": "task-0001",
        "task_kind": "diagnostic",
        "title": "Fix parser behavior",
        "description": "Fix parser behavior",
        "write_scope": ["src/parser.py"],
        "expected_artifacts": ["src/parser.py"],
        "expected_changed_files": ["src/parser.py"],
    }

    assert resolve_worker_transport(task=task) == "tool_use"


def test_runtime_profile_builder_projects_tool_use_for_single_file_fast_path(tmp_path: Path) -> None:
    validator = SchemaValidator(Path("schemas"))
    builder = RuntimeProfileBuilder(validator)
    context = RuntimeContext(
        root=tmp_path,
        run_id=None,
        policy={"permissions": {}, "agent_loop": {"worker_transport": "json"}},
        validator=validator,
    )
    task = {
        "task_id": "task-0001",
        "role": "CoderAgent",
        "task_kind": "diagnostic",
        "description": "Fix parser behavior",
        "allowed_tools": ["write_file", "run_command"],
        "expected_artifacts": ["src/parser.py"],
        "expected_changed_files": ["src/parser.py"],
        "write_scope": ["src/parser.py"],
        "read_scope": ["src/parser.py"],
        "parallel_safety": "serial",
    }

    mount = builder.build_and_record(
        context=context,
        task=task,
        worker_id="worker-1",
        runtime_context={},
    )

    assert mount.runtime_context["agent_role_contract"]["worker_transport"] == "tool_use"
