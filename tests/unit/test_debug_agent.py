import json
from pathlib import Path

from asteria_runtime.agents.debug_agent import DebugAgent
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


class WrappedRepairClient:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
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


class NonJsonRepairClient:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            content="I would replace jsonjson.dump with json.dump.",
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

    client = WrappedRepairClient()
    action = DebugAgent(
        client,
        SchemaValidator(Path.cwd() / "schemas"),
    ).propose_repair(
        task=task,
        goal_spec={"normalized_goal": "Create out/result.txt"},
        failure_evidence={"summary": "missing file"},
        available_tools=["write_file", "run_command"],
        run_id="run-1",
        runtime_context={
            "context_package": {
                "context_envelope_path": ".asteria/runs/run-1/context_envelopes/context_envelope_task-0001.json",
                "context_envelope": {
                    "payload_hash": "sha256:debug-context",
                },
            },
        },
    )

    assert action["task_id"] == "task-0001"
    assert action["tool_calls"][0]["tool_name"] == "write_file"
    assert action["tool_calls"][0]["args"]["path"] == "out/result.txt"
    assert client.requests[0].metadata["context_envelope_hash"] == "sha256:debug-context"
    assert client.requests[0].metadata["context_envelope_path"].endswith(
        "context_envelope_task-0001.json"
    )


def test_debug_agent_uses_deterministic_repair_for_repeated_name_typo() -> None:
    task = {
        "task_id": "task-0001",
        "title": "Repair notes app",
        "description": "Fix notes_app/storage.py",
        "allowed_tools": ["apply_patch", "run_command"],
        "expected_artifacts": ["notes_app/storage.py"],
        "expected_changed_files": ["notes_app/storage.py"],
        "acceptance": ["add command works"],
    }
    failure_evidence = {
        "summary": "verification did not pass",
        "verification_failures": [
            {
                "data": {
                    "requested_command": 'python notes.py add "ship validation"',
                    "expected_returncodes": [0],
                    "stderr": (
                        '  File "C:\\workspace\\notes_app\\storage.py", line 38, in save_notes\n'
                        "    jsonjson.dump(notes, f, indent=2, ensure_ascii=False)\n"
                        "NameError: name 'jsonjson' is not defined\n"
                    ),
                }
            }
        ],
    }

    action = DebugAgent(
        NonJsonRepairClient(),
        SchemaValidator(Path.cwd() / "schemas"),
    ).propose_repair(
        task=task,
        goal_spec={"normalized_goal": "Fix notes app"},
        failure_evidence=failure_evidence,
        available_tools=["apply_patch", "run_command"],
        run_id="run-1",
    )

    assert action["tool_calls"][0]["tool_name"] == "apply_patch"
    patch = action["tool_calls"][0]["args"]["patch"]
    assert "--- a/notes_app/storage.py" in patch
    assert "-    jsonjson.dump(notes, f, indent=2, ensure_ascii=False)" in patch
    assert "+    json.dump(notes, f, indent=2, ensure_ascii=False)" in patch
    assert action["verification"][0]["args"]["command"] == 'python notes.py add "ship validation"'
