from pathlib import Path
import json

import pytest

from asteria_runtime.agents.goal_spec_agent import GoalSpecAgent
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.schema_validator import SchemaValidator


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[ChatRequest] = []

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            content=self.content,
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-model",
            raw_response={},
        )


def valid_goal_spec_json() -> str:
    return """{
      "schema_version": "0.1.0",
      "goal_id": "goal-0001",
      "original_goal": "做一个密码测试工具",
      "normalized_goal": "构建本地优先密码测试工具",
      "goal_type": "software_tool",
      "assumptions": ["本地运行"],
      "constraints": ["privacy_safe"],
      "non_goals": ["不证明绝对安全"],
      "expanded_requirements": [
        {
          "id": "req-0001",
          "priority": "must",
          "description": "提供密码强度评分",
          "source": "inferred",
          "acceptance": ["输入密码后显示评分"]
        }
      ],
      "target_outputs": ["local_cli"],
      "definition_of_done": ["可以运行"],
      "verification_strategy": ["unit_tests"],
      "budget": {"max_iterations": 8, "max_model_calls": 60}
    }"""


def test_goal_spec_agent_generates_valid_goal_spec(monkeypatch) -> None:
    monkeypatch.setattr("asteria_runtime.core.execution_environment.platform.system", lambda: "Windows")
    client = FakeClient(valid_goal_spec_json())
    agent = GoalSpecAgent(client, SchemaValidator(Path("schemas")))

    result = agent.generate("做一个密码测试工具", {"project": {}}, "run-1")

    assert result["goal_id"] == "goal-0001"
    assert result["expanded_requirements"][0]["priority"] == "must"
    assert client.requests[0].metadata["agent_role_contract"]["role"] == "GoalSpecAgent"
    assert '"host_os": "Windows"' in client.requests[0].messages[1].content
    assert '"run_command_shell": "cmd.exe"' in client.requests[0].messages[1].content
    assert "Do not invent a shell command" in client.requests[0].messages[0].content


def test_goal_spec_agent_metadata_uses_provider_route_deadline() -> None:
    client = FakeClient(valid_goal_spec_json())
    agent = GoalSpecAgent(client, SchemaValidator(Path("schemas")))

    agent.generate(
        "goal",
        {
            "project": {},
            "runtime_context": {
                "goal_spec_route_plan": {
                    "selected_model_tier": "strong",
                    "provider": "glm",
                }
            },
            "policy": {
                "provider_route_strategy": {
                    "strong_goal_spec": {
                        "provider_deadline_seconds": 42,
                        "stream_idle_timeout_seconds": 7,
                    }
                }
            },
        },
        "run-1",
    )

    metadata = client.requests[0].metadata
    assert metadata["agent_role_contract"]["provider_call_seconds"] == 42
    assert metadata["agent_role_contract"]["stream_idle_timeout_seconds"] == 7
    assert metadata["model_route"]["provider"] == "glm"


def test_goal_spec_agent_prompt_uses_role_scoped_context() -> None:
    client = FakeClient(valid_goal_spec_json())
    agent = GoalSpecAgent(client, SchemaValidator(Path("schemas")))

    agent.generate(
        "create greet.py",
        {
            "project": {
                "name": "demo",
                "language": "python",
                "internal_catalog": "x" * 20_000,
            },
            "runtime_context": {
                "workspace_files": [{"path": "unrelated.py", "content": "x" * 20_000}],
                "capability_manifest": {"direct_tools": [{"description": "x" * 20_000}]},
                "prompt_envelope": {"sections": ["x" * 20_000]},
                "goal_spec_route_plan": {"selected_model_tier": "medium"},
            },
            "policy": {
                "decision_granularity": "balanced",
                "budgets": {"max_model_calls_per_goal": 200},
                "permissions": {"shell": "review"},
                "provider_route_strategy": {"internal": "x" * 20_000},
            },
            "capability_manifest": {"direct_tools": [{"description": "x" * 20_000}]},
        },
        "run-1",
    )

    prompt = client.requests[0].messages[-1].content
    context_text = prompt.split("Project context:\n", 1)[1].split(
        "\n\nReturn this exact JSON shape:", 1
    )[0]
    context = json.loads(context_text)
    assert context == {
        "project": {"name": "demo", "language": "python"},
        "runtime_context": {"goal_spec_route_plan": {"selected_model_tier": "medium"}},
        "policy": {
            "decision_granularity": "balanced",
            "budgets": {"max_model_calls_per_goal": 200},
            "permissions": {"shell": "review"},
        },
    }
    assert len(prompt) < 5_000


def test_goal_spec_agent_falls_back_for_invalid_json() -> None:
    agent = GoalSpecAgent(FakeClient("not json"), SchemaValidator(Path("schemas")))

    result = agent.generate("goal", {}, "run-1")

    assert result["original_goal"] == "goal"
    assert result["expanded_requirements"][0]["description"] == "goal"
    assert any("deterministic goal specification fallback" in item for item in result["assumptions"])


def test_goal_spec_agent_normalizes_common_model_shape_drift() -> None:
    content = """{
      "goal_id": "goal-0001",
      "original_goal": "create a file",
      "normalized_goal": "Create a simple local file",
      "goal_type": "tool",
      "assumptions": [{"description": "local only"}],
      "constraints": [],
      "non_goals": null,
      "expanded_requirements": [
        {
          "description": "Create hello_runtime.txt",
          "acceptance": [{"description": "file exists"}]
        }
      ],
      "target_outputs": [{"path": "hello_runtime.txt"}],
      "definition_of_done": [{"description": "file exists"}],
      "verification_strategy": "filesystem check",
      "budget": {"max_iterations": 1}
    }"""
    agent = GoalSpecAgent(FakeClient(content), SchemaValidator(Path("schemas")))

    result = agent.generate("create a file", {}, "run-1")

    assert result["schema_version"] == "0.1.0"
    assert result["goal_type"] == "unknown"
    assert result["assumptions"] == ["local only"]
    assert result["non_goals"] == []
    assert result["target_outputs"] == ["hello_runtime.txt"]
    assert result["expanded_requirements"][0]["priority"] == "must"
    assert result["expanded_requirements"][0]["source"] == "inferred"
    assert result["expanded_requirements"][0]["acceptance"] == ["file exists"]


def test_goal_spec_agent_preserves_exact_user_goal_over_model_rewrite() -> None:
    content = """{
      "goal_id": "goal-0001",
      "original_goal": "Create notes stored in notes.",
      "normalized_goal": "Create notes stored in a JSON file",
      "goal_type": "software_tool",
      "assumptions": [],
      "constraints": [],
      "non_goals": [],
      "expanded_requirements": [
        {"description": "Create notes CLI", "acceptance": ["CLI works"]}
      ],
      "target_outputs": ["notes.py"],
      "definition_of_done": ["notes.json is used"],
      "verification_strategy": ["python notes.py list"],
      "budget": {}
    }"""
    agent = GoalSpecAgent(FakeClient(content), SchemaValidator(Path("schemas")))

    result = agent.generate("Create notes stored in notes.json.", {}, "run-1")

    assert result["original_goal"] == "Create notes stored in notes.json."


def test_goal_spec_agent_preserves_explicit_execution_controls() -> None:
    agent = GoalSpecAgent(FakeClient(valid_goal_spec_json()), SchemaValidator(Path("schemas")))

    result = agent.generate(
        "Delegate the review to a subagent. Inspect all Markdown files under input/.",
        {},
        "run-1",
    )

    assert result["execution_preferences"] == {
        "delegation": "required",
        "requested_capability": "subagent",
        "requested_read_scope": ["input/"],
    }


def test_goal_spec_agent_does_not_allow_model_to_expand_user_execution_controls() -> None:
    content = valid_goal_spec_json().replace(
        '"budget": {"max_iterations": 8, "max_model_calls": 60}',
        (
            '"execution_preferences": {"delegation": "required", '
            '"requested_capability": "subagent", "requested_read_scope": ["reports/"]}, '
            '"budget": {"max_iterations": 8, "max_model_calls": 60}'
        ),
    )
    agent = GoalSpecAgent(FakeClient(content), SchemaValidator(Path("schemas")))

    result = agent.generate("Create a local review report.", {}, "run-1")

    assert result["execution_preferences"] == {
        "delegation": "auto",
        "requested_capability": None,
        "requested_read_scope": [],
    }


def test_output_intents_project_only_required_values_and_preserve_conditions(tmp_path) -> None:
    from asteria_runtime.agents.planner import RequirementPlanner
    from asteria_runtime.storage.json_store import JsonStore

    payload = json.loads(valid_goal_spec_json())
    required = "资料/结果（草案）.md"
    optional = "lib/helper.py"
    allowed = "lib/existing.py"
    payload["target_outputs"] = [required, "docs/result.md", optional, allowed]
    payload["constraints"] = [f"May edit {allowed}; optionally create {optional} if needed."]
    payload["output_intents"] = [
        {"value": required, "obligation": "required"},
        {"value": "docs/result.md", "obligation": "required"},
        {"value": optional, "obligation": "optional", "condition": "仅在实现确有需要时"},
        {"value": allowed, "obligation": "allowed"},
    ]
    validator = SchemaValidator(Path("schemas"))
    agent = GoalSpecAgent(FakeClient(json.dumps(payload)), validator)
    result = agent.generate("Produce the required report within the permitted scope.", {}, "run-1")

    assert result["target_outputs"] == [required, "docs/result.md"]
    assert result["output_intents"] == payload["output_intents"]
    store = JsonStore(validator)
    path = tmp_path / "goal_spec.json"
    store.write(path, result, "goal_spec")
    persisted = store.read(path, "goal_spec")
    assert persisted == result
    plan = RequirementPlanner().build_task_plan(persisted, execution_profile="session_agent")
    artifacts = [p for task in plan["tasks"] for p in task["expected_artifacts"]]
    assert required in artifacts
    assert optional not in artifacts and allowed not in artifacts


@pytest.mark.parametrize("intents", [
    [{"value": "helper.py", "obligation": "maybe"}],
    [{"value": "helper.py", "obligation": None}],
    [{"value": 42, "obligation": "required"}],
    [{"value": "helper.py", "obligation": "optional", "condition": ["if needed"]}],
    [{"value": "helper.py", "obligation": "required", "condition": "if needed"}],
    [{"value": "", "obligation": "required"}],
    "helper.py",
])
def test_invalid_output_intents_fall_back_without_promoting_unknown_obligations(intents) -> None:
    payload = json.loads(valid_goal_spec_json())
    payload["target_outputs"] = ["helper.py"]
    payload["output_intents"] = intents
    agent = GoalSpecAgent(FakeClient(json.dumps(payload)), SchemaValidator(Path("schemas")))
    result = agent.generate("Keep the complete original user request.", {}, "run-1")

    assert result["original_goal"] == "Keep the complete original user request."
    assert result["target_outputs"] == []
    assert result["expanded_requirements"][0]["description"] == result["original_goal"]
    assert any("fallback" in s.lower() for s in result["assumptions"])
