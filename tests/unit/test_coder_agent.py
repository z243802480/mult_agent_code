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


class PrematureStopThenToolClient:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            action = {
                "schema_version": "0.1.0",
                "task_id": "task-0001",
                "summary": "stop before doing work",
                "tool_calls": [],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "stop",
                        "reason": "nothing else needed",
                        "target_task_id": "task-0001",
                        "capability_ref": {"type": "runtime", "name": "stop"},
                        "expected_observation": {"summary": "stopped"},
                        "risk": "low",
                        "budget_hint": {},
                        "evidence_refs": [],
                    }
                },
            }
        else:
            action = {
                "schema_version": "0.1.0",
                "task_id": "task-0001",
                "summary": "create expected artifact",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {"path": "result.txt", "content": "done"},
                        "reason": "produce the expected artifact",
                    }
                ],
                "verification": [],
                "runtime_requests": [],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "tool",
                        "reason": "produce the expected artifact",
                        "target_task_id": "task-0001",
                        "capability_ref": {"type": "tool", "name": "write_file"},
                        "expected_observation": {"summary": "result.txt exists"},
                        "risk": "low",
                        "budget_hint": {},
                        "evidence_refs": [],
                    }
                },
            }
        return ChatResponse(
            content=json.dumps(action),
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            model_provider="fake",
            model_name="fake",
            raw_response={},
        )


class ToolUseRetryClient:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ChatResponse(
                content="",
                finish_reason="tool_calls",
                usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
                model_provider="fake",
                model_name="fake",
                raw_response={"choices": [{"message": {"role": "assistant", "content": ""}}]},
            )
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "create expected artifact",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {"path": "result.txt", "content": "done"},
                            "reason": "produce the expected artifact",
                        }
                    ],
                    "verification": [],
                    "runtime_requests": [],
                    "agent_loop_decision": {
                        "next_action": {
                            "action": "tool",
                            "reason": "produce the expected artifact",
                            "target_task_id": "task-0001",
                            "capability_ref": {"type": "tool", "name": "write_file"},
                            "expected_observation": {"summary": "result.txt exists"},
                            "risk": "low",
                            "budget_hint": {},
                            "evidence_refs": [],
                        }
                    },
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            model_provider="fake",
            model_name="fake",
            raw_response={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "write_file",
                                        "arguments": json.dumps(
                                            {"path": "result.txt", "content": "done"}
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
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


def test_coder_agent_tool_use_retry_message_stays_on_native_tool_calls() -> None:
    client = ToolUseRetryClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    agent.propose_action(
        task={
            "task_id": "task-0001",
            "allowed_tools": ["write_file"],
            "write_scope": ["result.txt"],
            "read_scope": [],
            "expected_artifacts": ["result.txt"],
        },
        goal_spec={"goal_id": "goal-1", "original_goal": "Create a local file"},
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
        runtime_context={"agent_role_contract": {"worker_transport": "tool_use"}},
    )

    assert "native tool calls only" in client.requests[1].messages[-1].content
    assert "valid JSON object" not in client.requests[1].messages[-1].content


def test_coder_agent_slim_prompt_omits_unscoped_runtime_bulk() -> None:
    client = CaptureActionClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

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
            "planner_internal_notes": "x" * 10_000,
        },
        project_config={"name": "demo", "internal_catalog": "x" * 10_000},
        available_tools=["write_file"],
        run_id="run-1",
        runtime_context={
            "workspace_files": [{"path": "unrelated.py", "content": "x" * 10_000}],
            "memory": [{"content": "x" * 10_000}],
            "capability_registry": [{"name": "unused", "description": "x" * 10_000}],
            "prompt_envelope": {
                "capability_manifest": {
                    "direct_tools": [{"name": "write_file", "description": "x" * 10_000}],
                    "boundaries": {"internal": "x" * 10_000},
                }
            },
        },
    )

    payload = json.loads(client.requests[0].messages[-1].content)
    prompt_context = payload["runtime_context"]
    assert "workspace_files" not in prompt_context
    assert len(prompt_context["memory"]) == 1
    assert prompt_context["memory"][0]["content_truncated"] is True
    assert "capability_registry" not in prompt_context
    assert payload["goal_spec"] == {
        "goal_id": "goal-1",
        "original_goal": "Create a local file",
        "target_outputs": ["result.json"],
    }
    assert payload["project"] == {"name": "demo"}
    assert prompt_context["prompt_envelope"]["capability_manifest"] == {
        "direct_tools": [{"name": "write_file"}]
    }
    assert len(client.requests[0].messages[-1].content) < 8_000


def test_coder_agent_retries_premature_first_round_stop_for_work_bearing_task() -> None:
    client = PrematureStopThenToolClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    action = agent.propose_action(
        task={
            "task_id": "task-0001",
            "allowed_tools": ["write_file"],
            "write_scope": ["result.txt"],
            "expected_artifacts": ["result.txt"],
        },
        goal_spec={"goal_id": "goal-1", "original_goal": "Create result.txt"},
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
    )

    assert action["agent_loop_decision"]["next_action"]["action"] == "tool"
    assert len(client.requests) == 2
    assert "stop is not grounded" in client.requests[1].messages[-1].content


def test_coder_agent_defaults_to_strong_tier_and_names_target_on_retry() -> None:
    client = PrematureStopThenToolClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    agent.propose_action(
        task={
            "task_id": "task-0001",
            "allowed_tools": ["write_file"],
            "write_scope": ["result.txt"],
            "expected_artifacts": ["result.txt"],
        },
        goal_spec={"goal_id": "goal-1", "original_goal": "Create result.txt"},
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
    )

    # Capable authoring work delegates to the strong tier by default; the
    # corrective retry stays on strong and names the unwritten target file.
    assert client.requests[0].model_tier == "strong"
    assert client.requests[1].model_tier == "strong"
    retry_prompt = client.requests[1].messages[-1].content
    assert "result.txt" in retry_prompt
    assert "Do not stop, ask, or replan" in retry_prompt


def test_coder_agent_honors_explicit_grunt_downgrade_then_escalates_on_retry() -> None:
    client = PrematureStopThenToolClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    agent.propose_action(
        task={
            "task_id": "task-0001",
            "allowed_tools": ["write_file"],
            "write_scope": ["result.txt"],
            "expected_artifacts": ["result.txt"],
            # Planner flags this as basic grunt work -> medium tier.
            "execution_tier": "medium",
        },
        goal_spec={"goal_id": "goal-1", "original_goal": "Create result.txt"},
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
    )

    # Explicit grunt downgrade is honored on the first attempt; a corrective
    # retry still escalates to strong so the task converges.
    assert client.requests[0].model_tier == "medium"
    assert client.requests[1].model_tier == "strong"


# --- transport parity: discovered mcp__/skill__ tools reach the model on the
# tool_use transport and survive slim context, at parity with the json/full path ---


class ToolUseSurfaceClient:
    """Captures the request and returns one native write_file tool call (single round)."""

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
                                            "path": "result.txt",
                                            "content": "done",
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


def _mcp_tool(name: str = "mcp__files__read", *, allowed: bool = True) -> dict:
    return {
        "name": name,
        "kind": "external",
        "permission": "ask" if allowed else "deny",
        "task_allowed": allowed,
        "description": "Read a file via MCP",
        "parameter_contract": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }


def _skill_tool(name: str = "skill__verify", *, allowed: bool = True) -> dict:
    return {
        "name": name,
        "kind": "skill",
        "permission": "ask" if allowed else "deny",
        "task_allowed": allowed,
        "description": "Load the verify skill",
        "parameter_contract": {},
    }


def _surface_with(*tools: dict) -> dict:
    return {
        "schema_version": "0.1.0",
        "adapter": "model_tool_surface",
        "tools": list(tools),
        "task_allowed_model_tools": [
            t["name"] for t in tools if t.get("task_allowed")
        ],
    }


def _slim_task() -> dict:
    return {
        "task_id": "task-0001",
        "allowed_tools": ["write_file"],
        "write_scope": ["result.json"],
        "read_scope": [],
        "expected_artifacts": ["result.json"],
    }


def _slim_goal() -> dict:
    return {
        "goal_id": "goal-1",
        "original_goal": "Create a local file",
        "target_outputs": ["result.json"],
    }


def test_coder_agent_tool_use_exposes_mcp_skill_native_defs() -> None:
    client = ToolUseSurfaceClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    agent.propose_action(
        task={
            "task_id": "task-0001",
            "allowed_tools": ["write_file"],
            "write_scope": ["result.txt"],
            "expected_artifacts": ["result.txt"],
        },
        goal_spec={"goal_id": "goal-1", "original_goal": "Create a local file"},
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
        runtime_context={
            "agent_role_contract": {"worker_transport": "tool_use"},
            "model_tool_surface": _surface_with(_mcp_tool(), _skill_tool()),
        },
    )

    specs = client.requests[0].tools
    by_name = {s["function"]["name"]: s for s in specs}
    assert "write_file" in by_name  # native local tool preserved
    assert "mcp__files__read" in by_name  # MCP tool now a native def under tool_use
    assert "skill__verify" in by_name
    assert by_name["mcp__files__read"]["function"]["parameters"]["required"] == ["path"]
    assert by_name["skill__verify"]["function"]["parameters"] == {
        "type": "object",
        "properties": {},
    }


def test_coder_agent_tool_use_no_mcp_skill_is_noop() -> None:
    client = ToolUseSurfaceClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    agent.propose_action(
        task={
            "task_id": "task-0001",
            "allowed_tools": ["write_file"],
            "write_scope": ["result.txt"],
            "expected_artifacts": ["result.txt"],
        },
        goal_spec={"goal_id": "goal-1", "original_goal": "Create a local file"},
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
        runtime_context={"agent_role_contract": {"worker_transport": "tool_use"}},
    )

    names = [s["function"]["name"] for s in client.requests[0].tools]
    assert names == ["write_file"]  # byte-for-byte the prior native-only behavior


def test_coder_agent_slim_json_keeps_mcp_skill_surface() -> None:
    client = CaptureActionClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    agent.propose_action(
        task=_slim_task(),
        goal_spec=_slim_goal(),
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
        runtime_context={
            "model_tool_surface": _surface_with(
                _mcp_tool(),
                {"name": "write_file", "kind": "internal", "task_allowed": True},
            ),
        },
    )

    payload = json.loads(client.requests[0].messages[-1].content)
    assert payload["runtime_context"]["context_policy"]["mode"] == "slim"
    surface = payload["model_tool_surface"]
    names = {t["name"] for t in surface["tools"]}
    assert "mcp__files__read" in names  # external tool survives slim
    assert "write_file" not in names  # local registry tool dropped (slim token win)


def test_coder_agent_slim_json_blank_when_no_mcp_skill() -> None:
    client = CaptureActionClient()
    agent = CoderAgent(client, SchemaValidator(Path("schemas")))

    agent.propose_action(
        task=_slim_task(),
        goal_spec=_slim_goal(),
        project_config={"name": "demo"},
        available_tools=["write_file"],
        run_id="run-1",
        runtime_context={
            "model_tool_surface": _surface_with(
                {"name": "write_file", "kind": "internal", "task_allowed": True},
            ),
        },
    )

    payload = json.loads(client.requests[0].messages[-1].content)
    assert payload["runtime_context"]["context_policy"]["mode"] == "slim"
    assert payload["model_tool_surface"] == {}  # parity with prior slim behavior
