import json
from pathlib import Path

import pytest

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from tests.helpers.spine import spine_response

# RA7b slice 3: this file drives the 立真身 spine (production default) — its execute fakes speak the
# model-driven turn contract, so opt every test out of the conftest legacy-FSM pin.
pytestmark = [pytest.mark.workflow, pytest.mark.spine_default]


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "create a reviewed module",
                    "normalized_goal": "Create a reviewed module",
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
                    "target_outputs": ["reviewed_module.py"],
                    "definition_of_done": ["answer() returns 42"],
                    "verification_strategy": ["python command"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-plan",
            raw_response={},
        )


class FakeExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return spine_response(
            request,
            narration="创建 reviewed_module 并验证。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "reviewed_module.py",
                        "content": "def answer():\n    return 42\n",
                        "overwrite": True,
                    },
                },
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": (
                            "python -c "
                            '"from reviewed_module import answer; assert answer() == 42"'
                        )
                    },
                },
            ],
            model_name="fake-execute",
        )


class FakeDocPlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "Create docs/p0_matrix_doc_update.md with heading",
                    "normalized_goal": "Create a small documentation artifact",
                    "goal_type": "documentation",
                    "assumptions": [],
                    "constraints": ["local filesystem only"],
                    "non_goals": [],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Create a markdown file with a heading",
                            "source": "user",
                            "acceptance": ["file can be read back"],
                        }
                    ],
                    "target_outputs": ["docs/p0_matrix_doc_update.md"],
                    "definition_of_done": ["document exists"],
                    "verification_strategy": ["read generated artifact"],
                    "budget": {"max_iterations": 3, "max_model_calls": 10},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 20, 30),
            model_provider="fake",
            model_name="fake-doc-plan",
            raw_response={},
        )


class FakeDocReadbackExecuteClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return spine_response(
            request,
            narration="创建文档并读回验证。",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "args": {
                        "path": "docs/p0_matrix_doc_update.md",
                        "content": "# P0 Matrix Doc Update\n\n- Evidence captured\n",
                        "overwrite": True,
                    },
                },
                {
                    "tool_name": "read_file",
                    "args": {"path": "docs/p0_matrix_doc_update.md"},
                },
            ],
            model_name="fake-doc-execute",
        )


class FakeReviewClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        assert "runtime_os_evidence" in payload["trajectory"]
        assert "prompt_envelope" in payload
        assert "capability_manifest" in payload["prompt_envelope"]
        assert payload["tool_observations"]
        assert all("next_hint" in item for item in payload["tool_observations"])
        assert "tool_observation_actions" in payload
        assert payload["trajectory"]["tool_observations"]
        assert "tool_observation_actions" in payload["trajectory"]
        assert payload["trajectory"]["worker_results"]
        assert "runtime_os_summary" in payload["deterministic_checks"]
        assert payload["deterministic_checks"]["worker_result_count"] == 1
        assert payload["deterministic_checks"]["task_completion_rate"] == 1
        assert payload["deterministic_checks"]["verification_pass_rate"] == 1
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
                },
                ensure_ascii=False,
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
                                "title": "Add online breach API",
                                "description": "Use an external API to check leaked passwords.",
                                "category": "privacy",
                                "impact": {
                                    "scope": "medium",
                                    "budget": "low",
                                    "risk": "high",
                                    "quality": "high",
                                },
                                "decision_question": "Should the tool use an online breach API?",
                                "decision_options": [
                                    {
                                        "option_id": "local_only",
                                        "label": "Stay local only",
                                        "tradeoff": "Best privacy; lower breach coverage.",
                                    },
                                    {
                                        "option_id": "online_api",
                                        "label": "Use online API",
                                        "tradeoff": (
                                            "Better coverage; sends data to a network service."
                                        ),
                                    },
                                ],
                                "recommended_option_id": "local_only",
                                "default_option_id": "local_only",
                            }
                        ],
                    },
                    "trajectory_eval": {"blocked_task_count": 0, "repair_success_rate": 1.0},
                    "cost_eval": {"status": "within_budget"},
                    "overall": {
                        "status": "partial",
                        "score": 0.75,
                        "reason": "Needs a privacy decision before expanding scope.",
                    },
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(20, 30, 50),
            model_provider="fake",
            model_name="fake-review",
            raw_response={},
        )


class FakeSparseReviewClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = json.loads(request.messages[-1].content)
        return ChatResponse(
            content=json.dumps(
                {
                    "run_id": payload["run_id"],
                    "overall": {
                        "status": "pass",
                        "score": 0.9,
                        "reason": "Looks good.",
                    },
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(20, 30, 50),
            model_provider="fake",
            model_name="fake-review",
            raw_response={},
        )


class FakeNonJsonReviewClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="The run looks good, but this is not JSON.",
            finish_reason="stop",
            usage=TokenUsage(20, 30, 50),
            model_provider="fake",
            model_name="fake-review",
            raw_response={},
        )


def test_review_command_writes_eval_and_markdown_reports(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()
    assert execute.completed == 1

    result = ReviewCommand(tmp_path, run_id=plan.run_id, model_client=FakeReviewClient()).run()

    assert result.status == "pass"
    assert result.score == 0.92
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    review_envelope = json.loads(
        (run_dir / "prompt_envelope_review.json").read_text(encoding="utf-8")
    )
    assert review_envelope["mode"] == "review"
    assert "delegation_contract" in review_envelope["section_order"]
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert eval_report["overall"]["status"] == "pass"
    review_md = (run_dir / "review_report.md").read_text(encoding="utf-8")
    assert review_md.startswith("# Review Report")
    assert "## Conclusion" in review_md
    assert "## Blocking Reasons" in review_md
    assert "## Evidence Chain" in review_md
    assert "## Latest Agent Next Action" in review_md
    assert "## Next Actions" in review_md
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "completed"
    assert run["current_phase"] == "REVIEWED"
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 4
    assert cost_report["estimated_input_tokens"] == 60
    assert cost_report["estimated_output_tokens"] == 100
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["channel"] == "validation"
        and event["event_type"] == "validation_result"
        and event["data"]["validation"]["status"] == "pass"
        for event in user_progress
    )
    assert any(
        event["channel"] == "evidence"
        and event["event_type"] == "evidence"
        and str(result.review_report_path) in event["artifact_refs"]
        for event in user_progress
    )
    assert any(event["title"] == "评审完成" for event in user_progress)
    active_goal = json.loads(
        (tmp_path / ".asteria" / "memory" / "active_goal.json").read_text(encoding="utf-8")
    )
    assert active_goal["updated_by"] == "review"
    assert active_goal["update_reason"] == "review_passed"
    assert active_goal["current_result"]["review"] == "passed"


def test_review_command_uses_deterministic_first_for_fast_path_without_model_client(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()
    assert execute.completed == 1

    result = ReviewCommand(tmp_path, run_id=plan.run_id).run()

    assert result.status == "pass"
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    review_tier = eval_report["trajectory_eval"]["review_tier"]
    assert review_tier["mode"] == "deterministic_first"
    assert review_tier["accepted_without_model"] is True
    assert review_tier["fast_path"]["task_kind"] == "simple_file"
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 3
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["title"] == "确定性评审通过" for event in user_progress)


def test_review_command_accepts_recovered_fast_path_worker_failure_without_model_call(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()
    assert execute.completed == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    with (run_dir / "worker_results.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "worker_result_id": "worker-result-recovered-failure",
                    "worker_invocation_id": "worker-recovered-failure",
                    "run_id": plan.run_id,
                    "task_id": "task-0001",
                    "status": "failed",
                    "artifact_refs": [],
                    "validation_refs": [],
                    "failure_evidence_refs": ["task_execution_evidence.jsonl"],
                    "cost": {"model_calls": 1, "tool_calls": 0},
                    "summary": "Earlier attempt failed before a later successful repair.",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    result = ReviewCommand(tmp_path, run_id=plan.run_id).run()

    assert result.status == "pass"
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    review_tier = eval_report["trajectory_eval"]["review_tier"]
    assert review_tier["mode"] == "deterministic_first"
    assert review_tier["accepted_without_model"] is True
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 3


def test_review_command_accepts_doc_fast_path_readback_without_model_call(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(
        tmp_path,
        "create a documentation artifact",
        model_client=FakeDocPlanClient(),
    ).run()
    execute = ExecuteCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeDocReadbackExecuteClient(),
    ).run()
    assert execute.completed == 1

    result = ReviewCommand(tmp_path, run_id=plan.run_id).run()

    assert result.status == "pass"
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    review_tier = eval_report["trajectory_eval"]["review_tier"]
    assert review_tier["mode"] == "deterministic_first"
    assert review_tier["accepted_without_model"] is True
    assert review_tier["fast_path"]["task_kind"] == "doc_update"
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 3


def test_review_command_requires_command_verification_for_bugfix_fast_path(
    tmp_path: Path,
) -> None:
    blockers = ReviewCommand(tmp_path)._tiered_review_blockers(
        {
            "task_completion_rate": 1.0,
            "blocked_task_count": 0,
            "verification_call_count": 1,
            "verification_pass_rate": 1.0,
            "command_verification_call_count": 0,
            "command_verification_pass_rate": 0.0,
            "unrecovered_failed_worker_result_count": 0,
            "merge_gate_block_count": 0,
            "pending_runtime_request_count": 0,
            "cost_status": "within_budget",
        },
        fast_path_task_kind="bug_fix",
    )

    assert "missing_command_verification_call" in blockers


def test_fast_path_overall_score_is_unverified_without_executable_verification(
    tmp_path: Path,
) -> None:
    # ADR-0016 §3: a fast-path run with NO executable verification (doc/creative) must NOT report a
    # fabricated 0.9 green score — the status stays the deterministic "pass" invariant but the score
    # is None ("unverified"), matching ReviewAgent._overall's de-fabrication.
    command = ReviewCommand(tmp_path)

    unverified = command._fast_path_overall(None)
    assert unverified["status"] == "pass"
    assert unverified["score"] is None
    assert "unverified" in unverified["reason"].lower()

    # With real executable verification evidence, the score IS the real pass rate (not a constant).
    verified = command._fast_path_overall({"status": "pass", "score": 0.5, "reason": "1/2 passed"})
    assert verified["status"] == "pass"
    assert verified["score"] == 0.5


def test_review_command_treats_discarded_replanned_worker_failure_as_recovered(
    tmp_path: Path,
) -> None:
    command = ReviewCommand(tmp_path)

    count = command._unrecovered_failed_worker_count(
        [{"task_id": "task-0001", "status": "failed"}],
        [{"task_id": "task-0002", "status": "done", "contract_check": {"ok": True}}],
        discarded_task_ids={"task-0001"},
        all_active_tasks_done=True,
    )

    assert count == 0


def test_review_command_keeps_discarded_worker_failure_when_active_work_not_done(
    tmp_path: Path,
) -> None:
    command = ReviewCommand(tmp_path)

    count = command._unrecovered_failed_worker_count(
        [{"task_id": "task-0001", "status": "failed"}],
        [{"task_id": "task-0002", "status": "blocked"}],
        discarded_task_ids={"task-0001"},
        all_active_tasks_done=False,
    )

    assert count == 1


def test_review_command_reports_high_risk_follow_up_without_orchestrating(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()
    assert execute.completed == 1

    result = ReviewCommand(
        tmp_path,
        run_id=plan.run_id,
        model_client=FakeDecisionReviewClient(),
    ).run()

    assert result.status == "partial"
    assert result.follow_up_count == 0
    assert result.decision_count == 0
    assert result.recommended_next_command == "resume"
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    assert not (run_dir / "decisions.jsonl").exists()
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "running"
    assert run["current_phase"] == "REVIEWED"
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    review_validation = [
        event for event in user_progress if event["event_type"] == "validation_result"
    ][-1]
    assert review_validation["status"] == "blocked"
    assert review_validation["data"]["validation"]["decision_count"] == 0
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert len(task_plan["tasks"]) == 1
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 4
    assert cost_report["user_decisions"] == 0


def test_review_command_normalizes_sparse_eval_report(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()
    assert execute.completed == 1

    result = ReviewCommand(
        tmp_path, run_id=plan.run_id, model_client=FakeSparseReviewClient()
    ).run()

    assert result.status == "pass"
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert eval_report["schema_version"] == "0.1.0"
    assert eval_report["goal_eval"]["requirement_coverage"] == 1.0
    assert eval_report["artifact_eval"]["logs_present"]
    assert eval_report["outcome_eval"]["run_success"]


def test_review_command_falls_back_to_deterministic_report_for_non_json_response(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()
    assert execute.completed == 1

    result = ReviewCommand(tmp_path, run_id=plan.run_id, model_client=FakeNonJsonReviewClient()).run()

    assert result.status == "pass"
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert eval_report["overall"]["status"] == "pass"
    assert "deterministic runtime checks" in eval_report["overall"]["reason"]
    assert "review_model_parse_error" in eval_report["trajectory_eval"]


def test_review_command_excludes_discarded_replan_history_from_completion_rate(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()
    assert execute.completed == 1
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan_path = run_dir / "task_plan.json"
    task_plan = json.loads(task_plan_path.read_text(encoding="utf-8"))
    original = dict(task_plan["tasks"][0])
    original["task_id"] = "task-0000"
    original["status"] = "discarded"
    original["notes"] = "Superseded by task-0001 during replan."
    task_plan["tasks"].insert(0, original)
    task_plan_path.write_text(json.dumps(task_plan), encoding="utf-8")

    result = ReviewCommand(tmp_path, run_id=plan.run_id, model_client=FakeReviewClient()).run()

    assert result.status == "pass"
    eval_report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert eval_report["goal_eval"]["requirement_coverage"] == 1.0
    assert eval_report["outcome_eval"]["run_success"]


def test_review_command_includes_collaboration_summary_in_markdown_report(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "create a reviewed module", model_client=FakePlanClient()).run()
    execute = ExecuteCommand(tmp_path, run_id=plan.run_id, model_client=FakeExecuteClient()).run()
    assert execute.completed == 1

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    # Seed a minimal agent_run_graph with collaboration_summary
    agent_run_graph = {
        "schema_version": "0.1.0",
        "agent_run_graph_id": "agent-run-graph-test",
        "run_id": plan.run_id,
        "status": "succeeded",
        "coordination_modes": ["sequential"],
        "max_concurrency_observed": 1,
        "child_worker_plans": [],
        "collaboration_summary": {
            "total_workers": 2,
            "successful_workers": 1,
            "failed_workers": 1,
            "blocked_workers": 0,
            "total_model_calls": 4,
            "total_tool_calls": 8,
            "artifact_refs": ["out.py"],
            "validation_refs": [],
            "failure_evidence_refs": ["task_execution_evidence.jsonl"],
            "merge_strategy": "merge_gate_then_promotion_queue",
            "collaboration_protocol": {
                "isolation_model": "isolated_workspace",
                "review_agent_role": "evaluator",
                "debug_agent_role": "repairer",
                "merge_gate_role": "gatekeeper",
                "promotion_queue_role": "coordinator",
            },
            "strategy_modes": [],
            "next_actions": ["Debug failed child worker plans before widening concurrency."],
        },
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    from asteria_runtime.storage.json_store import JsonStore
    from asteria_runtime.storage.schema_validator import SchemaValidator

    JsonStore(SchemaValidator(Path.cwd() / "schemas")).write(
        run_dir / "agent_run_graph.json", agent_run_graph, "agent_run_graph"
    )

    result = ReviewCommand(tmp_path, run_id=plan.run_id, model_client=FakeSparseReviewClient()).run()

    assert result.status == "pass"
    review_md = (run_dir / "review_report.md").read_text(encoding="utf-8")
    assert "## Multi-Agent Collaboration" in review_md
    assert "total_workers=2" not in review_md  # rendered as text, not raw dict
    assert "Workers:" in review_md
    assert "failed=1" in review_md
    assert "Debug failed child worker" in review_md
