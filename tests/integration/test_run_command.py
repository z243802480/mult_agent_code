import json
from pathlib import Path

import pytest

from asteria_runtime.commands.decide_command import DecideCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.new_command import NewCommand
from asteria_runtime.commands.resume_command import ResumeCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.evaluation.task_plan_evaluator import TaskPlanEvaluator
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage

pytestmark = pytest.mark.workflow


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
                                    '"from complete_module import answer; assert answer() == 42"'
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


class CombinedFastPathClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        if request.purpose == "goal_spec":
            return FakePlanClient().chat(request)
        if request.purpose == "task_execution":
            return FakeExecuteClient().chat(request)
        raise AssertionError(f"Unexpected model call purpose: {request.purpose}")


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
                "python -c \"from pathlib import Path; assert Path('README_HELPER.md').exists()\""
            )
        else:
            path = "complete_module.py"
            body = "def answer():\n    return 42\n"
            command = 'python -c "from complete_module import answer; assert answer() == 42"'
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
            command = "python -c \"from pathlib import Path; assert Path('WEB_UI.md').exists()\""
        else:
            path = "complete_module.py"
            body = "def answer():\n    return 42\n"
            command = 'python -c "from complete_module import answer; assert answer() == 42"'
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


class FakeApprovalExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": json.loads(request.messages[-1].content)["task"]["task_id"],
                    "summary": "Create artifact and verify with a shell operator.",
                    "tool_calls": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    "python -c \"print('approval required')\" "
                                    "&& python -c \"print('approved')\""
                                )
                            },
                            "reason": "exercise execution policy approval before changing files",
                        },
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "complete_module.py",
                                "content": "def answer():\n    return 42\n",
                                "overwrite": True,
                            },
                            "reason": "create artifact",
                        },
                    ],
                    "verification": [
                        {
                            "tool_name": "run_command",
                            "args": {
                                "command": (
                                    'python -c "from complete_module import answer; '
                                    'assert answer() == 42"'
                                )
                            },
                            "reason": "verify behavior after approval",
                        }
                    ],
                    "completion_notes": "complete_module.py exists",
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
                                    '"from complete_module import answer; assert answer() == 42"'
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


class FakeProviderNetworkFailureClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        raise RuntimeError(
            "<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred>"
        )


class DebugMustNotRunClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        raise AssertionError("provider transient blockers must not enter DebugAgent")


def set_budget_policy(
    root: Path,
    *,
    max_model_calls: int,
    compaction_threshold: float,
    hard_stop_threshold: float,
) -> None:
    path = root / ".asteria" / "policies.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    policy["active_budget_profile"] = ""
    policy["budgets"]["max_model_calls_per_goal"] = max_model_calls
    policy["context"]["compaction_threshold"] = compaction_threshold
    policy["context"]["hard_stop_threshold"] = hard_stop_threshold
    path.write_text(json.dumps(policy), encoding="utf-8")


def set_task_plan_quality_gate_blocks(root: Path, value: bool) -> None:
    path = root / ".asteria" / "policies.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    policy.setdefault("agent_loop", {})["task_plan_quality_gate_blocks"] = value
    path.write_text(json.dumps(policy), encoding="utf-8")


class FakeFailingDebugClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Attempt a repair that still fails.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "complete_module.py",
                                "content": "def answer():\n    return 40\n",
                                "overwrite": True,
                            },
                            "reason": "incorrect repair",
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
                            "reason": "verify repair",
                        }
                    ],
                    "completion_notes": "still broken",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(12, 18, 30),
            model_provider="fake",
            model_name="fake-debug",
            raw_response={},
        )


class FakeReplanExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        task = json.loads(request.messages[-1].content)["task"]
        if task["task_id"] == "task-0001":
            value = 41
            summary = "Create module with wrong value."
        else:
            value = 42
            summary = "Repair replanned module."
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task["task_id"],
                    "summary": summary,
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": "complete_module.py",
                                "content": f"def answer():\n    return {value}\n",
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
                                    '"from complete_module import answer; assert answer() == 42"'
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


class FakeQualityRevisionExecuteClient:
    def __init__(self, root: Path) -> None:
        self.root = root

    def chat(self, request: ChatRequest) -> ChatResponse:
        task = json.loads(request.messages[-1].content)["task"]
        if task["role"] != "PlannerAgent":
            return FakeExecuteClient().chat(request)
        task_plan_path, task_plan_eval_path = task["expected_artifacts"]
        task_plan_content = (self.root / task_plan_path).read_text(encoding="utf-8")
        task_plan_eval_content = (self.root / task_plan_eval_path).read_text(encoding="utf-8")
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": task["task_id"],
                    "summary": "Refresh task plan and task plan eval artifacts.",
                    "tool_calls": [
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": task_plan_path,
                                "content": task_plan_content,
                                "overwrite": True,
                            },
                            "reason": "touch task plan artifact for revision",
                        },
                        {
                            "tool_name": "write_file",
                            "args": {
                                "path": task_plan_eval_path,
                                "content": task_plan_eval_content,
                                "overwrite": True,
                            },
                            "reason": "touch quality eval artifact for revision",
                        },
                    ],
                    "verification": [],
                    "completion_notes": "Task plan revision artifacts were refreshed.",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-quality-revision",
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
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    assert (run_dir / "review_report.md").exists()
    assert (run_dir / "final_report.md").exists()
    final_report = (run_dir / "final_report.md").read_text(encoding="utf-8")
    assert "## Current State" in final_report
    assert "Completion: complete" in final_report
    assert "Release gate signal: not_run" in final_report
    assert "Review status: pass" in final_report
    assert "## Execution Evidence" in final_report
    assert "strategy=" in final_report
    assert "promoted=complete_module.py" in final_report
    assert "## Promotion Queue" in final_report
    assert "promoted=1" in final_report
    assert "task_execution_evidence.jsonl" in final_report
    assert "Run `asteria /acceptance --suite core` before release." in final_report


def test_final_report_includes_provider_matrix_guidance(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _write_single_file_bugfix_matrix(tmp_path)

    result = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "## Provider Matrix Guidance" in final_report
    assert "Latest real-provider matrix: 1/1 passed" in final_report
    assert "single_file_bugfix: task_execution avg=2.0" in final_report
    assert "class=extra_execution_without_repair" in final_report
    summary = result.final_report_summary
    guidance = summary["provider_matrix_guidance"]
    assert guidance["status"] == "recorded"
    assert guidance["summary_path"] == (
        ".asteria/verification/real_provider_matrix/matrix-1/matrix_summary.json"
    )
    assert guidance["latest_case"] == "single_file_bugfix"
    assert guidance["task_execution_model_calls"] == 2
    bugfix_trend = guidance["trend"]["cases"]["single_file_bugfix"]
    assert bugfix_trend["task_execution_model_calls_avg"] == 2.0
    assert bugfix_trend["latest_retry_classification"] == "extra_execution_without_repair"


def _write_single_file_bugfix_matrix(root: Path) -> None:
    matrix_dir = root / ".asteria" / "verification" / "real_provider_matrix" / "matrix-1"
    matrix_dir.mkdir(parents=True)
    (matrix_dir / "matrix_summary.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "matrix": "p0",
                "provider_mode": "real",
                "created_at": "2026-06-04T10:00:00Z",
                "ok": True,
                "case_count": 1,
                "passed": 1,
                "failed": 0,
                "duration_seconds": 41.0,
                "output_dir": str(matrix_dir),
                "cases": [
                    {
                        "name": "single_file_bugfix",
                        "task_kind": "bug_fix",
                        "route": "repair",
                        "reason": "Focused bugfix probe.",
                        "ok": True,
                        "workspace": "matrix-output/single_file_bugfix",
                        "summary_json": "matrix-output/single_file_bugfix_summary.json",
                        "expected_file": "calc.py",
                        "expected_text": "return a + b",
                        "run_id": "run-bugfix",
                        "final_report": "matrix-output/final_report.md",
                        "diagnostics": {},
                        "agent_loop": {
                            "status": "recorded",
                            "recovery_required": False,
                            "recovery_satisfied": True,
                            "budget_repair_attempts": 0,
                        },
                        "context_strategy": {
                            "status": "recorded",
                            "model_call_count": 3,
                            "context_modes": {"slim": 2, "unknown": 1},
                            "fast_path_task_kinds": {"single_file_bugfix": 2},
                            "model_tiers": {"medium": 3},
                            "purposes": {"goal_spec": 1, "task_execution": 2},
                            "purpose_context_modes": {
                                "goal_spec": {"unknown": 1},
                                "task_execution": {"slim": 2},
                            },
                            "context_mode_recorded": 2,
                            "slim_model_calls": 2,
                            "strong_model_calls": 0,
                            "failed_model_calls": 0,
                            "task_execution_model_calls": 2,
                            "task_repair_model_calls": 0,
                            "run_review_model_calls": 0,
                        },
                        "failure_type": None,
                        "failure_summary": None,
                        "evidence_refs": ["matrix-output/final_report.md"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_run_command_keeps_default_review_deterministic_when_model_client_is_shared(
    tmp_path: Path,
) -> None:
    result = RunCommand(
        tmp_path,
        "create a complete module",
        model_client=CombinedFastPathClient(),
        enable_research=False,
    ).run()

    assert result.status == "completed"
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    review_tier = eval_report["trajectory_eval"]["review_tier"]
    assert review_tier["mode"] == "deterministic_first"
    assert review_tier["accepted_without_model"] is True
    model_calls = [
        json.loads(line)
        for line in (run_dir / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [call["purpose"] for call in model_calls] == ["goal_spec", "task_execution"]


def test_run_command_pauses_before_execute_when_task_plan_quality_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_task_plan_quality(self, task_plan, goal_spec, run_id=None):
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "created_at": "2026-05-06T12:00:00+08:00",
            "status": "fail",
            "overall_score": 0.55,
            "scores": {
                "granularity_score": 0.5,
                "dependency_score": 1.0,
                "acceptance_score": 0.5,
                "artifact_score": 0.5,
                "tooling_score": 0.25,
            },
            "summary": "Task plan quality fail with score 0.55; 2 error(s), 0 warning(s).",
            "issues": [
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_artifact",
                    "message": "Deliverable task has no expected artifact.",
                    "recommendation": "Add expected_artifacts before execution.",
                },
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_write_tool",
                    "message": "Implementation task cannot write changes.",
                    "recommendation": "Allow apply_patch or write_file.",
                },
            ],
            "recommendations": [
                "Add expected_artifacts before execution.",
                "Allow apply_patch or write_file.",
            ],
            "task_count": 1,
        }

    monkeypatch.setattr(TaskPlanEvaluator, "evaluate", fail_task_plan_quality)
    InitCommand(tmp_path).run()
    set_task_plan_quality_gate_blocks(tmp_path, True)

    result = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    assert result.status == "paused"
    assert not (tmp_path / "complete_module.py").exists()
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[0]["metadata"]["kind"] == "task_plan_quality_gate"
    assert decisions[0]["recommended_option_id"] == "revise_plan"
    assert decisions[0]["options"][0]["action"] == "require_replan"
    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "Task plan quality: fail (0.55; 2 issue(s))" in final_report
    assert "Task plan quality failed" in final_report


def test_run_command_treats_task_plan_quality_failure_as_repairable_warning_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_task_plan_quality(self, task_plan, goal_spec, run_id=None):
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "created_at": "2026-05-06T12:00:00+08:00",
            "status": "fail",
            "overall_score": 0.55,
            "scores": {
                "granularity_score": 0.5,
                "dependency_score": 1.0,
                "acceptance_score": 0.5,
                "artifact_score": 0.5,
                "tooling_score": 0.25,
            },
            "summary": "Task plan quality fail with score 0.55; 1 error(s), 0 warning(s).",
            "issues": [
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_artifact",
                    "message": "Deliverable task has no expected artifact.",
                    "recommendation": "Add expected_artifacts before execution.",
                }
            ],
            "recommendations": ["Add expected_artifacts before execution."],
            "task_count": 1,
        }

    monkeypatch.setattr(TaskPlanEvaluator, "evaluate", fail_task_plan_quality)

    result = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    assert result.status == "completed"
    assert (tmp_path / "complete_module.py").exists()
    assert any(step.name == "plan-quality" and step.status == "warning" for step in result.steps)
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    assert not (run_dir / "decisions.jsonl").exists()


def test_resume_prioritizes_task_plan_revision_after_quality_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_task_plan_quality(self, task_plan, goal_spec, run_id=None):
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "created_at": "2026-05-06T12:00:00+08:00",
            "status": "fail",
            "overall_score": 0.55,
            "scores": {
                "granularity_score": 0.5,
                "dependency_score": 1.0,
                "acceptance_score": 0.5,
                "artifact_score": 0.5,
                "tooling_score": 0.25,
            },
            "summary": "Task plan quality fail with score 0.55; 2 error(s), 0 warning(s).",
            "issues": [
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_artifact",
                    "message": "Deliverable task has no expected artifact.",
                    "recommendation": "Add expected_artifacts before execution.",
                },
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_write_tool",
                    "message": "Implementation task cannot write changes.",
                    "recommendation": "Allow apply_patch or write_file.",
                },
            ],
            "recommendations": [
                "Add expected_artifacts before execution.",
                "Allow apply_patch or write_file.",
            ],
            "task_count": 1,
        }

    monkeypatch.setattr(TaskPlanEvaluator, "evaluate", fail_task_plan_quality)
    InitCommand(tmp_path).run()
    set_task_plan_quality_gate_blocks(tmp_path, True)
    paused = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    DecideCommand(
        tmp_path,
        run_id=paused.run_id,
        decision_id="decision-0001",
        select_option_id="revise_plan",
    ).run()
    resumed = ResumeCommand(
        tmp_path,
        run_id=paused.run_id,
        max_iterations=0,
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / paused.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    original_task = task_plan["tasks"][0]
    revision_task = task_plan["tasks"][1]

    assert resumed.applied_decisions == 1
    assert resumed.created_tasks == 1
    assert original_task["status"] == "backlog"
    assert original_task["depends_on"] == [revision_task["task_id"]]
    assert revision_task["status"] == "ready"
    assert revision_task["role"] == "PlannerAgent"
    assert revision_task["expected_artifacts"] == [
        f".asteria/runs/{paused.run_id}/task_plan.json",
        f".asteria/runs/{paused.run_id}/task_plan_eval.json",
    ]
    assert revision_task["completion_contract"]["requires_changed_artifact"] is True
    assert "missing_artifact" in revision_task["description"]


def test_resume_rechecks_quality_after_plan_revision_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_task_plan_quality(self, task_plan, goal_spec, run_id=None):
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "created_at": "2026-05-06T12:00:00+08:00",
            "status": "fail",
            "overall_score": 0.55,
            "scores": {
                "granularity_score": 0.5,
                "dependency_score": 1.0,
                "acceptance_score": 0.5,
                "artifact_score": 0.5,
                "tooling_score": 0.25,
            },
            "summary": "Task plan quality fail with score 0.55; 2 error(s), 0 warning(s).",
            "issues": [
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_artifact",
                    "message": "Deliverable task has no expected artifact.",
                    "recommendation": "Add expected_artifacts before execution.",
                },
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_write_tool",
                    "message": "Implementation task cannot write changes.",
                    "recommendation": "Allow apply_patch or write_file.",
                },
            ],
            "recommendations": [
                "Add expected_artifacts before execution.",
                "Allow apply_patch or write_file.",
            ],
            "task_count": 1,
        }

    monkeypatch.setattr(TaskPlanEvaluator, "evaluate", fail_task_plan_quality)
    InitCommand(tmp_path).run()
    set_task_plan_quality_gate_blocks(tmp_path, True)
    paused = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()
    DecideCommand(
        tmp_path,
        run_id=paused.run_id,
        decision_id="decision-0001",
        select_option_id="revise_plan",
    ).run()

    resumed = ResumeCommand(
        tmp_path,
        run_id=paused.run_id,
        max_iterations=1,
        execute_model_client=FakeQualityRevisionExecuteClient(tmp_path),
        review_model_client=FakeReviewClient(),
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / paused.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert resumed.status == "paused"
    assert task_plan["tasks"][1]["status"] == "done"
    assert task_plan["tasks"][0]["status"] == "ready"
    assert not (tmp_path / "complete_module.py").exists()
    assert [decision["decision_id"] for decision in decisions] == [
        "decision-0001",
        "decision-0002",
    ]
    assert decisions[1]["metadata"]["kind"] == "task_plan_quality_gate"
    assert decisions[1]["status"] == "pending"


def test_resume_proceed_once_bypasses_current_task_plan_quality_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_task_plan_quality(self, task_plan, goal_spec, run_id=None):
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "created_at": "2026-05-06T12:00:00+08:00",
            "status": "fail",
            "overall_score": 0.55,
            "scores": {
                "granularity_score": 0.5,
                "dependency_score": 1.0,
                "acceptance_score": 0.5,
                "artifact_score": 0.5,
                "tooling_score": 0.25,
            },
            "summary": "Task plan quality fail with score 0.55; 1 error(s), 0 warning(s).",
            "issues": [
                {
                    "task_id": "task-0001",
                    "severity": "error",
                    "code": "missing_artifact",
                    "message": "Deliverable task has no expected artifact.",
                    "recommendation": "Add expected_artifacts before execution.",
                }
            ],
            "recommendations": ["Add expected_artifacts before execution."],
            "task_count": 1,
        }

    monkeypatch.setattr(TaskPlanEvaluator, "evaluate", fail_task_plan_quality)
    InitCommand(tmp_path).run()
    set_task_plan_quality_gate_blocks(tmp_path, True)
    paused = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()
    DecideCommand(
        tmp_path,
        run_id=paused.run_id,
        decision_id="decision-0001",
        select_option_id="proceed_once",
    ).run()

    resumed = ResumeCommand(
        tmp_path,
        run_id=paused.run_id,
        max_iterations=1,
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / paused.run_id
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert resumed.status == "completed"
    assert (tmp_path / "complete_module.py").exists()
    assert any(
        event.get("data", {}).get("effect") == "task_plan_quality_bypass_recorded"
        for event in events
    )


def test_run_command_without_goal_continues_current_session(tmp_path: Path) -> None:
    planned = NewCommand(
        tmp_path,
        "create a complete module",
        model_client=FakePlanClient(),
    ).run()

    result = RunCommand(
        tmp_path,
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    assert result.run_id == planned.run_id
    assert result.status == "completed"
    assert (tmp_path / "complete_module.py").exists()


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


def test_run_command_does_not_debug_provider_transient_blocker(tmp_path: Path) -> None:
    result = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeProviderNetworkFailureClient(),
        debug_model_client=DebugMustNotRunClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    assert result.status == "blocked"
    assert any(step.name == "provider" for step in result.steps)
    assert not any(step.name == "debug" for step in result.steps)
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    failures = [
        json.loads(line)
        for line in (run_dir / "task_failures.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert failures[-1]["failure_type"] == "provider_network"
    progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(event["title"] == "Provider route blocked" for event in progress)
    model_calls = [
        json.loads(line)
        for line in (run_dir / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert not any(call.get("purpose") == "task_repair" for call in model_calls)


def test_run_command_replans_when_debug_cannot_repair(tmp_path: Path) -> None:
    result = RunCommand(
        tmp_path,
        "create a complete module",
        max_iterations=3,
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeReplanExecuteClient(),
        debug_model_client=FakeFailingDebugClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    assert result.status == "completed"
    assert (tmp_path / "complete_module.py").read_text(encoding="utf-8") == (
        "def answer():\n    return 42\n"
    )
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert [task["status"] for task in task_plan["tasks"]] == ["discarded", "done"]
    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "replan: completed - 1 task(s), 0 decision(s)." in final_report


def test_run_command_compacts_once_when_near_budget(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    set_budget_policy(
        tmp_path,
        max_model_calls=4,
        compaction_threshold=0.25,
        hard_stop_threshold=0.95,
    )

    result = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    assert result.status == "completed"
    assert any(step.name == "compact" and step.status == "budget_guard" for step in result.steps)
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    cost = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost["context_compactions"] >= 1


def test_run_command_pauses_at_budget_hard_stop(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    set_budget_policy(
        tmp_path,
        max_model_calls=1,
        compaction_threshold=0.75,
        hard_stop_threshold=0.9,
    )

    result = RunCommand(
        tmp_path,
        "create a complete module",
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    assert result.status == "paused"
    assert not (tmp_path / "complete_module.py").exists()
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[0]["metadata"]["kind"] == "budget_guard"
    assert decisions[0]["recommended_option_id"] == "stop_and_review"
    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "Budget guard created" in final_report


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
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
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
    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
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
    run_dir = tmp_path / ".asteria" / "runs" / paused.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert len(task_plan["tasks"]) == 2
    assert all(task["status"] == "done" for task in task_plan["tasks"])
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "decision_applied" in events
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    decision_events = [event for event in user_progress if event["event_type"] == "decision"]
    assert any(event["title"] == "已应用恢复决策" for event in decision_events)
    assert any(
        event["data"]["decision"].get("effect") == "task_created" for event in decision_events
    )
    final_report = resumed.run_result.final_report_path.read_text(encoding="utf-8")
    assert "## Accepted Decisions" in final_report
    active_goal = json.loads(
        (tmp_path / ".asteria" / "memory" / "active_goal.json").read_text(encoding="utf-8")
    )
    assert active_goal["updated_by"] == "resume"
    assert active_goal["update_reason"] == "resume_applied_decisions"


def test_resume_command_records_constraint_action_without_creating_task(tmp_path: Path) -> None:
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
        select_option_id="defer",
    ).run()
    resumed = ResumeCommand(
        tmp_path,
        run_id=paused.run_id,
        max_iterations=1,
        execute_model_client=FakeDecisionExecuteClient(),
        review_model_client=FakeReviewClient(),
    ).run()

    assert resumed.applied_decisions == 1
    assert resumed.created_tasks == 0
    run_dir = tmp_path / ".asteria" / "runs" / paused.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert len(task_plan["tasks"]) == 1
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    applied = [event for event in events if event["type"] == "decision_applied"]
    assert applied[0]["data"]["action"] == "record_constraint"
    assert applied[0]["data"]["effect"] == "constraint_recorded"
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    decision_events = [event for event in user_progress if event["event_type"] == "decision"]
    assert any(
        event["data"]["decision"].get("effect") == "constraint_recorded"
        for event in decision_events
    )
    memory = [
        json.loads(line)
        for line in (tmp_path / ".asteria" / "memory" / "decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert memory[0]["source"]["effect"] == "constraint_recorded"


def test_resume_command_applies_cancel_and_replan_decision_effects(tmp_path: Path) -> None:
    planned = NewCommand(
        tmp_path,
        "create a complete module",
        model_client=FakePlanClient(),
    ).run()
    options = [
        {
            "option_id": "cancel",
            "label": "Cancel extra UI",
            "tradeoff": "Keep the current scope small.",
            "action": "cancel_scope",
        },
        {
            "option_id": "replan",
            "label": "Replan task board",
            "tradeoff": "Spend planning effort to update the task board.",
            "action": "require_replan",
        },
    ]
    DecideCommand(
        tmp_path,
        run_id=planned.run_id,
        question="Should we cancel the extra UI scope?",
        options_json=json.dumps(options),
        default_option_id="cancel",
    ).run()
    DecideCommand(
        tmp_path,
        run_id=planned.run_id,
        question="Should we refresh the task board?",
        options_json=json.dumps(options),
        default_option_id="replan",
    ).run()
    DecideCommand(
        tmp_path,
        run_id=planned.run_id,
        decision_id="decision-0001",
        select_option_id="cancel",
    ).run()
    DecideCommand(
        tmp_path,
        run_id=planned.run_id,
        decision_id="decision-0002",
        select_option_id="replan",
    ).run()

    resumed = ResumeCommand(
        tmp_path,
        run_id=planned.run_id,
        max_iterations=0,
        execute_model_client=FakeDecisionExecuteClient(),
        review_model_client=FakeReviewClient(),
    ).run()

    assert resumed.applied_decisions == 2
    assert resumed.created_tasks == 1
    run_dir = tmp_path / ".asteria" / "runs" / planned.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    replan_task = task_plan["tasks"][-1]
    assert replan_task["role"] == "PlannerAgent"
    assert replan_task["expected_artifacts"] == [f".asteria/runs/{planned.run_id}/task_plan.json"]
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    effects = [event["data"]["effect"] for event in events if event["type"] == "decision_applied"]
    assert "scope_cancelled" in effects
    assert "replan_task_created" in effects
    memories = [
        json.loads(line)
        for line in (tmp_path / ".asteria" / "memory" / "decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [memory["source"]["effect"] for memory in memories] == [
        "scope_cancelled",
        "replan_task_created",
    ]


def test_run_command_pauses_for_execution_policy_approval_and_resumes(tmp_path: Path) -> None:
    paused = RunCommand(
        tmp_path,
        "create a complete module",
        max_iterations=2,
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeApprovalExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    assert paused.status == "paused"
    assert not (tmp_path / "complete_module.py").exists()
    run_dir = tmp_path / ".asteria" / "runs" / paused.run_id
    decisions = [
        json.loads(line)
        for line in (run_dir / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[0]["metadata"]["kind"] == "execution_policy_approval"
    assert decisions[0]["metadata"]["task_id"] == "task-0001"

    DecideCommand(
        tmp_path,
        run_id=paused.run_id,
        decision_id="decision-0001",
        select_option_id="approve_once",
    ).run()
    resumed = ResumeCommand(
        tmp_path,
        run_id=paused.run_id,
        max_iterations=2,
        execute_model_client=FakeApprovalExecuteClient(),
        review_model_client=FakeReviewClient(),
    ).run()

    assert resumed.status == "completed"
    assert resumed.applied_decisions == 1
    assert resumed.created_tasks == 0
    assert (tmp_path / "complete_module.py").exists()
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["status"] == "done"


class FakeNoVerificationExecuteClient:
    """Execute client that writes the file but skips all verification commands."""

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Create module without running any verification.",
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
                    "verification": [],
                    "completion_notes": "wrote file, no verification run",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


class FakeResearchPlanClient:
    """Plan client that creates a research task (no verification required) to avoid debug cycle."""

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "create a complete module",
                    "normalized_goal": "Create a complete module",
                    "goal_type": "software_tool",
                    "assumptions": [],
                    "constraints": [],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Research the module structure",
                            "source": "inferred",
                            "acceptance": ["research done"],
                            "task_kind": "research",
                        }
                    ],
                    "target_outputs": [],
                    "definition_of_done": ["module created"],
                    "verification_strategy": [],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class FakeResearchExecuteClient:
    """Execute client that completes a research task using only a readonly tool call."""

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "summary": "Research complete, no verification required.",
                    "tool_calls": [
                        {
                            "tool_name": "read_file",
                            "args": {"path": "AGENTS.md"},
                            "reason": "read project guidance for research",
                        }
                    ],
                    "verification": [],
                    "completion_notes": "research task completed without verification",
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(15, 25, 40),
            model_provider="fake",
            model_name="fake-execute",
            raw_response={},
        )


def test_final_report_marks_implemented_unverified_when_no_verification_calls(
    tmp_path: Path,
) -> None:
    # Use a research task (requires_verification=False) so the task completes without
    # needing a debug cycle, while still leaving tool_calls.jsonl with no run_command calls.
    result = RunCommand(
        tmp_path,
        "create a complete module",
        max_iterations=2,
        plan_model_client=FakeResearchPlanClient(),
        execute_model_client=FakeResearchExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    final_report = (run_dir / "final_report.md").read_text(encoding="utf-8")
    assert "implemented_unverified" in final_report
    assert "No verification commands" in final_report


def test_final_report_includes_verification_evidence_section(tmp_path: Path) -> None:
    result = RunCommand(
        tmp_path,
        "create a complete module",
        max_iterations=2,
        plan_model_client=FakePlanClient(),
        execute_model_client=FakeExecuteClient(),
        review_model_client=FakeReviewClient(),
        enable_research=False,
    ).run()

    run_dir = tmp_path / ".asteria" / "runs" / result.run_id
    final_report = (run_dir / "final_report.md").read_text(encoding="utf-8")
    assert "## Verification Evidence" in final_report
    assert "run_command" in final_report
    assert "complete" in final_report
