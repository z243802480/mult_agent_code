import json
from pathlib import Path

from agent_runtime.commands.decide_command import DecideCommand
from agent_runtime.commands.resume_command import ResumeCommand
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


class FakePartialThenPassReviewClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        payload = json.loads(request.messages[-1].content)
        if self.calls == 1:
            overall = {
                "status": "partial",
                "score": 0.72,
                "reason": "Needs a README helper artifact.",
            }
            outcome_eval = {
                "verification_pass_rate": 1.0,
                "run_success": True,
                "follow_up_tasks": [
                    {
                        "title": "Create README helper",
                        "description": "Create README helper artifact",
                        "priority": "medium",
                        "acceptance": ["README helper file exists"],
                    }
                ],
            }
        else:
            overall = {
                "status": "pass",
                "score": 0.9,
                "reason": "Follow-up is complete.",
            }
            outcome_eval = {"verification_pass_rate": 1.0, "run_success": True}
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": payload["run_id"],
                    "goal_eval": {"goal_clarity_score": 0.9, "requirement_coverage": 1.0},
                    "artifact_eval": {"artifacts_present": True, "logs_present": True},
                    "outcome_eval": outcome_eval,
                    "trajectory_eval": {"blocked_task_count": 0, "repair_success_rate": 1.0},
                    "cost_eval": {"status": "within_budget"},
                    "overall": overall,
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(20, 30, 50),
            model_provider="fake",
            model_name="fake-review",
            raw_response={},
        )


class FakeDecisionReviewClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": payload["run_id"],
                    "goal_eval": {"goal_clarity_score": 0.9, "requirement_coverage": 0.8},
                    "artifact_eval": {"artifacts_present": True, "logs_present": True},
                    "outcome_eval": {
                        "verification_pass_rate": 1.0,
                        "run_success": True,
                        "follow_up_tasks": [
                            {
                                "title": "Add web UI",
                                "description": "Add a web UI output medium for the tool.",
                                "category": "output_medium",
                                "impact": {
                                    "scope": "high",
                                    "budget": "medium",
                                    "risk": "medium",
                                    "quality": "high",
                                },
                                "decision_question": (
                                    "Should the first product surface be a web UI?"
                                ),
                            }
                        ],
                    },
                    "trajectory_eval": {"blocked_task_count": 0, "repair_success_rate": 1.0},
                    "cost_eval": {"status": "within_budget"},
                    "overall": {
                        "status": "partial",
                        "score": 0.74,
                        "reason": "Output medium needs user steering.",
                    },
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(20, 30, 50),
            model_provider="fake",
            model_name="fake-review",
            raw_response={},
        )


class FakeResearchClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        source = payload["sources"][0]
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": payload["run_id"],
                    "query": payload["query"],
                    "created_at": "2026-04-28T10:00:00+08:00",
                    "sources": [
                        {
                            "source_id": source["source_id"],
                            "title": source["title"],
                            "source_type": source["source_type"],
                            "reference": source["reference"],
                            "summary": source["summary"],
                        }
                    ],
                    "claims": [
                        {
                            "claim": "A complete module should include a helper artifact.",
                            "source_ids": [source["source_id"]],
                            "confidence": "medium",
                        }
                    ],
                    "expanded_requirements": [
                        {
                            "description": "Include a helper artifact.",
                            "priority": "should",
                            "source_ids": [source["source_id"]],
                        }
                    ],
                    "risks": [],
                    "decision_candidates": [],
                    "summary": "Research suggests adding a helper artifact.",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 10, 20),
            model_provider="fake",
            model_name="fake-research",
            raw_response={},
        )


class FakeSequentialExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        content = request.messages[-1].content
        if "README helper" in content:
            path = "README_HELPER.md"
            body = "helper\n"
            command = (
                "python -c \"from pathlib import Path; "
                "assert Path('README_HELPER.md').exists()\""
            )
        else:
            path = "complete_module.py"
            body = "def answer():\n    return 42\n"
            command = "python -c \"from complete_module import answer; assert answer() == 42\""
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": json.loads(content)["task"]["task_id"],
                    "summary": f"Create {path}.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {"path": path, "content": body, "overwrite": True},
                            "reason": "create artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {"command": command},
                            "reason": "verify artifact",
                        }
                    ],
                    "completion_notes": f"{path} works",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


class FakeDecisionExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        content = request.messages[-1].content
        if "Implement accepted decision" in content:
            path = "WEB_UI.md"
            body = "web ui selected\n"
            command = (
                "python -c \"from pathlib import Path; "
                "assert Path('WEB_UI.md').exists()\""
            )
        else:
            path = "complete_module.py"
            body = "def answer():\n    return 42\n"
            command = "python -c \"from complete_module import answer; assert answer() == 42\""
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": json.loads(content)["task"]["task_id"],
                    "summary": f"Create {path}.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {"path": path, "content": body, "overwrite": True},
                            "reason": "create artifact",
                        }
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {"command": command},
                            "reason": "verify artifact",
                        }
                    ],
                    "completion_notes": f"{path} works",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
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
        enable_research=False,
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
        enable_research=False,
    ).run()

    assert result.status == "completed"
    assert (tmp_path / "complete_module.py").read_text(encoding="utf-8") == (
        "def answer():\n    return 42\n"
    )
    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "debug: completed" in final_report
    assert "Blocked tasks: 0" in final_report


def test_run_command_uses_research_and_executes_review_follow_up(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "complete.md").write_text(
        "A complete module should include a helper artifact.\n",
        encoding="utf-8",
    )
    review_client = FakePartialThenPassReviewClient()

    result = RunCommand(
        tmp_path,
        "create a complete module",
        max_iterations=3,
        plan_model_client=FakePlanClient(),
        research_model_client=FakeResearchClient(),
        execute_model_client=FakeSequentialExecuteClient(),
        review_model_client=review_client,
    ).run()

    assert result.status == "completed"
    assert (tmp_path / "complete_module.py").exists()
    assert (tmp_path / "README_HELPER.md").exists()
    assert review_client.calls == 2
    run_dir = tmp_path / ".agent" / "runs" / result.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert len(task_plan["tasks"]) == 2
    assert all(task["status"] == "done" for task in task_plan["tasks"])
    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "research: completed" in final_report
    assert "follow-up task(s)" in final_report


def test_run_command_pauses_when_review_creates_decision_point(tmp_path: Path) -> None:
    result = RunCommand(
        tmp_path,
        "create a complete module",
        max_iterations=3,
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeDecisionReviewClient(),
        enable_research=False,
    ).run()

    assert result.status == "paused"
    run_dir = tmp_path / ".agent" / "runs" / result.run_id
    decisions = (run_dir / "decisions.jsonl").read_text(encoding="utf-8")
    assert "Should the first product surface be a web UI?" in decisions
    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "decision point(s)" in final_report
    assert "## Pending Decisions" in final_report
    assert "decision-0001" in final_report


def test_resume_command_applies_resolved_decision_and_continues_run(tmp_path: Path) -> None:
    paused = RunCommand(
        tmp_path,
        "create a complete module",
        max_iterations=3,
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeDecisionReviewClient(),
        enable_research=False,
    ).run()
    assert paused.status == "paused"

    DecideCommand(
        tmp_path,
        run_id=paused.run_id,
        decision_id="decision-0001",
        select_option_id="approve",
    ).run()
    resumed = ResumeCommand(
        tmp_path,
        run_id=paused.run_id,
        max_iterations=2,
        execute_model_client=FakeDecisionExecuteClient(),
        review_model_client=FakeReviewClient(),
    ).run()

    assert resumed.status == "completed"
    assert resumed.applied_decisions == 1
    assert resumed.created_tasks == 1
    assert (tmp_path / "WEB_UI.md").exists()
    run_dir = tmp_path / ".agent" / "runs" / paused.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert len(task_plan["tasks"]) == 2
    assert all(task["status"] == "done" for task in task_plan["tasks"])
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "decision_applied" in events
    final_report = resumed.run_result.final_report_path.read_text(encoding="utf-8")
    assert "## Accepted Decisions" in final_report
