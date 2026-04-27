import json
from pathlib import Path

from agent_runtime.commands.run_command import RunCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "create a complete module",
                    "normalized_goal": "Create a complete module",
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
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class FakeExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Create module and verify it.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "complete_module.py",
                                "content": "def answer():\n    return 42\n",
                                "overwrite": True,
                            },
                            "reason": "create artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    "python -c "
                                    "\"from complete_module import answer; assert answer() == 42\""
                                )
                            },
                            "reason": "verify behavior",
                        }
                    ],
                    "completion_notes": "complete_module.py works",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


class FakeReviewClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": payload["run_id"],
                    "goal_eval": {"goal_clarity_score": 0.9, "requirement_coverage": 1.0},
                    "artifact_eval": {"artifacts_present": True, "logs_present": True},
                    "outcome_eval": {"verification_pass_rate": 1.0, "run_success": True},
                    "trajectory_eval": {"blocked_task_count": 0, "repair_success_rate": 1.0},
                    "cost_eval": {"status": "within_budget", "model_calls": 2, "tool_calls": 2},
                    "overall": {
                        "status": "pass",
                        "score": 0.92,
                        "reason": "Run is complete and verified.",
                    },
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(20, 30, 50),
            model_provider="fake",
            model_name="fake-review",
            raw_response={},
        )


class FakeBrokenExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Create module with wrong value.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "complete_module.py",
                                "content": "def answer():\n    return 41\n",
                                "overwrite": True,
                            },
                            "reason": "create initial artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    "python -c "
                                    "\"from complete_module import answer; assert answer() == 42\""
                                )
                            },
                            "reason": "verify behavior",
                        }
                    ],
                    "completion_notes": "intentionally broken",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


class FakeDebugClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Fix answer() to return 42.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "complete_module.py",
                                "content": "def answer():\n    return 42\n",
                                "overwrite": True,
                            },
                            "reason": "repair artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    "python -c "
                                    "\"from complete_module import answer; assert answer() == 42\""
                                )
                            },
                            "reason": "verify repair",
                        }
                    ],
                    "completion_notes": "complete_module.py is repaired",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(12, 18, 30),
            model_provider="fake",
            model_name="fake-debug",
            raw_response={},
        )


def test_run_command_executes_minimal_closed_loop(tmp_path: Path) -> None:
    result = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
    ).run()

    assert result.status == "completed"
    assert result.final_report_path.exists()
    assert (tmp_path / "complete_module.py").exists()
    run_dir = tmp_path / ".agent" / "runs" / result.run_id
    assert (run_dir / "review_report.md").exists()
    assert (run_dir / "final_report.md").exists()
    assert "Review status: pass" in (run_dir / "final_report.md").read_text(encoding="utf-8")


def test_run_command_repairs_blocked_task_before_review(tmp_path: Path) -> None:
    result = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeBrokenExecuteClient(),
        debug_model_client=FakeDebugClient(),
        review_model_client=FakeReviewClient(),
    ).run()

    assert result.status == "completed"
    assert (tmp_path / "complete_module.py").read_text(encoding="utf-8") == (
        "def answer():\n    return 42\n"
    )
    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "debug: completed" in final_report
    assert "Blocked tasks: 0" in final_report
