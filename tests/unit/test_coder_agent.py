import json
from pathlib import Path

from asteria_runtime.agents.coder_agent import CoderAgent
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


class CaptureActionClient:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "rerun tests after observation",
                    "tool_calls": [],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": "python -m pytest",
                                "expected_returncodes": [0],
                            },
                            "reason": "verify repair",
                        }
                    ],
                    "runtime_requests": [],
                    "completion_notes": "tests pass",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            model_provider="fake",
            model_name="fake",
            raw_response={},
        )


def test_coder_agent_prompt_includes_harness_observations() -> None:
    client = CaptureActionClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    agent.propose_action(
        task={
            "task_id": "task-0001",
            "allowed_tools": ["run_command"],
            "write_scope": [],
            "expected_artifacts": [],
        },
        goal_spec={"goal_id": "goal-1", "user_goal": "fix tests"},
        project_config={"name": "demo"},
        available_tools=["run_command"],
        run_id="run-1",
        runtime_context={
            "runtime_profile_id": "runtime-profile-task-0001",
            "model_profile_id": "model-profile-task-0001",
            "agent_role_contract": {
                "role": "CoderAgent",
                "purpose": "coding",
                "deadline_profile": "worker",
                "provider_call_seconds": 90,
                "stream_idle_timeout_seconds": 30,
                "max_model_calls": 1,
            },
            "prompt_envelope": {
                "content_hash": "sha256:prompt",
                "path": ".asteria/runs/run-1/prompt_envelope_execute.json",
                "capability_manifest_hash": "sha256:manifest",
                "section_order": ["project_guidance", "capability_manifest"],
                "sections": [
                    {
                        "name": "project_guidance",
                        "summary": "Follow AGENTS.md project guidance.",
                    }
                ],
                "capability_manifest": {
                    "direct_tools": [{"name": "run_command"}],
                    "verification": [{"name": "run_tests"}],
                },
            },
            "context_package": {
                "context_envelope_path": ".asteria/runs/run-1/context_envelopes/context_envelope_task-0001.json",
                "context_envelope": {
                    "payload_hash": "sha256:context",
                },
            },
            "tool_observations": [
                {
                    "tool_name": "run_command",
                    "ok": False,
                    "summary": "pytest failed",
                    "next_hint": "diagnose_then_repair_replan_ask_or_stop",
                }
            ],
            "harness_observations": [
                {
                    "task_id": "task-0001",
                    "stage": "verification",
                    "summary": "run_command failed: pytest failed",
                    "observation": {
                        "tool_name": "run_command",
                        "ok": False,
                        "summary": "pytest failed",
                    },
                }
            ]
        },
    )

    prompt = client.requests[0].messages[-1].content
    metadata = client.requests[0].metadata
    assert "harness_observations" in prompt
    assert "prompt_envelope" in prompt
    assert "capability_manifest" in prompt
    assert "tool_observations" in prompt
    assert "run_command failed: pytest failed" in prompt
    assert metadata["runtime_profile_id"] == "runtime-profile-task-0001"
    assert metadata["model_profile_id"] == "model-profile-task-0001"
    assert metadata["agent_role_contract"]["role"] == "CoderAgent"
    assert metadata["prompt_envelope_hash"] == "sha256:prompt"
    assert metadata["context_envelope_hash"] == "sha256:context"
    assert metadata["context_envelope_path"].endswith("context_envelope_task-0001.json")


def test_coder_agent_prompt_uses_slim_execution_context_for_fast_path() -> None:
    client = CaptureActionClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))
    runtime_context = {
        "context_package": {
            "read_scope_files": [
                {"path": f"file-{index}.py", "content": "x" * 1500}
                for index in range(7)
            ],
            "context_envelope_path": ".asteria/runs/run-1/context_envelopes/context.json",
            "context_envelope": {"payload": {"large": True}, "payload_hash": "sha256:context"},
        },
        "tool_observations": [{"id": f"obs-{index}"} for index in range(9)],
    }

    agent.propose_action(
        task={
            "task_id": "task-0001",
            "allowed_tools": ["write_file"],
            "write_scope": ["result.json"],
            "read_scope": [],
            "expected_artifacts": ["result.json"],
        },
        goal_spec={
            "goal_id": "goal-1",
            "original_goal": "Create a local file",
            "target_outputs": ["result.json"],
        },
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
        runtime_context=runtime_context,
    )

    payload = json.loads(client.requests[0].messages[-1].content)
    metadata = client.requests[0].metadata
    prompt_context = payload["runtime_context"]
    assert prompt_context["context_policy"]["mode"] == "slim"
    assert prompt_context["context_policy"]["fast_path"]["task_kind"] == "simple_file"
    assert len(prompt_context["tool_observations"]) == 5
    assert len(prompt_context["context_package"]["read_scope_files"]) == 5
    assert prompt_context["context_package"]["context_envelope"]["payload_omitted"] is True
    assert metadata["context_mode"] == "slim"
    assert metadata["fast_path_task_kind"] == "simple_file"
    assert len(runtime_context["tool_observations"]) == 9
