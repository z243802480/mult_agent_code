import json

import pytest
from pathlib import Path

from asteria_runtime.commands.chat_command import ChatCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.sessions_command import SessionsCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.models.base import ChatRequest, ChatResponse

from tests.integration.test_plan_command import FakePlanClient
from tests.integration.test_user_command_smoke import FakeChatClient

pytestmark = pytest.mark.workflow


def _write_completed_memory(root: Path, *, run_id: str, goal: str) -> None:
    ActiveGoalMemory(root).write_from_run(
        goal_spec={
            "goal_id": "goal-0001",
            "original_goal": goal,
            "normalized_goal": goal,
        },
        task_plan={
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Initial scaffold",
                    "status": "done",
                    "summary": "Scaffold completed.",
                }
            ]
        },
        run_status={"run_id": run_id, "current_phase": "DONE", "status": "completed"},
        review_status="pass",
        completion="implemented_needs_review",
        updated_by="run",
        update_reason="first_goal_completed",
    )


def test_same_workspace_second_plan_updates_current_session(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    first = PlanCommand(tmp_path, "第一个目标：本地 CLI 工具", model_client=FakePlanClient()).run()
    second = PlanCommand(tmp_path, "续作：补充测试与文档", model_client=FakePlanClient()).run()

    sessions = SessionsCommand(tmp_path, limit=10).run()
    assert sessions.current_session_id == second.run_id
    assert len(sessions.sessions) >= 2
    assert {item["run_id"] for item in sessions.sessions[:2]} >= {first.run_id, second.run_id}

    status = StatusCommand(tmp_path).run().to_dict()
    assert status["current_session_id"] == second.run_id
    assert status["runtime_progress"]["plan"]["transcript_kind"] == "plan"


def test_active_goal_memory_path_available_after_plan(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    PlanCommand(tmp_path, "做一个密码测试工具", model_client=FakePlanClient()).run()

    memory = ActiveGoalMemory(tmp_path)
    assert memory.path.parent.exists()
    status = StatusCommand(tmp_path).run().to_dict()
    assert status["current_session_id"]
    assert status["runtime_progress"]["plan"] is not None


def test_second_goal_sees_prior_active_goal_memory_in_status(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    first_goal = "第一个目标：本地 CLI 工具"
    continuation_goal = "续作：补充测试与文档"
    first = PlanCommand(tmp_path, first_goal, model_client=FakePlanClient()).run()
    _write_completed_memory(tmp_path, run_id=first.run_id, goal=first_goal)

    second = PlanCommand(tmp_path, continuation_goal, model_client=FakePlanClient()).run()

    status = StatusCommand(tmp_path).run().to_dict()
    assert status["current_session_id"] == second.run_id
    assert status["active_goal_memory_path"]
    assert first_goal in status["active_goal_memory"]
    structured = ActiveGoalMemory(tmp_path).read_structured()
    assert structured["source_run_id"] == first.run_id
    assert structured["current_goal"] == first_goal


def test_chat_continuation_question_mounts_active_goal_memory(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    first_goal = "第一个目标：本地 CLI 工具"
    first = PlanCommand(tmp_path, first_goal, model_client=FakePlanClient()).run()
    _write_completed_memory(tmp_path, run_id=first.run_id, goal=first_goal)

    class ContinuationChatClient(FakeChatClient):
        def __init__(self) -> None:
            self.context: dict | None = None

        def chat(self, request: ChatRequest) -> ChatResponse:
            payload = json.loads(request.messages[-1].content)
            self.context = payload["context_envelope"]["payload"]
            return super().chat(request)

    client = ContinuationChatClient()
    chat = ChatCommand(
        tmp_path,
        "继续上次未完成的任务，先总结当前状态，再推进下一步。",
        model_client=client,
    ).run()

    assert chat.answer.strip()
    assert client.context is not None
    assert client.context["active_goal_memory"]
    assert first_goal in client.context["active_goal_memory"]
    assert client.context["context_policy"]["active_goal_memory_included"] is True
