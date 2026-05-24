import json
from pathlib import Path

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.chat_command import ChatCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.commands.run_command import RunCommand, RunStepSummary
from asteria_runtime.commands.sessions_command import SessionsCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.models.base import ChatResponse, TokenUsage
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


class ContextAwareChatModel:
    def __init__(self) -> None:
        self.context: dict | None = None

    def chat(self, request):
        self.context = json.loads(request.messages[-1].content)["safe_project_context"]
        session = self.context["session_context"]
        workflow = session["workflow"]
        run = session["current_run"]
        return ChatResponse(
            content=(
                f"Current run {run['run_id']} is {workflow['workflow_state']}. "
                f"Latest evidence is {session['latest_evidence']['path']}. "
                "No execution was performed."
            ),
            finish_reason="stop",
            usage=TokenUsage(10, 10, 20),
            model_provider="fake",
            model_name="fake-chat",
            raw_response={},
        )


class EvidenceAwareReviewModel:
    def __init__(self, *, status: str = "pass") -> None:
        self.status = status
        self.seen_evidence_summary = False
        self.seen_model_selection = False

    def chat(self, request):
        review_context = json.loads(request.messages[-1].content)
        evidence = review_context["trajectory"]["task_execution_evidence"]
        self.seen_evidence_summary = any(
            item.get("summary") == "minimal run evidence" for item in evidence
        )
        selection = review_context.get("model_selection") or {}
        trajectory_selection = review_context["trajectory"].get("model_selection") or {}
        self.seen_model_selection = (
            selection.get("reason") == "capability_feedback_escalated_from_medium"
            and trajectory_selection == selection
        )
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": request.metadata["run_id"],
                    "goal_eval": {"requirement_coverage": 1.0},
                    "artifact_eval": {"artifacts_present": True, "logs_present": True},
                    "outcome_eval": {"verification_pass_rate": 1.0, "run_success": True},
                    "trajectory_eval": {
                        "blocked_task_count": 0,
                        "reviewed_evidence_summary": evidence[-1]["summary"],
                    },
                    "cost_eval": {"status": "within_budget", "model_calls": 0, "tool_calls": 1},
                    "overall": {
                        "status": self.status,
                        "score": 0.95 if self.status == "pass" else 0.55,
                        "reason": (
                            "Evidence-backed minimal run is complete."
                            if self.status == "pass"
                            else "Verification evidence is incomplete."
                        ),
                    },
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20),
            model_provider="fake",
            model_name="evidence-aware-reviewer",
            raw_response={},
        )


class ClassifiedReviewModel:
    def __init__(self, *, kind: str) -> None:
        self.kind = kind

    def chat(self, request):
        if self.kind == "plan_gap":
            goal_eval = {"requirement_coverage": 0.4}
            artifact_eval = {"artifacts_present": False, "logs_present": True}
            outcome_eval = {"verification_pass_rate": 1.0, "run_success": False}
            trajectory_eval = {"blocked_task_count": 0}
            reason = "Requirements are not covered by the current task plan."
        elif self.kind == "decision":
            goal_eval = {"requirement_coverage": 1.0}
            artifact_eval = {"artifacts_present": True, "logs_present": True}
            outcome_eval = {
                "verification_pass_rate": 1.0,
                "run_success": False,
                "follow_up_tasks": [
                    {
                        "title": "Deploy to production",
                        "description": (
                            "Deploy to production using network credentials and external API access."
                        ),
                        "category": "deployment",
                        "risk_impact": "high",
                        "budget_impact": "high",
                        "requires_decision": True,
                    }
                ],
            }
            trajectory_eval = {"blocked_task_count": 0}
            reason = "The remaining work is high risk and needs user approval."
        else:
            goal_eval = {"requirement_coverage": 1.0}
            artifact_eval = {"artifacts_present": True, "logs_present": True}
            outcome_eval = {"verification_pass_rate": 0.0, "run_success": False}
            trajectory_eval = {"blocked_task_count": 0}
            reason = "Verification failed."
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "run_id": request.metadata["run_id"],
                    "goal_eval": goal_eval,
                    "artifact_eval": artifact_eval,
                    "outcome_eval": outcome_eval,
                    "trajectory_eval": trajectory_eval,
                    "cost_eval": {"status": "within_budget", "model_calls": 0, "tool_calls": 1},
                    "overall": {"status": "partial", "score": 0.45, "reason": reason},
                }
            ),
            finish_reason="stop",
            usage=TokenUsage(input_tokens=10, output_tokens=10, total_tokens=20),
            model_provider="fake",
            model_name="classified-reviewer",
            raw_response={},
        )


def test_run_status_review_accept_user_loop(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)

    ready_for_review = StatusCommand(tmp_path).run()
    ready_payload = ready_for_review.to_dict()
    assert ready_payload["workflow_state"] == "ready_for_review"
    assert ready_payload["current_phase"] == "DONE"
    assert ready_payload["current_blocker"] is None
    assert ready_payload["can_review"] is True
    assert ready_payload["can_accept"] is False
    assert ready_payload["recommended_next_command"] == "review"

    review_model = EvidenceAwareReviewModel()
    review = ReviewCommand(tmp_path, model_client=review_model).run()
    assert review.run_id == run_id
    assert review.status == "pass"
    assert review_model.seen_evidence_summary is True
    assert review_model.seen_model_selection is True
    report_text = review.review_report_path.read_text(encoding="utf-8")
    assert "minimal run evidence" in report_text
    assert "## Model Selection" in report_text
    assert "- Reason: capability_feedback_escalated_from_medium" in report_text
    assert "- Tier pressure: medium -> strong direction=up delta=1" in report_text
    assert "- Capability feedback: blocked decision=escalated_to_strong" in report_text
    assert "model selection: strong reason=capability_feedback_escalated_from_medium" in report_text
    eval_report = JsonStore(SchemaValidator(Path("schemas"))).read(
        review.eval_report_path,
        "eval_report",
    )
    assert eval_report["trajectory_eval"]["model_selection"]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )

    ready_for_accept = StatusCommand(tmp_path).run()
    accept_payload = ready_for_accept.to_dict()
    assert accept_payload["workflow_state"] == "ready_for_accept"
    assert accept_payload["current_phase"] == "REVIEWED"
    assert accept_payload["can_review"] is False
    assert accept_payload["can_accept"] is True
    assert accept_payload["recommended_next_command"] == "accept"

    accept = AcceptCommand(tmp_path).run()
    assert accept.accepted is True
    assert accept.blockers == []
    assert accept.next_actions == ["Use the final report as the durable handoff artifact."]
    final_report = accept.final_report_path.read_text(encoding="utf-8")
    assert "## Model Selection" in final_report
    assert "- Reason: capability_feedback_escalated_from_medium" in final_report
    assert "- Tier pressure: medium -> strong direction=up delta=1" in final_report
    assert "- Capability feedback: blocked decision=escalated_to_strong" in final_report
    assert "- Matched route: coding/medium action=review_worker_route_before_scaling" in final_report
    summary_path = accept.final_report_path.with_name("final_report_summary.json")
    assert accept.final_report_summary_path == summary_path
    final_summary = JsonStore(SchemaValidator(Path("schemas"))).read(
        summary_path,
        "final_report_summary",
    )
    assert final_summary["status"] == "completed"
    assert final_summary["review_status"] == "pass"
    assert final_summary["workflow_state"] == "accepted"
    assert final_summary["final_report_path"].endswith("final_report.md")
    assert final_summary["model_selection"]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )
    assert final_summary["blockers"] == []
    assert final_summary["recommended_next_command"] is None
    assert accept.final_report_summary == final_summary
    accept_dict = accept.to_dict()
    assert accept_dict["final_report_summary_path"] == str(summary_path)
    assert accept_dict["final_report_summary"] == final_summary
    accept_text = accept.to_text()
    assert "Final report summary:" in accept_text
    assert "Model selection: strong (capability_feedback_escalated_from_medium)" in accept_text

    accepted_payload = StatusCommand(tmp_path).run().to_dict()
    assert accepted_payload["final_report_summary_path"].endswith("final_report_summary.json")
    assert accepted_payload["final_report_summary"] == final_summary
    assert accepted_payload["workflow_state"] == "accepted"
    assert accepted_payload["current_phase"] == "ACCEPTED"
    assert accepted_payload["can_accept"] is False
    assert accepted_payload["recommended_next_command"] is None


def test_review_failure_text_names_primary_blocker_and_next_command(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _create_minimal_completed_run(tmp_path)

    review = ReviewCommand(
        tmp_path,
        model_client=EvidenceAwareReviewModel(status="partial"),
    ).run()

    assert review.status == "partial"
    assert review.primary_blocker == (
        "Review verdict is partial: Verification evidence is incomplete."
    )
    assert review.recommended_next_command == "debug"
    payload = review.to_dict()
    assert payload["primary_blocker"] == review.primary_blocker
    assert payload["recommended_next_command"] == "debug"
    text = review.to_text()
    assert "Primary blocker: Review verdict is partial" in text
    assert "Recommended next command: asteria debug" in text
    report_text = review.review_report_path.read_text(encoding="utf-8")
    assert "## Failure Classification" in report_text
    assert "- Category: verification_failed" in report_text
    eval_report = JsonStore(SchemaValidator(Path("schemas"))).read(
        review.eval_report_path,
        "eval_report",
    )
    assert eval_report["failure_classification"]["recommended_command"] == "debug"


def test_goal_run_result_surfaces_user_workflow_state(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)

    result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=0,
        enable_research=False,
    ).continue_run(
        run_id,
        steps=[RunStepSummary("plan", "completed", "Existing completed plan.")],
    )

    assert result.workflow_state == "ready_for_review"
    assert result.current_phase == "DONE"
    assert result.current_blocker is None
    assert result.recommended_next_command == "review"
    assert result.next_actions == ["Run `asteria review`."]
    assert result.run_loop_summary_path is not None
    assert result.final_report_summary_path is not None
    final_summary = JsonStore(SchemaValidator(Path("schemas"))).read(
        result.final_report_summary_path,
        "final_report_summary",
    )
    assert result.final_report_summary == final_summary
    assert final_summary["workflow_state"] == "ready_for_review"
    assert final_summary["model_selection"]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )
    result_payload = result.to_dict()
    assert result_payload["final_report_summary"] == final_summary
    assert result_payload["final_report_summary_path"] == str(result.final_report_summary_path)
    assert final_summary["model_route_timeline"][0]["task_id"] == "task-0001"
    assert final_summary["model_route_timeline"][0]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )
    assert final_summary["model_route_timeline_path"] == (
        f".asteria/runs/{result.run_id}/model_route_timeline.json"
    )
    route_timeline = JsonStore(SchemaValidator(Path("schemas"))).read(
        result.final_report_path.with_name("model_route_timeline.json"),
        "model_route_timeline",
    )
    assert route_timeline["record_count"] == 1
    assert route_timeline["timeline"][0]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )
    summary = JsonStore(SchemaValidator(Path("schemas"))).read(
        result.run_loop_summary_path,
        "run_loop_summary",
    )
    assert summary["iteration_count"] == 0
    assert summary["stop_reason"] == "handoff_written"
    assert summary["workflow_state"] == "ready_for_review"
    assert summary["current_blocker"] is None
    assert summary["recommended_next_command"] == "review"
    assert summary["latest_evidence"] == {
        "path": f".asteria/runs/{run_id}/task_execution_evidence.jsonl",
        "task_id": "task-0001",
        "status": "succeeded",
        "summary": "minimal run evidence",
        "evidence_id": "evidence-0001",
    }
    text = result.to_text()
    assert "Workflow: ready_for_review" in text
    assert "Current phase: DONE" in text
    assert "Recommended next command: asteria review" in text
    assert "Final report summary:" in text
    assert "Run loop summary:" in text
    assert "Loop steps:" in text




def test_goal_loop_policy_auto_accepts_passed_review_in_auto_mode(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)

    result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=1,
        enable_research=False,
        review_model_client=EvidenceAwareReviewModel(),
        permission_level="auto",
    ).continue_run(run_id)

    assert result.status == "completed"
    assert result.workflow_state == "accepted"
    assert result.current_phase == "ACCEPTED"
    assert any(step.name == "goal-policy" and step.status == "auto_accept" for step in result.steps)
    assert any(step.name == "accept" and step.status == "accepted" for step in result.steps)
    assert result.final_report_summary["workflow_state"] == "accepted"


def test_goal_loop_policy_stops_for_explicit_accept_in_balanced_mode(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)

    result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=1,
        enable_research=False,
        review_model_client=EvidenceAwareReviewModel(),
        permission_level="balanced",
    ).continue_run(run_id)

    assert result.workflow_state == "ready_for_accept"
    assert result.current_phase == "REVIEWED"
    assert result.recommended_next_command == "accept"
    assert any(step.name == "goal-policy" and step.status == "stop_for_accept" for step in result.steps)
    assert not any(step.name == "accept" for step in result.steps)


def test_goal_loop_policy_stops_for_repair_after_failed_review(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)

    result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=1,
        enable_research=False,
        review_model_client=EvidenceAwareReviewModel(status="partial"),
        permission_level="auto",
    ).continue_run(run_id)

    assert result.status == "running"
    assert result.workflow_state == "needs_action"
    assert result.recommended_next_command == "debug"
    assert any(step.name == "goal-policy" and step.status == "stop_for_repair" for step in result.steps)
    assert result.final_report_summary["recommended_next_command"] == "debug"
    assert result.final_report_summary["goal_policy"]["recommended_command"] == "debug"


def test_goal_loop_policy_recommends_replan_for_plan_gap(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)

    result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=1,
        enable_research=False,
        review_model_client=ClassifiedReviewModel(kind="plan_gap"),
        permission_level="auto",
    ).continue_run(run_id)

    assert result.recommended_next_command == "replan"
    assert any(
        step.name == "goal-policy" and step.status == "stop_for_replan"
        for step in result.steps
    )
    assert result.final_report_summary["goal_policy"]["category"] == "plan_gap"
    assert result.final_report_summary["goal_policy"]["recommended_command"] == "replan"
    status_payload = StatusCommand(tmp_path).run().to_dict()
    assert status_payload["recommended_next_command"] == "replan"
    assert status_payload["goal_policy"]["category"] == "plan_gap"


def test_goal_loop_policy_creates_decision_for_high_risk_follow_up(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)

    result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=1,
        enable_research=False,
        review_model_client=ClassifiedReviewModel(kind="decision"),
        permission_level="auto",
    ).continue_run(run_id)

    assert result.recommended_next_command == "decide --list"
    assert any(
        step.name == "goal-policy" and step.status == "stop_for_decision"
        for step in result.steps
    )
    assert result.final_report_summary["goal_policy"]["category"] == "decision_required"
    decisions = JsonlStore(SchemaValidator(Path("schemas"))).read_all(
        tmp_path / ".asteria" / "runs" / run_id / "decisions.jsonl",
        "decision_point",
    )
    assert decisions
    assert decisions[-1]["status"] == "pending"
    assert "production" in decisions[-1]["question"].lower()


def test_budget_guard_goal_policy_is_exposed_in_final_summary(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)
    validator = SchemaValidator(Path("schemas"))
    store = JsonStore(validator)
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    cost_report = store.read(run_dir / "cost_report.json", "cost_report")
    cost_report["model_calls"] = 999
    cost_report["tool_calls"] = 999
    store.write(run_dir / "cost_report.json", cost_report, "cost_report")

    result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=1,
        enable_research=False,
        permission_level="auto",
    ).continue_run(run_id)

    assert result.recommended_next_command.startswith("decide --decision-id")
    assert result.final_report_summary["goal_policy"]["category"] == "budget_guard"
    assert result.final_report_summary["goal_policy"]["recommended_command"] == "decide --list"
    status_payload = StatusCommand(tmp_path).run().to_dict()
    assert status_payload["goal_policy"]["category"] == "budget_guard"


def test_status_and_sessions_context_expose_run_loop_summary(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)
    result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=0,
        enable_research=False,
    ).continue_run(run_id)
    assert result.run_loop_summary_path is not None

    status_payload = StatusCommand(tmp_path).run().to_dict()
    status_context = status_payload["current_context"]
    assert status_payload["run_loop_summary_path"] == (
        f".asteria/runs/{run_id}/run_loop_summary.json"
    )
    assert status_payload["run_loop_summary"]["workflow_state"] == "ready_for_review"
    assert status_payload["run_loop_summary"]["recommended_next_command"] == "review"
    assert status_context["run_loop_summary_path"] == (
        f".asteria/runs/{run_id}/run_loop_summary.json"
    )
    assert status_context["run_loop_summary"]["workflow_state"] == "ready_for_review"
    assert status_context["run_loop_summary"]["recommended_next_command"] == "review"
    assert status_payload["model_route_timeline"][0]["task_id"] == "task-0001"
    assert status_payload["model_route_timeline"][0]["purpose"] == "coding"
    assert status_payload["model_route_timeline"][0]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )

    sessions = SessionsCommand(tmp_path, include_context=True).run()
    session_context = sessions.context[run_id]
    assert session_context["run_loop_summary_path"] == status_context["run_loop_summary_path"]
    assert session_context["run_loop_summary"] == status_context["run_loop_summary"]
    assert session_context["model_route_timeline"] == status_payload["model_route_timeline"]
    assert "run loop summary:" in sessions.to_text()
    assert "Model route timeline: 1 recent decision(s)" in StatusCommand(tmp_path).run().to_text()
    assert session_context["model_route_timeline_path"] == f".asteria/runs/{run_id}/model_route_timeline.json"


def test_chat_safely_summarizes_current_session_without_execution(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)
    run_result = RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=0,
        enable_research=False,
    ).continue_run(run_id)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and ".asteria" not in path.relative_to(tmp_path).parts
    }
    chat_model = ContextAwareChatModel()

    chat = ChatCommand(
        tmp_path,
        "当前任务到什么状态了？需要我执行什么吗？",
        model_client=chat_model,
    ).run()

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file() and ".asteria" not in path.relative_to(tmp_path).parts
    }
    assert after == before
    assert chat.execution_allowed is False
    assert chat.session_context["current_run"]["run_id"] == run_id
    assert chat.session_context["workflow"]["workflow_state"] == "ready_for_review"
    assert chat.session_context["workflow"]["recommended_next_command"] == "review"
    assert chat.session_context["latest_evidence"]["path"] == (
        f".asteria/runs/{run_id}/task_execution_evidence.jsonl"
    )
    assert chat.session_context["model_selection"]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )
    assert chat.session_context["model_route_timeline"][0]["selected_tier"] == "strong"
    assert chat_model.context["session_context"]["model_route_timeline"][0]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )
    assert f"Current session recommends `asteria {run_result.recommended_next_command}`." in (
        chat.next_actions
    )
    assert "Current session:" in chat.to_text()
    assert chat.to_dict()["execution_allowed"] is False
    assert chat_model.context is not None
    assert chat_model.context["session_context"]["workflow"]["workflow_state"] == (
        "ready_for_review"
    )


def test_status_exposes_latest_model_selection_pressure_and_feedback(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _create_minimal_completed_run(tmp_path)

    payload = StatusCommand(tmp_path).run().to_dict()
    selection = payload["model_selection"]

    assert selection["reason"] == "capability_feedback_escalated_from_medium"
    assert selection["tier_pressure"]["direction"] == "up"
    assert selection["tier_pressure"]["uses_stronger_than_default"] is True
    assert selection["capability_feedback"]["status"] == "blocked"
    assert selection["capability_feedback"]["matched_route"]["recommended_action"] == (
        "review_worker_route_before_scaling"
    )
    assert payload["current_context"]["latest_execution_evidence"]["model_selection"] == selection
    assert payload["current_context"]["model_selection"] == selection
    assert payload["current_context"]["model_route_timeline"][0]["reason"] == selection["reason"]
    text = StatusCommand(tmp_path).run().to_text()
    assert (
        "Model selection: strong for coding "
        "(capability_feedback_escalated_from_medium)"
    ) in text
    assert "pressure: medium -> strong (stronger route selected, direction=up) delta=1" in text
    assert "capability feedback: blocked (escalated_to_strong; blocking=1, review=0)" in text
    assert "matched route: coding/medium action=review_worker_route_before_scaling" in text


def test_goal_run_result_uses_explicit_session_status_when_not_current(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    target_run_id = _create_minimal_completed_run(tmp_path)
    validator = SchemaValidator(Path("schemas"))
    run_store = RunStore(tmp_path / ".asteria", validator)
    other_run = run_store.create_run("/run", goal_id="goal-other")
    run_store.set_current_session(other_run["run_id"], "switch current away")

    result = RunCommand(
        tmp_path,
        run_id=target_run_id,
        max_iterations=0,
        enable_research=False,
    ).continue_run(
        target_run_id,
        steps=[RunStepSummary("plan", "completed", "Existing completed plan.")],
    )

    assert result.run_id == target_run_id
    assert result.workflow_state == "ready_for_review"
    assert result.current_phase == "DONE"
    assert result.recommended_next_command == "review"


def test_review_report_includes_model_route_readiness_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    InitCommand(tmp_path).run()
    _create_minimal_completed_run(tmp_path)
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "openai-compatible")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "strong-model")
    monkeypatch.delenv("AGENT_MODEL_STRONG_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    run_id = RunStore(
        tmp_path / ".asteria",
        SchemaValidator(Path("schemas")),
    ).current_session_id()
    assert run_id is not None
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    JsonlStore(SchemaValidator(Path("schemas"))).append(
        run_dir / "model_profiles.jsonl",
        {
            "schema_version": "0.1.0",
            "model_profile_id": "model-profile-0001",
            "purpose": "coding",
            "provider": "openai-compatible",
            "model_name": "strong-model",
            "model_tier": "strong",
        },
        "model_profile",
    )

    review = ReviewCommand(
        tmp_path,
        model_client=EvidenceAwareReviewModel(status="partial"),
    ).run()

    report = review.review_report_path.read_text(encoding="utf-8")
    assert "## Model Route Readiness" in report
    assert "- Status: blocked" in report
    assert "AGENT_MODEL_STRONG_API_KEY or AGENT_MODEL_API_KEY or OPENAI_API_KEY" in report
    assert "model routes=blocked" in report
    eval_report = JsonStore(SchemaValidator(Path("schemas"))).read(
        review.eval_report_path,
        "eval_report",
    )
    assert eval_report["trajectory_eval"]["route_readiness"]["status"] == "blocked"


def _create_minimal_completed_run(root: Path) -> str:
    validator = SchemaValidator(Path("schemas"))
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    run_store = RunStore(root / ".asteria", validator)
    run = run_store.create_run("/run", goal_id="goal-workflow")
    run_id = run["run_id"]
    run_dir = run_store.run_dir(run_id)
    run.update(
        {
            "status": "completed",
            "current_phase": "DONE",
            "summary": "Minimal run completed and ready for review.",
            "ended_at": now_iso(),
        }
    )
    run_store.update_run(run)
    run_store.set_current_session(run_id, "workflow test")
    store.write(
        run_dir / "goal_spec.json",
        {
            "schema_version": "0.1.0",
            "goal_id": "goal-workflow",
            "original_goal": "Create a minimal verified workflow.",
            "normalized_goal": "Create a minimal verified workflow.",
            "goal_type": "codebase_improvement",
            "assumptions": [],
            "constraints": [],
            "non_goals": [],
            "expanded_requirements": [
                {
                    "id": "REQ-1",
                    "priority": "must",
                    "description": "Produce evidence for review and acceptance.",
                    "source": "user",
                    "acceptance": ["status, review, and accept can inspect the run"],
                }
            ],
            "target_outputs": ["workflow evidence"],
            "definition_of_done": ["review passes", "accept completes"],
            "verification_strategy": ["unit workflow test"],
            "budget": {},
        },
        "goal_spec",
    )
    store.write(
        run_dir / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Minimal workflow task",
                    "status": "done",
                    "summary": "Minimal task completed.",
                }
            ],
        },
        "task_board",
    )
    store.write(
        run_dir / "cost_report.json",
        {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "model_calls": 0,
            "tool_calls": 1,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "strong_model_calls": 0,
            "cheap_model_calls": 0,
            "repair_attempts": 0,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        },
        "cost_report",
    )
    created_at = now_iso()
    jsonl.append(
        run_dir / "task_execution_evidence.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "evidence-0001",
            "run_id": run_id,
            "task_id": "task-0001",
            "status": "succeeded",
            "summary": "minimal run evidence",
            "task": {"task_id": "task-0001", "title": "Minimal workflow task"},
            "action": {
                "kind": "test_setup",
                "model_selection": {
                    "purpose": "coding",
                    "task_kind": "implementation",
                    "default_tier": "medium",
                    "strategy_tier": "medium",
                    "selected_tier": "strong",
                    "strategy": "quality",
                    "reason": "capability_feedback_escalated_from_medium",
                    "tier_pressure": {
                        "default_tier": "medium",
                        "strategy_tier": "medium",
                        "selected_tier": "strong",
                        "direction": "up",
                        "delta": 1,
                        "uses_stronger_than_default": True,
                        "uses_cheaper_than_default": False,
                    },
                    "capability_feedback": {
                        "status": "blocked",
                        "decision": "escalated_to_strong",
                        "matched_route": {
                            "purpose": "coding",
                            "model_tier": "medium",
                            "recommended_action": "review_worker_route_before_scaling",
                        },
                        "blocking_count": 1,
                        "review_count": 0,
                        "recommended_actions": [
                            "Pause scaling affected routes until provider, worker, or budget issues are resolved."
                        ],
                        "provider_route_strategy": {},
                    },
                },
            },
            "candidate": {"artifact_refs": ["task_plan.json"]},
            "contract_check": {"ok": True},
            "tool_results": [{"tool": "run_command", "ok": True}],
            "verification_results": [{"name": "workflow setup", "status": "pass"}],
            "created_at": created_at,
        },
        "task_execution_evidence",
    )
    jsonl.append(
        run_dir / "tool_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "tool_call_id": "toolcall-0001",
            "run_id": run_id,
            "task_id": "task-0001",
            "agent_id": "WorkflowTest",
            "tool_name": "run_tests",
            "input_summary": "pytest workflow",
            "output_summary": "passed",
            "status": "success",
            "started_at": created_at,
            "ended_at": created_at,
            "error": None,
        },
        "tool_call",
    )
    return run_id

