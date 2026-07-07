import json
from pathlib import Path

import pytest

from asteria_runtime.commands.debug_command import DebugCommand
from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from tests.helpers.spine import spine_response

pytestmark = [pytest.mark.workflow, pytest.mark.spine_default]


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        del request
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "create a repairable module",
                    "normalized_goal": "Create a repairable module",
                    "goal_type": "software_tool",
                    "assumptions": [],
                    "constraints": [],
                    "non_goals": [],
                    "expanded_requirements": [],
                    "target_outputs": ["repairable.py"],
                    "definition_of_done": ["VALUE equals 2"],
                    "verification_strategy": ["python command"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class FakeExecutionClient:
    def __init__(self, value: int) -> None:
        self.value = value

    def chat(self, request: ChatRequest) -> ChatResponse:
        return spine_response(
            request,
            narration=f"设置 VALUE 为 {self.value} 并验证。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "repairable.py",
                        "content": f"VALUE = {self.value}\n",
                        "overwrite": True,
                    },
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": 'python -c "from repairable import VALUE; assert VALUE == 2"'
                    },
                },
            ],
            model_name="fake-execute",
        )


def _blocked_run(tmp_path: Path) -> str:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    result = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeExecutionClient(1),
    ).run()
    assert result.blocked == 1
    return plan.run_id


def test_debug_continues_failed_task_through_execute_session_loop(tmp_path: Path) -> None:
    run_id = _blocked_run(tmp_path)

    result = DebugCommand(
        tmp_path,
        run_id=run_id,
        model_client=FakeExecutionClient(2),
    ).run()

    assert result.repaired == 1
    assert result.still_blocked == 0
    assert (tmp_path / "repairable.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    assert not (run_dir / "prompt_envelope_debug.json").exists()
    assert "session_recovery_requested" in (run_dir / "events.jsonl").read_text(
        encoding="utf-8"
    )
    progress = (run_dir / "user_progress.jsonl").read_text(encoding="utf-8")
    assert "session_agent_loop" in progress


def test_debug_only_requeues_selected_failed_task(tmp_path: Path) -> None:
    run_id = _blocked_run(tmp_path)
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    other = dict(task_plan["tasks"][0])
    other["task_id"] = "task-0002"
    other["title"] = "Unrelated ready work"
    other["status"] = "ready"
    task_plan["tasks"].insert(0, other)
    task_plan_path.write_text(json.dumps(task_plan), encoding="utf-8")

    result = DebugCommand(
        tmp_path,
        run_id=run_id,
        task_id="task-0001",
        model_client=FakeExecutionClient(2),
    ).run()

    assert [item.task_id for item in result.repairs] == ["task-0001"]
    updated = json.loads(task_plan_path.read_text(encoding="utf-8"))
    statuses = {item["task_id"]: item["status"] for item in updated["tasks"]}
    assert statuses["task-0001"] == "done"
    assert statuses["task-0002"] == "ready"


def test_debug_requeues_in_progress_failure_notes() -> None:
    command = DebugCommand(Path("."))
    assert command._task_needs_debug_repair(
        {
            "status": "in_progress",
            "notes": "Task completion contract violated: verification did not pass",
        }
    )
    assert not command._task_needs_debug_repair({"status": "in_progress", "notes": ""})
    assert command._task_needs_debug_repair({"status": "blocked", "notes": ""})
