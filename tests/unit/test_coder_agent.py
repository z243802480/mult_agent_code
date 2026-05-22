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
                "prompt_envelope": {
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
    assert "harness_observations" in prompt
    assert "prompt_envelope" in prompt
    assert "capability_manifest" in prompt
    assert "tool_observations" in prompt
    assert "run_command failed: pytest failed" in prompt
