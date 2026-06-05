import pytest
from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.sessions_command import SessionsCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.core.active_goal_memory import ActiveGoalMemory

from tests.integration.test_plan_command import FakePlanClient

pytestmark = pytest.mark.workflow


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
