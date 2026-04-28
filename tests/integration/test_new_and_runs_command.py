import json
from pathlib import Path

from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.new_command import NewCommand
from agent_runtime.commands.runs_command import RunsCommand
from agent_runtime.commands.sessions_command import SessionsCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


class GoalEchoPlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        prompt = request.messages[-1].content
        goal = "alpha" if "alpha" in prompt else "beta"
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": f"goal-{goal}",
                    "original_goal": f"create {goal}",
                    "normalized_goal": f"Create {goal}",
                    "goal_type": "software_tool",
                    "assumptions": [],
                    "constraints": [],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": f"Create {goal} artifact",
                            "source": "user",
                            "acceptance": [f"{goal} artifact exists"],
                        }
                    ],
                    "target_outputs": ["file"],
                    "definition_of_done": [f"{goal} artifact exists"],
                    "verification_strategy": ["inspect file"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class CurrentRunExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        content = request.messages[-1].content
        path = "alpha.txt" if "alpha" in content.lower() else "beta.txt"
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": json.loads(content)["task"]["task_id"],
                    "summary": f"Create {path}",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {"path": path, "content": path, "overwrite": True},
                            "reason": "create artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    "python -c \"from pathlib import Path; "
                                    f"assert Path('{path}').exists()\""
                                )
                            },
                            "reason": "verify artifact",
                        }
                    ],
                    "completion_notes": f"{path} exists",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


def test_new_command_creates_isolated_current_session(tmp_path: Path) -> None:
    first = NewCommand(tmp_path, "create alpha", model_client=GoalEchoPlanClient()).run()
    second = NewCommand(tmp_path, "create beta", model_client=GoalEchoPlanClient()).run()

    assert first.run_id != second.run_id
    current = json.loads(
        (tmp_path / ".agent" / "current_session.json").read_text(encoding="utf-8")
    )
    assert current["session_id"] == second.run_id
    sessions = SessionsCommand(tmp_path).run()
    assert sessions.current_session_id == second.run_id
    assert [session["run_id"] for session in sessions.sessions] == [first.run_id, second.run_id]


def test_sessions_command_can_restore_context_for_default_execution(tmp_path: Path) -> None:
    first = NewCommand(tmp_path, "create alpha", model_client=GoalEchoPlanClient()).run()
    second = NewCommand(tmp_path, "create beta", model_client=GoalEchoPlanClient()).run()
    assert second.run_id != first.run_id

    SessionsCommand(tmp_path, session_id=first.run_id, set_current=True).run()
    result = ExecuteCommand(tmp_path, model_client=CurrentRunExecuteClient()).run()

    assert result.run_id == first.run_id
    assert (tmp_path / "alpha.txt").exists()
    assert not (tmp_path / "beta.txt").exists()


def test_runs_command_remains_a_compatibility_alias(tmp_path: Path) -> None:
    session = NewCommand(tmp_path, "create alpha", model_client=GoalEchoPlanClient()).run()

    runs = RunsCommand(tmp_path, run_id=session.run_id).run()

    assert runs.current_run_id == session.run_id
    assert runs.runs[0]["run_id"] == session.run_id
