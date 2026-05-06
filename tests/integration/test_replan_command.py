import json
from pathlib import Path

from agent_runtime.commands.execute_command import ExecuteCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.replan_command import ReplanCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "create a repairable module",
                    "normalized_goal": "Create a repairable module",
                    "goal_type": "software_tool",
                    "assumptions": ["local python module"],
                    "constraints": ["no network"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Create a module exposing answer()",
                            "source": "inferred",
                            "acceptance": ["answer() returns 42"],
                        }
                    ],
                    "target_outputs": ["python_module"],
                    "definition_of_done": ["answer() returns 42"],
                    "verification_strategy": ["python command"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class FakeBrokenExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task_id = json.loads(request.messages[-1].content)["task"]["task_id"]
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "summary": "Create module with wrong value.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "complete_module.py",
                                "content": "def answer():\n    return 41\n",
                                "overwrite": True,
                            },
                            "reason": "create broken artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    "python -c "
                                    '"from complete_module import answer; assert answer() == 42"'
                                )
                            },
                            "reason": "verify behavior",
                        }
                    ],
                    "completion_notes": "intentionally broken",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


def test_replan_command_creates_repair_task_from_task_failure_evidence(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()

    result = ReplanCommand(tmp_path, run_id=plan.run_id).run()

    assert result.created_tasks == 1
    assert result.created_decisions == 0
    assert result.superseded_tasks == ["task-0001"]
    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert [task["status"] for task in task_plan["tasks"]] == ["discarded", "ready"]
    repair_task = task_plan["tasks"][1]
    assert repair_task["task_id"] == "task-0002"
    assert repair_task["replan"]["source_evidence_id"] == "task-failure-0001"
    assert "verification did not pass" in repair_task["description"]
    backlog = json.loads(
        (tmp_path / ".agent" / "tasks" / "backlog.json").read_text(encoding="utf-8")
    )
    assert backlog["tasks"][1]["task_id"] == "task-0002"


def test_replan_command_creates_decision_after_replan_limit(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a repairable module", model_client=FakePlanClient()).run()
    ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeBrokenExecuteClient()).run()

    result = ReplanCommand(
        tmp_path,
        run_id=plan.run_id,
        max_replans_per_task=0,
    ).run()

    assert result.created_tasks == 0
    assert result.created_decisions == 1
    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[0]["metadata"]["kind"] == "replan_decision"
    assert decisions[0]["metadata"]["source_evidence_id"] == "task-failure-0001"
