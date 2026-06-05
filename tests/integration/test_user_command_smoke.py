import pytest
from pathlib import Path

from asteria_runtime.commands.chat_command import ChatCommand
from asteria_runtime.commands.compact_command import CompactCommand
from asteria_runtime.commands.handoff_command import HandoffCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.sessions_command import SessionsCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage

from tests.integration.test_plan_command import FakePlanClient

pytestmark = pytest.mark.workflow


class FakeChatClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="当前 workspace 已初始化，可用 goal、plan、status 推进任务。",
            finish_reason="stop",
            usage=TokenUsage(1, 2, 3),
            model_provider="fake",
            model_name="fake-chat",
            raw_response={},
        )


def test_chat_command_returns_structured_result_in_initialized_workspace(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = ChatCommand(
        tmp_path,
        "解释一下当前 workspace 能做什么",
        model_client=FakeChatClient(),
    ).run()

    assert result.answer.strip()
    assert result.session_context is not None


def test_handoff_command_writes_package_after_plan(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "做一个密码测试工具", model_client=FakePlanClient()).run()

    handoff = HandoffCommand(tmp_path, run_id=plan.run_id).run()

    assert handoff.handoff_path.exists()
    assert handoff.run_id == plan.run_id


def test_resume_command_uses_current_session_after_plan(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "做一个密码测试工具", model_client=FakePlanClient()).run()

    sessions = SessionsCommand(tmp_path, session_id=plan.run_id, include_context=True).run()
    assert sessions.current_session_id == plan.run_id
    assert sessions.context[plan.run_id]["runtime_progress"]["plan"] is not None
    assert sessions.context[plan.run_id]["recommended_next_command"]


def test_compact_command_creates_snapshot_artifact(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    PlanCommand(tmp_path, "做一个密码测试工具", model_client=FakePlanClient()).run()

    compact = CompactCommand(tmp_path, focus="phase3 smoke").run()

    assert compact.snapshot_path.exists()
