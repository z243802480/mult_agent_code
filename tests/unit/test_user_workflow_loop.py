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
        self.context_envelope: dict | None = None
        self.request = None

    def chat(self, request):
        self.request = request
        payload = json.loads(request.messages[-1].content)
        self.context_envelope = payload["context_envelope"]
        self.context = self.context_envelope["payload"]
        assert payload["context"] == self.context_envelope
        assert "safe_project_context" not in payload
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


class FailingReviewModel:
    def chat(self, request):
        raise RuntimeError("stream deadline exceeded")


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
    assert (
        "- Active next step: Use the selected stronger route for coding/medium; review results before scaling."
        in report_text
    )
    assert "Pause scaling affected routes" not in report_text
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
    active_goal = tmp_path / ".asteria" / "memory" / "active_goal.md"
    assert active_goal.exists()
    active_goal_text = active_goal.read_text(encoding="utf-8")
    assert "# Asteria Active Goal" in active_goal_text
    assert "## Current Goal" in active_goal_text
    assert "## Overall Plan" in active_goal_text
    assert "## Completed Work" in active_goal_text
    assert "## Next Task" in active_goal_text
    assert run_id not in active_goal_text
    assert "task_execution_evidence" not in active_goal_text
    assert "model_route" not in active_goal_text
    active_goal_json = tmp_path / ".asteria" / "memory" / "active_goal.json"
    assert active_goal_json.exists()
    active_goal_state = JsonStore(SchemaValidator(Path("schemas"))).read(
        active_goal_json,
        "active_goal_memory",
    )
    assert active_goal_state["source_run_id"] == run_id
    assert active_goal_state["updated_by"] == "accept"
    assert active_goal_state["update_reason"] == "accepted_result"
    assert active_goal_state["current_result"]["state"] == "accepted"
    assert active_goal_state["current_result"]["completion"] == "accepted"
    final_report = accept.final_report_path.read_text(encoding="utf-8")
    assert "- Completion: accepted" in final_report
    assert "## Model Selection" in final_report
    assert "- Reason: capability_feedback_escalated_from_medium" in final_report
    assert "- Tier pressure: medium -> strong direction=up delta=1" in final_report
    assert "- Capability feedback: blocked decision=escalated_to_strong" in final_report
    assert (
        "- Active next step: Use the selected stronger route for coding/medium; review results before scaling."
        in final_report
    )
    assert "Pause scaling affected routes" not in final_report
    summary_path = accept.final_report_path.with_name("final_report_summary.json")
    assert accept.final_report_summary_path == summary_path
    final_summary = JsonStore(SchemaValidator(Path("schemas"))).read(
        summary_path,
        "final_report_summary",
    )
    assert final_summary["status"] == "completed"
    assert final_summary["review_status"] == "pass"
    assert final_summary["workflow_state"] == "accepted"
    assert final_summary["main_path"]["path"] == (
        "Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop"
    )
    assert final_summary["main_path"]["active_stage"] == "stop"
    assert final_summary["todo_view"]["counts"]["completed"] == 1
    assert final_summary["main_path"]["todo_view"]["summary"].startswith("All 1 todo item")
    assert final_summary["runtime_progress"]["active_stage"] == "stop"
    assert final_summary["runtime_progress"]["next_command"] is None
    assert final_summary["runtime_progress"]["todo"]["counts"]["completed"] == 1
    assert final_summary["final_report_path"].endswith("final_report.md")
    assert final_summary["model_selection"]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )
    assert final_summary["blockers"] == []
    assert final_summary["recommended_next_command"] is None
    assert final_summary["recommended_next_command"] == final_summary["main_path"]["next_command"]
    assert accept.final_report_summary == final_summary
    accept_dict = accept.to_dict()
    assert accept_dict["final_report_summary_path"] == str(summary_path)
    assert accept_dict["final_report_summary"] == final_summary
    accept_text = accept.to_text()
    assert "Final report summary:" in accept_text
    assert "Model selection: strong (capability_feedback_escalated_from_medium)" in accept_text

    accepted_payload = StatusCommand(tmp_path).run().to_dict()
    assert accepted_payload["active_goal_state"] == active_goal_state
    assert accepted_payload["final_report_summary_path"].endswith("final_report_summary.json")
    assert accepted_payload["final_report_summary"] == final_summary
    assert accepted_payload["workflow_state"] == "accepted"
    assert accepted_payload["current_phase"] == "ACCEPTED"
    assert accepted_payload["can_accept"] is False
    assert accepted_payload["recommended_next_command"] is None
    assert accepted_payload["recommended_next_command"] == accepted_payload["main_path"][
        "next_command"
    ]
    assert accepted_payload["runtime_progress"]["active_stage"] == "stop"
    assert accepted_payload["runtime_progress"]["next_command"] is None
    assert accepted_payload["run_loop_summary"]["workflow_state"] == "accepted"
    assert accepted_payload["run_loop_summary"]["recommended_next_command"] is None
    assert accepted_payload["run_loop_summary"]["main_path"]["active_stage"] == "stop"
    assert accepted_payload["run_loop_summary"]["runtime_progress"]["active_stage"] == "stop"


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


def test_status_ignores_task_failure_superseded_by_done_evidence(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)
    validator = SchemaValidator(Path("schemas"))
    jsonl = JsonlStore(validator)
    run_dir = tmp_path / ".asteria" / "runs" / run_id

    jsonl.append(
        run_dir / "task_failures.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "task-failure-0001",
            "run_id": run_id,
            "task_id": "task-0001",
            "phase": "execute",
            "failure_type": "exception",
            "summary": "ExecutionAction response was not valid JSON.",
            "task_status": "ready",
            "contract_check": {},
            "tool_failures": [],
            "verification_failures": [],
            "candidate": {},
            "recommendations": ["Repair the execution action."],
            "created_at": "2026-05-26T00:00:00+08:00",
        },
        "task_failure_evidence",
    )
    jsonl.append(
        run_dir / "task_execution_evidence.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "evidence-0002",
            "run_id": run_id,
            "task_id": "task-0001",
            "status": "done",
            "summary": "Repair verification passed.",
            "task": {"task_id": "task-0001", "title": "Minimal workflow task"},
            "action": {"kind": "repair"},
            "candidate": {"promoted_files": ["greet.py"]},
            "contract_check": {"ok": True},
            "tool_results": [],
            "verification_results": [{"ok": True}],
            "created_at": "2026-05-26T00:00:01+08:00",
        },
        "task_execution_evidence",
    )

    payload = StatusCommand(tmp_path).run().to_dict()

    assert payload["latest_failure"] == {}
    assert payload["blockers"] == []
    assert payload["risks"] == []
    assert payload["current_blocker"] is None


def test_review_falls_back_to_deterministic_report_when_model_call_fails(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)

    review = ReviewCommand(tmp_path, model_client=FailingReviewModel()).run()

    run_dir = tmp_path / ".asteria" / "runs" / run_id
    cost = JsonStore(SchemaValidator(Path("schemas"))).read(
        run_dir / "cost_report.json",
        "cost_report",
    )
    model_call_count = len(
        [
            line
            for line in (run_dir / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    )
    assert cost["model_calls"] == model_call_count
    assert review.status == "pass"
    assert review.recommended_next_command == "accept"
    eval_report = JsonStore(SchemaValidator(Path("schemas"))).read(
        review.eval_report_path,
        "eval_report",
    )
    fallback = eval_report["trajectory_eval"]["review_fallback"]
    assert fallback["used"] is True
    assert fallback["source"] == "deterministic_checks"
    assert fallback["attempted_tiers"] == ["strong", "medium", "cheap"]
    assert "stream deadline exceeded" in fallback["reason"]


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
    assert final_summary["main_path"]["active_stage"] == "verify"
    assert final_summary["main_path"]["next_command"] == "review"
    assert final_summary["recommended_next_command"] == final_summary["main_path"][
        "next_command"
    ]
    assert final_summary["runtime_progress"]["active_stage"] == "verify"
    assert final_summary["runtime_progress"]["next_command"] == "review"
    assert final_summary["todo_view"]["current"]["id"] == "task-0001"
    assert final_summary["main_path"]["todo_view"]["current"]["id"] == "task-0001"
    assert final_summary["output_locations"]["workspace_root"] == str(tmp_path.resolve())
    assert final_summary["output_locations"]["artifact_root"] == str(
        (tmp_path / ".asteria" / "artifacts").resolve()
    )
    final_report = result.final_report_path.read_text(encoding="utf-8")
    assert "## Workspace and Outputs" in final_report
    assert "## Main Path" in final_report
    assert "## Todo" in final_report
    assert "Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop" in final_report
    assert f"- Output root: {tmp_path.resolve()}" in final_report
    assert final_summary["model_selection"]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )
    assert final_summary["file_changes"][0]["path"] == "workflow_report.md"
    assert final_summary["validation_conclusion"]["status"] == "passed"
    assert final_summary["validation_conclusion"]["verification_command_count"] == 1
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
    assert route_timeline["timeline"][0]["reason"] == ("capability_feedback_escalated_from_medium")
    user_progress = JsonlStore(SchemaValidator(Path("schemas"))).read_all(
        result.final_report_path.with_name("user_progress.jsonl"),
        "user_progress_event",
    )
    event_types = [event["event_type"] for event in user_progress]
    transcript_kinds = {
        event.get("transcript_kind")
        for event in user_progress
        if event.get("display_level") == "main"
    }
    assert "workspace_selected" in event_types
    assert "evidence" in event_types
    assert "model_decision" in event_types
    assert "file_changed" in event_types
    assert "validation_result" in event_types
    assert "final_report" in event_types
    assert {"file_change", "verification", "final"}.issubset(transcript_kinds)
    assert not any(
        event.get("channel") == "model"
        and event.get("event_type") == "delta"
        and event.get("display_level") == "main"
        for event in user_progress
    )
    final_report_event = [
        event for event in user_progress if event["event_type"] == "final_report"
    ][-1]
    assert final_report_event["data"]["output_locations"]["workspace_root"] == str(
        tmp_path.resolve()
    )
    assert final_report_event["data"]["validation"]["status"] == "passed"
    dispatch_path = result.final_report_path.with_name("agent_loop_dispatch.json")
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    assert dispatch["task_dispatch"]
    assert any(
        event["title"] == "Agent loop dispatch loaded"
        and event["data"]["agent_loop_dispatch"]["task_dispatch"]
        for event in user_progress
    )
    summary = JsonStore(SchemaValidator(Path("schemas"))).read(
        result.run_loop_summary_path,
        "run_loop_summary",
    )
    active_goal = tmp_path / ".asteria" / "memory" / "active_goal.md"
    assert active_goal.exists()
    active_goal_text = active_goal.read_text(encoding="utf-8")
    assert "Create a minimal verified workflow." in active_goal_text
    assert "## Next Task" in active_goal_text
    assert "Run `asteria review`." in active_goal_text
    assert run_id not in active_goal_text
    active_goal_json = tmp_path / ".asteria" / "memory" / "active_goal.json"
    active_goal_state = JsonStore(SchemaValidator(Path("schemas"))).read(
        active_goal_json,
        "active_goal_memory",
    )
    assert active_goal_state["source_run_id"] == run_id
    assert active_goal_state["updated_by"] == "run"
    assert active_goal_state["update_reason"] == "ready_for_review"
    status_text = StatusCommand(tmp_path).run().to_text()
    assert "Asteria progress" in status_text
    assert "Current goal:" in status_text
    assert "Completed:" in status_text
    assert "Needs you:" in status_text
    assert "# Asteria Active Goal" not in status_text
    assert "Current session:" not in status_text
    assert "Model selection:" not in status_text
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
    assert any(
        step.name == "goal-policy" and step.status == "stop_for_accept" for step in result.steps
    )
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
    assert any(
        step.name == "goal-policy" and step.status == "stop_for_repair" for step in result.steps
    )
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
        step.name == "goal-policy" and step.status == "stop_for_replan" for step in result.steps
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
        step.name == "goal-policy" and step.status == "stop_for_decision" for step in result.steps
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
    assert status_payload["main_path"]["active_stage"] == "verify"
    assert status_payload["recommended_next_command"] == status_payload["main_path"][
        "next_command"
    ]
    assert status_payload["main_path"]["current_step"] == "Run `asteria review`."
    assert status_payload["todo_view"]["current"]["id"] == "task-0001"
    assert status_payload["main_path"]["todo_view"]["current"]["id"] == "task-0001"
    assert status_payload["runtime_progress"]["active_stage"] == "verify"
    assert status_payload["runtime_progress"]["next_command"] == "review"
    assert status_payload["runtime_progress"]["todo"]["current"]["id"] == "task-0001"
    assert status_payload["run_loop_summary"]["main_path"]["active_stage"] == "verify"
    assert status_payload["run_loop_summary"]["runtime_progress"]["active_stage"] == "verify"
    assert status_context["run_loop_summary_path"] == (
        f".asteria/runs/{run_id}/run_loop_summary.json"
    )
    assert status_context["run_loop_summary"]["workflow_state"] == "ready_for_review"
    assert status_context["run_loop_summary"]["recommended_next_command"] == "review"
    assert status_context["main_path"]["active_stage"] == "verify"
    assert status_context["recommended_next_command"] == status_context["main_path"][
        "next_command"
    ]
    assert status_payload["model_route_timeline"][0]["task_id"] == "task-0001"
    assert status_payload["model_route_timeline"][0]["purpose"] == "coding"
    assert status_payload["model_route_timeline"][0]["reason"] == (
        "capability_feedback_escalated_from_medium"
    )

    sessions = SessionsCommand(tmp_path, include_context=True).run()
    session_context = sessions.context[run_id]
    assert session_context["run_loop_summary_path"] == status_context["run_loop_summary_path"]
    assert session_context["run_loop_summary"] == status_context["run_loop_summary"]
    assert session_context["main_path"]["path"] == (
        "Plan/Todo -> Tool Use -> Verify -> Repair/Ask/Stop"
    )
    assert session_context["runtime_progress"]["active_stage"] == "verify"
    assert session_context["runtime_progress"]["next_command"] == "review"
    assert session_context["model_route_timeline"] == status_payload["model_route_timeline"]
    assert "run loop summary:" in sessions.to_text()
    assert "Model route timeline: 1 recent decision(s)" in StatusCommand(tmp_path).run().to_text(
        debug=True
    )
    assert (
        session_context["model_route_timeline_path"]
        == f".asteria/runs/{run_id}/model_route_timeline.json"
    )


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
    assert chat.session_context["main_path"]["active_stage"] == "verify"
    assert chat.session_context["runtime_progress"]["active_stage"] == "verify"
    assert chat.session_context["runtime_progress"]["next_command"] == "review"
    assert chat.session_context["workflow"]["recommended_next_command"] == chat.session_context[
        "main_path"
    ]["next_command"]
    assert chat.session_context["todo_view"]["current"]["id"] == "task-0001"
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
    text = chat.to_text()
    assert "Current session:" not in text
    assert run_id not in text
    assert "task_execution_evidence.jsonl" not in text
    assert "# Asteria Active Goal" in text
    assert "## Next Task" in text
    assert chat.to_dict()["execution_allowed"] is False
    assert chat.to_dict()["debug_details"] is False
    assert chat_model.context is not None
    assert chat_model.context["active_goal_memory"]
    assert chat_model.context["context_policy"]["active_goal_memory_included"] is True
    assert chat_model.request.metadata["agent_id"] == "ChatAgent"
    assert chat_model.request.metadata["agent_role_contract"]["role"] == "ChatAgent"
    assert chat_model.context["session_context"]["workflow"]["workflow_state"] == (
        "ready_for_review"
    )
    assert chat_model.context["workspace_envelope"]["workspace_root"] == str(tmp_path.resolve())
    assert chat_model.context["policy"]["permission_mode"] == "reviewed_auto"
    assert chat_model.context["session_context"]["workspace_envelope"]["workspace_root"] == str(
        tmp_path.resolve()
    )
    assert chat_model.context_envelope is not None
    assert chat_model.context_envelope["intent"] == "next_step_question"
    assert chat_model.context_envelope["payload"] == chat_model.context
    assert (
        chat_model.context_envelope["payload_hash"]
        == (chat_model.request.metadata["context_envelope_hash"])
    )
    assert (
        chat_model.request.metadata["context_envelope_id"]
        == (chat_model.context_envelope["envelope_id"])
    )
    envelope_path = tmp_path / chat_model.request.metadata["context_envelope_path"]
    assert envelope_path.exists()
    persisted_envelope = JsonStore(SchemaValidator(Path("schemas"))).read(
        envelope_path,
        "context_envelope",
    )
    assert persisted_envelope["payload_hash"] == chat_model.context_envelope["payload_hash"]


def test_chat_ordinary_question_does_not_mount_active_goal_memory(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)
    RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=0,
        enable_research=False,
    ).continue_run(run_id)
    chat_model = ContextAwareChatModel()

    chat = ChatCommand(
        tmp_path,
        "请解释一下 schema validation 的作用。",
        model_client=chat_model,
    ).run()

    assert chat_model.context is not None
    assert chat_model.context["chat_intent"] == "ordinary_chat"
    assert chat_model.context_envelope is not None
    assert chat_model.context_envelope["intent"] == "ordinary_chat"
    assert chat_model.context_envelope["payload"] == chat_model.context
    active_memory_section = next(
        item
        for item in chat_model.context_envelope["sections"]
        if item["name"] == "active_goal_memory"
    )
    assert active_memory_section["included"] is False
    assert chat_model.context["active_goal_memory"] == ""
    assert chat_model.context["context_policy"]["active_goal_memory_included"] is False
    assert ".asteria/memory/active_goal.md" not in chat.context_refs
    assert all("active_goal.md" not in ref for ref in chat.context_refs)
    assert not any("Current session recommends" in action for action in chat.next_actions)
    assert "# Asteria Active Goal" not in chat.to_text()
    assert "## Next Task" not in chat.to_text()


def test_chat_can_show_debug_session_details_when_requested(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    run_id = _create_minimal_completed_run(tmp_path)
    RunCommand(
        tmp_path,
        run_id=run_id,
        max_iterations=0,
        enable_research=False,
    ).continue_run(run_id)

    debug_model = ContextAwareChatModel()
    chat = ChatCommand(
        tmp_path,
        "请显示调试细节：run_id 和 model route 是什么？",
        model_client=debug_model,
    ).run()

    text = chat.to_text()
    assert chat.debug_details is True
    assert "Current session:" in text
    assert run_id in text
    assert "latest route:" in text
    assert debug_model.context_envelope is not None
    assert debug_model.context_envelope["intent"] == "debug_question"
    assert debug_model.context_envelope["redaction_policy"]["backend_fields_allowed"] is True
    assert "model_route_timeline" in debug_model.context_envelope["payload"]["session_context"]


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
    assert payload["workspace_envelope"]["workspace_root"] == str(tmp_path.resolve())
    assert payload["workspace_envelope"]["permission_mode"] == "reviewed_auto"
    status_text = StatusCommand(tmp_path).run().to_text(debug=True)
    assert "Workspace envelope:" in status_text
    assert f"- root: {tmp_path.resolve()}" in status_text
    debug_text = StatusCommand(tmp_path).run().to_text(debug=True)
    assert (
        "Model selection: strong for coding (capability_feedback_escalated_from_medium)"
    ) in debug_text
    assert (
        "pressure: medium -> strong (stronger route selected, direction=up) delta=1" in debug_text
    )
    assert "capability feedback: blocked (escalated_to_strong; blocking=1, review=0)" in debug_text
    assert (
        "next step: Use the selected stronger route for coding/medium; review results before scaling."
        in debug_text
    )
    assert "Pause scaling affected routes" not in debug_text


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


def test_review_report_includes_model_route_health_blocker(
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
    assert "## Model Route Health" in report
    assert "- Status: blocked" in report
    assert "AGENT_MODEL_STRONG_API_KEY or AGENT_MODEL_API_KEY or OPENAI_API_KEY" in report
    assert "model routes=blocked" in report
    eval_report = JsonStore(SchemaValidator(Path("schemas"))).read(
        review.eval_report_path,
        "eval_report",
    )
    assert eval_report["trajectory_eval"]["route_health"]["status"] == "blocked"


def _create_minimal_completed_run(root: Path) -> str:
    validator = SchemaValidator(Path("schemas"))
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    run_store = RunStore(root / ".asteria", validator)
    run = run_store.create_run("/run", goal_id="goal-workflow")
    run_id = run["run_id"]
    run_dir = run_store.run_dir(run_id)
    workspace_envelope = {
        "schema_version": "0.1.0",
        "workspace_id": "workspace-test",
        "workspace_root": str(root.resolve()),
        "input_roots": [str(root.resolve())],
        "output_root": str(root.resolve()),
        "artifact_root": str((root / ".asteria" / "artifacts").resolve()),
        "candidate_workspace_policy": "controlled_patch",
        "worktree_policy": "controlled_patch",
        "read_scope": [str(root.resolve())],
        "write_scope": [str(root.resolve())],
        "scope_summary": {
            "input_root_count": 1,
            "read_scope_count": 1,
            "write_scope_count": 1,
            "output_inside_workspace": True,
            "artifact_root_inside_workspace": True,
        },
        "artifact_policy": "workspace_artifacts",
        "git_policy": "detect",
        "permission_mode": "reviewed_auto",
        "created_at": now_iso(),
    }
    store.write(run_dir / "workspace_envelope.json", workspace_envelope, "workspace_envelope")
    run.update(
        {
            "status": "completed",
            "current_phase": "DONE",
            "summary": "Minimal run completed and ready for review.",
            "ended_at": now_iso(),
            "workspace": {
                "workspace_id": "workspace-test",
                "workspace_root": str(root.resolve()),
                "output_root": str(root.resolve()),
                "permission_mode": "reviewed_auto",
            },
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
            "candidate": {
                "artifact_refs": ["task_plan.json"],
                "promoted_files": ["workflow_report.md"],
            },
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
