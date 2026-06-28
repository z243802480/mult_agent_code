import json
from pathlib import Path

from asteria_runtime.commands.compact_command import CompactCommand
from asteria_runtime.commands.handoff_command import HandoffCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.commands.sessions_command import SessionsCommand
from asteria_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


class FakePlanClient:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content=json.dumps(
                {
                    "schema_version": "0.1.0",
                    "goal_id": "goal-0001",
                    "original_goal": "build a password test tool",
                    "normalized_goal": "Build a local-first password test tool",
                    "goal_type": "software_tool",
                    "assumptions": ["runs locally"],
                    "constraints": ["privacy_safe"],
                    "non_goals": ["does not prove absolute security"],
                    "expanded_requirements": [
                        {
                            "id": "req-0001",
                            "priority": "must",
                            "description": "Provide password strength scoring",
                            "source": "inferred",
                            "acceptance": ["shows a score after password input"],
                        }
                    ],
                    "target_outputs": ["local_cli"],
                    "definition_of_done": ["can run locally"],
                    "verification_strategy": ["unit_tests"],
                    "budget": {"max_iterations": 8, "max_model_calls": 60},
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 2),
            model_provider="fake",
            model_name="fake",
            raw_response={},
        )


def test_compact_command_creates_snapshot_from_latest_run(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()

    compact = CompactCommand(tmp_path, focus="test handoff").run()

    assert compact.run_id == plan.run_id
    assert compact.snapshot_path.exists()
    snapshot = json.loads(compact.snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["goal_summary"] == "Build a local-first password test tool"
    assert snapshot["definition_of_done"] == ["can run locally"]
    assert snapshot["active_tasks"] == ["task-0001"]

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "context_compacted" in events
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["title"] == "正在压缩上下文" for event in user_progress)
    assert any(
        event["channel"] == "evidence" and event["title"] == "上下文快照已写入"
        for event in user_progress
    )
    assert any(event["title"] == "上下文压缩完成" for event in user_progress)
    cost_report = json.loads((run_dir / "cost_report.json").read_text(encoding="utf-8"))
    assert cost_report["model_calls"] == 1
    assert cost_report["context_compactions"] == 1


def test_handoff_command_creates_package_from_snapshot(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()

    handoff = HandoffCommand(tmp_path, to_role="ReviewerAgent").run()

    assert handoff.run_id == plan.run_id
    assert handoff.handoff_path.exists()
    package = json.loads(handoff.handoff_path.read_text(encoding="utf-8"))
    assert package["to_role"] == "ReviewerAgent"
    assert package["current_task_ids"] == ["task-0001"]
    assert package["recommended_next_command"] == "execute"
    assert package["snapshot_id"].startswith("snapshot-")

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "Created handoff package for ReviewerAgent" in events
    user_progress = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["title"] == "正在创建交接包" for event in user_progress)
    assert any(
        event["channel"] == "evidence" and event["title"] == "交接包已写入"
        for event in user_progress
    )
    assert any(event["title"] == "交接准备完成" for event in user_progress)


def test_handoff_includes_north_star_ref_when_configured(tmp_path: Path) -> None:
    InitCommand(
        tmp_path,
        north_star_title="Long horizon goal",
        north_star_statement="Cross-run milestones",
    ).run()
    PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()

    handoff = HandoffCommand(tmp_path, to_role="ReviewerAgent").run()
    package = json.loads(handoff.handoff_path.read_text(encoding="utf-8"))

    assert package["north_star_ref"]["title"] == "Long horizon goal"
    assert package["north_star_ref"]["active_milestone"] == "Harness 会话 MVP 稳定"


def test_compact_and_handoff_capture_recovery_context(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    run_store = RunStore(tmp_path / ".asteria", validator)
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    store.write(
        tmp_path / ".asteria" / "verification" / "latest.json",
        {
            "schema_version": "0.1.0",
            "created_at": "2026-04-30T10:00:00+08:00",
            "status": "passed",
            "platform": "windows",
            "checks": [{"name": "pytest", "status": "passed", "summary": "full test suite passed"}],
            "artifacts": {"snapshot_count": 1, "handoff_count": 1},
        },
        "verification_summary",
    )
    store.write(
        tmp_path / ".asteria" / "acceptance" / "failures" / "markdown_kb.json",
        {
            "schema_version": "0.1.0",
            "evidence_id": "acceptance-failure-markdown_kb",
            "suite": "core",
            "scenario": "markdown_kb",
            "failure_summary": "Expected markdown_kb.py was not created",
            "acceptance_report": str(
                tmp_path / ".asteria" / "acceptance" / "acceptance_report.json"
            ),
            "summary_json": str(tmp_path / ".asteria" / "acceptance" / "latest_summary.json"),
            "workspace": str(tmp_path / "acceptance" / "markdown_kb"),
            "transcript": str(tmp_path / "acceptance" / "markdown_kb" / "transcript.json"),
            "expected_file": str(tmp_path / "acceptance" / "markdown_kb" / "markdown_kb.py"),
            "stdout_tail": "",
            "stderr_tail": "missing markdown_kb.py",
            "reproduce": {
                "cli": "python -m asteria_runtime /acceptance --suite core --scenario markdown_kb",
                "script": (
                    "python scripts/real_model_acceptance.py --suite core --scenario markdown_kb"
                ),
            },
            "promoted_task_id": "task-0004",
            "created_at": "2026-05-05T00:00:00+08:00",
        },
        "acceptance_failure_evidence",
    )

    task_plan_path = run_dir / "task_plan.json"
    task_plan = store.read(task_plan_path, "task_board")
    task_plan["tasks"][0]["status"] = "blocked"
    task_plan["tasks"].extend(
        [
            {
                **task_plan["tasks"][0],
                "task_id": "task-0002",
                "title": "Ready follow-up",
                "status": "ready",
                "depends_on": [],
            },
            {
                **task_plan["tasks"][0],
                "task_id": "task-0003",
                "title": "Completed setup",
                "status": "done",
                "depends_on": [],
            },
        ]
    )
    store.write(task_plan_path, task_plan, "task_board")
    store.write(tmp_path / ".asteria" / "tasks" / "backlog.json", task_plan, "task_board")
    run = run_store.load_run(plan.run_id)
    run["status"] = "paused"
    run["current_phase"] = "DECISION"
    run["summary"] = "Waiting for product direction."
    run_store.update_run(run)

    decision_base = {
        "schema_version": "0.1.0",
        "recommended_option_id": "approve",
        "options": [
            {
                "option_id": "approve",
                "label": "Approve",
                "tradeoff": "Continue with the current scope.",
                "action": "create_task",
            }
        ],
        "default_option_id": "approve",
        "impact": {"scope": "medium", "budget": "low", "risk": "low", "quality": "medium"},
        "created_at": now_iso(),
        "metadata": {},
    }
    jsonl.append(
        run_dir / "decisions.jsonl",
        {
            **decision_base,
            "decision_id": "decision-0001",
            "status": "resolved",
            "question": "Should we keep local-first scope?",
            "selected_option_id": "approve",
            "resolved_at": now_iso(),
        },
        "decision_point",
    )
    jsonl.append(
        run_dir / "decisions.jsonl",
        {
            **decision_base,
            "decision_id": "decision-0002",
            "status": "pending",
            "question": "Should we add a UI now?",
            "selected_option_id": None,
            "resolved_at": None,
        },
        "decision_point",
    )
    jsonl.append(
        run_dir / "tool_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "tool_call_id": "tool-0001",
            "run_id": plan.run_id,
            "task_id": "task-0001",
            "agent_id": "CoderAgent",
            "tool_name": "run_command",
            "input_summary": "pytest tests/test_password.py",
            "output_summary": "1 failed",
            "status": "failure",
            "started_at": now_iso(),
            "ended_at": now_iso(),
            "error": "AssertionError",
        },
        "tool_call",
    )
    jsonl.append(
        run_dir / "task_failures.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "task-failure-0001",
            "run_id": plan.run_id,
            "task_id": "task-0001",
            "phase": "execute",
            "failure_type": "contract_violation",
            "summary": "Task completion contract violated: verification did not pass",
            "task_status": "blocked",
            "contract_check": {
                "ok": False,
                "violations": ["verification did not pass"],
                "changed_files": ["password_tool.py"],
                "expected_changed_files": [],
                "verification_total": 1,
                "verification_passed": 0,
            },
            "tool_failures": [],
            "verification_failures": [{"summary": "1 failed", "error": "AssertionError"}],
            "candidate": {"changed_files": ["password_tool.py"]},
            "recommendations": [
                "Inspect verification failures and repair the smallest related artifact."
            ],
            "created_at": "2026-05-05T00:00:01+08:00",
        },
        "task_failure_evidence",
    )
    jsonl.append(
        run_dir / "runtime_requests.jsonl",
        {
            "schema_version": "0.1.0",
            "runtime_request_id": "runtime-request-0001",
            "run_id": plan.run_id,
            "task_id": "task-0001",
            "request_type": "scope_expansion",
            "risk": "medium",
            "reason": "Need to write WEB_UI.md after a decision.",
            "details": {"write_scope": ["WEB_UI.md"]},
            "status": "decision_created",
            "decision_id": "decision-0002",
            "created_at": "2026-05-05T00:00:02+08:00",
        },
        "runtime_request",
    )
    jsonl.append(
        run_dir / "workers.jsonl",
        {
            "schema_version": "0.1.0",
            "worker_invocation_id": "worker-0001",
            "run_id": plan.run_id,
            "task_id": "task-0001",
            "agent_id": "CoderAgent",
            "runtime_profile_id": "runtime-profile-0001",
            "status": "failed",
            "started_at": "2026-05-05T00:00:03+08:00",
            "ended_at": "2026-05-05T00:00:04+08:00",
            "summary": "Worker blocked on contract violation.",
        },
        "worker_invocation",
    )
    jsonl.append(
        run_dir / "worker_results.jsonl",
        {
            "schema_version": "0.1.0",
            "worker_result_id": "worker-result-0001",
            "worker_invocation_id": "worker-0001",
            "run_id": plan.run_id,
            "task_id": "task-0001",
            "status": "failed",
            "artifact_refs": ["artifact-0001"],
            "validation_refs": [],
            "failure_evidence_refs": ["task-failure-0001"],
            "cost": {"model_calls": 1, "tool_calls": 2},
            "summary": "Contract violation stopped promotion.",
        },
        "worker_result",
    )
    jsonl.append(
        run_dir / "artifacts.jsonl",
        {
            "schema_version": "0.1.0",
            "artifact_id": "artifact-0001",
            "run_id": plan.run_id,
            "task_id": "task-0001",
            "type": "source",
            "path": "password_tool.py",
            "created_by": "CoderAgent",
            "summary": "Password scoring implementation draft.",
            "created_at": now_iso(),
        },
        "artifact",
    )
    (run_dir / "review_report.md").write_text(
        "# Review\n\nStatus: partial\n\nNeed user decision.\n",
        encoding="utf-8",
    )
    (run_dir / "final_report.md").write_text(
        "# Final Report\n\nRun paused with pending decision.\n",
        encoding="utf-8",
    )

    compact = CompactCommand(tmp_path, focus="recovery handoff").run()
    snapshot = json.loads(compact.snapshot_path.read_text(encoding="utf-8"))
    handoff = HandoffCommand(tmp_path, to_role="FutureRun").run()
    package = json.loads(handoff.handoff_path.read_text(encoding="utf-8"))

    assert snapshot["run_status"]["status"] == "paused"
    assert snapshot["run_status"]["current_phase"] == "DECISION"
    assert snapshot["task_summary"]["by_status"]["blocked"] == 1
    assert snapshot["task_summary"]["by_status"]["ready"] == 1
    assert snapshot["task_summary"]["by_status"]["done"] == 1
    assert snapshot["accepted_decisions"] == ["Should we keep local-first scope? -> approve"]
    assert snapshot["pending_decisions"][0]["decision_id"] == "decision-0002"
    assert snapshot["recent_artifacts"][0]["path"] == "password_tool.py"
    assert snapshot["verification"][0]["status"] == "failed"
    assert snapshot["verification_summary"]["status"] == "passed"
    assert snapshot["verification_summary"]["checks"][0]["name"] == "pytest"
    assert snapshot["task_failures"][0]["evidence_id"] == "task-failure-0001"
    assert snapshot["task_failures"][0]["contract_check"]["violations"] == [
        "verification did not pass"
    ]
    assert snapshot["runtime_requests"][0]["runtime_request_id"] == "runtime-request-0001"
    assert snapshot["runtime_requests"][0]["details"]["write_scope"] == ["WEB_UI.md"]
    assert snapshot["worker_summary"]["by_status"]["failed"] == 1
    assert snapshot["worker_summary"]["recent"][0]["failure_evidence_refs"] == ["task-failure-0001"]
    assert snapshot["acceptance_failures"][0]["scenario"] == "markdown_kb"
    assert snapshot["acceptance_failures"][0]["evidence_path"] == (
        ".asteria/acceptance/failures/markdown_kb.json"
    )
    assert "task failure evidence" in snapshot["open_risks"][1]
    assert "acceptance failure evidence" in snapshot["open_risks"][2]
    assert "runtime request" in snapshot["open_risks"][3]
    assert snapshot["failures"][0]["summary"] == "1 failed"
    assert "Need user decision" in snapshot["report_summaries"]["review_report"]
    assert snapshot["next_actions"][0] == "Resolve decision decision-0002 with /decide"

    assert package["recommended_next_command"] == "decide --decision-id decision-0002"
    assert package["task_summary"]["remaining"] == 2
    assert package["pending_decisions"][0]["question"] == "Should we add a UI now?"
    assert package["verification_summary"]["platform"] == "windows"
    assert package["task_failures"][0]["failure_type"] == "contract_violation"
    assert package["runtime_requests"][0]["request_type"] == "scope_expansion"
    assert package["worker_summary"]["total"] == 1
    assert package["acceptance_failures"][0]["failure_summary"] == (
        "Expected markdown_kb.py was not created"
    )
    assert ".asteria/runs/" + plan.run_id + "/task_failures.jsonl" in package["recent_artifacts"]
    assert ".asteria/acceptance/failures/markdown_kb.json" in package["recent_artifacts"]
    assert "password_tool.py" in package["recent_artifacts"]
    assert "Need user decision" in package["report_summaries"]["review_report"]


def test_sessions_command_can_show_latest_recovery_context(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()
    HandoffCommand(tmp_path, to_role="FutureRun").run()
    JsonStore(SchemaValidator(Path.cwd() / "schemas")).write(
        tmp_path / ".asteria" / "verification" / "latest.json",
        {
            "schema_version": "0.1.0",
            "created_at": "2026-04-30T10:00:00+08:00",
            "status": "passed",
            "platform": "windows",
            "checks": [{"name": "pytest", "status": "passed", "summary": "full test suite passed"}],
            "artifacts": {"snapshot_count": 1, "handoff_count": 1},
        },
        "verification_summary",
    )

    result = SessionsCommand(tmp_path, session_id=plan.run_id, include_context=True).run()
    text = result.to_text()
    context = result.context[plan.run_id]

    assert context["snapshot_path"].startswith(".asteria/context/snapshots/")
    assert context["handoff_path"].startswith(".asteria/context/handoffs/")
    assert context["recommended_next_command"] == "execute"
    assert context["verification"]["status"] == "passed"
    assert context["task_summary"]["remaining"] == 1
    assert "snapshot:" in text
    assert "handoff:" in text
    assert "next: execute" in text
    assert "verification: passed (windows, 2026-04-30T10:00:00+08:00)" in text


def test_sessions_context_summarizes_blockers_cost_and_failure_evidence(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    task_plan["tasks"][0]["status"] = "blocked"
    task_plan["tasks"][0]["notes"] = "verification failed"
    store.write(run_dir / "task_plan.json", task_plan, "task_board")
    store.write(
        run_dir / "cost_report.json",
        {
            "schema_version": "0.1.0",
            "run_id": plan.run_id,
            "model_calls": 8,
            "tool_calls": 13,
            "estimated_input_tokens": 100,
            "estimated_output_tokens": 50,
            "strong_model_calls": 2,
            "cheap_model_calls": 1,
            "repair_attempts": 1,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "near_limit",
            "warnings": ["tool budget is warming up"],
        },
        "cost_report",
    )
    jsonl.append(
        run_dir / "task_failures.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "task-failure-0001",
            "run_id": plan.run_id,
            "task_id": "task-0001",
            "phase": "execute",
            "failure_type": "contract_violation",
            "summary": "verification did not pass",
            "task_status": "blocked",
            "contract_check": {},
            "tool_failures": [],
            "verification_failures": [],
            "candidate": {},
            "recommendations": ["Run debug with the latest failure evidence."],
            "created_at": "2026-05-06T12:00:00+08:00",
        },
        "task_failure_evidence",
    )

    result = SessionsCommand(tmp_path, session_id=plan.run_id, include_context=True).run()
    text = result.to_text()
    context = result.context[plan.run_id]

    assert context["goal_summary"] == "Build a local-first password test tool"
    assert context["recommended_next_command"] == "debug"
    assert context["cost_summary"]["status"] == "near_limit"
    assert context["latest_task_failure"]["failure_type"] == "contract_violation"
    assert "blocked task task-0001" in context["blockers"][0]
    assert "cost status is near_limit" in context["risks"]
    assert "goal: Build a local-first password test tool" in text
    assert "next: debug" in text
    assert "cost: near_limit (8 model, 13 tool)" in text
    assert "latest failure: task-0001 contract_violation - verification did not pass" in text
    assert "risks: cost status is near_limit" in text


def test_sessions_context_shows_acceptance_failure_recovery_pointer(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()
    JsonStore(SchemaValidator(Path.cwd() / "schemas")).write(
        tmp_path / ".asteria" / "acceptance" / "failures" / "markdown_kb.json",
        {
            "schema_version": "0.1.0",
            "evidence_id": "acceptance-failure-markdown_kb",
            "suite": "core",
            "scenario": "markdown_kb",
            "failure_summary": "Expected markdown_kb.py was not created",
            "acceptance_report": str(
                tmp_path / ".asteria" / "acceptance" / "acceptance_report.json"
            ),
            "summary_json": str(tmp_path / ".asteria" / "acceptance" / "latest_summary.json"),
            "workspace": str(tmp_path / "acceptance" / "markdown_kb"),
            "transcript": str(tmp_path / "acceptance" / "markdown_kb" / "transcript.json"),
            "expected_file": str(tmp_path / "acceptance" / "markdown_kb" / "markdown_kb.py"),
            "stdout_tail": "",
            "stderr_tail": "missing markdown_kb.py",
            "reproduce": {
                "cli": "python -m asteria_runtime /acceptance --suite core --scenario markdown_kb",
                "script": (
                    "python scripts/real_model_acceptance.py --suite core --scenario markdown_kb"
                ),
            },
            "promoted_task_id": "task-0002",
            "created_at": "2026-05-05T00:00:00+08:00",
        },
        "acceptance_failure_evidence",
    )
    HandoffCommand(tmp_path, to_role="FutureRun").run()

    result = SessionsCommand(tmp_path, session_id=plan.run_id, include_context=True).run()
    text = result.to_text()
    context = result.context[plan.run_id]

    assert context["recommended_next_command"] == "debug"
    assert context["acceptance_failure_count"] == 1
    assert context["latest_acceptance_failure"]["scenario"] == "markdown_kb"
    assert context["acceptance_failures"][0]["evidence_path"] == (
        ".asteria/acceptance/failures/markdown_kb.json"
    )
    assert "next: debug" in text
    assert "acceptance failures: 1 (latest: markdown_kb)" in text


def test_compact_snapshot_includes_p1_context_fields(tmp_path: Path) -> None:
    """Verify P1 ContextSnapshot fields: compaction_purpose, failed_tool_observations,
    capability_manifest_ref, and that context_loader exposes pending_decisions."""
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a notes tool", model_client=FakePlanClient()).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id

    jsonl.append(
        run_dir / "tool_observations.jsonl",
        {
            "schema_version": "0.1.0",
            "observation_id": "tool-observation-toolcall-0001",
            "run_id": plan.run_id,
            "task_id": "task-0001",
            "tool_call_id": "toolcall-0001",
            "tool_name": "run_command",
            "ok": False,
            "status": "failure",
            "summary": "pytest failed: 1 assertion error",
            "error_class": "AssertionError",
            "artifact_refs": [],
            "evidence_refs": [],
            "user_progress_event_id": None,
            "next_hint": "diagnose_then_repair_replan_ask_or_stop",
            "observation": {"tool_name": "run_command", "ok": False, "summary": "pytest failed: 1 assertion error"},
            "created_at": now_iso(),
        },
        "tool_observation",
    )
    store.write(
        run_dir / "prompt_envelope.json",
        {
            "schema_version": "0.1.0",
            "run_id": plan.run_id,
            "mode": "plan",
            "sections": [
                {
                    "name": "capability_manifest",
                    "source": "AgentHarness",
                    "priority": "system",
                    "cache_scope": "dynamic",
                    "token_estimate": 20,
                    "content_hash": "sha256:abc123",
                    "summary": "Direct tools and deferred tools listed.",
                    "evidence_refs": [],
                    "cache_break_reasons": [],
                }
            ],
            "section_order": ["capability_manifest"],
            "capability_manifest": {
                "modes": ["plan", "build", "review"],
                "direct_tools": [{"name": "read_file", "kind": "read", "permission": "allow", "permission_state": "allow", "description": "", "sandbox_profile": "runtime_policy", "read_scope": [], "write_scope": [], "cost_tier": "low", "observation_schema": "tool_observation"}],
                "deferred_tools": [{"name": "tool_search", "kind": "discover", "permission": "allow", "permission_state": "allow", "description": "", "sandbox_profile": "runtime_policy", "read_scope": [], "write_scope": [], "cost_tier": "low", "observation_schema": "tool_observation"}],
                "mcp_tools": [],
                "skills": [],
                "subagents": [],
                "verification": [],
                "tools": [],
                "boundaries": {},
            },
            "content_hash": "sha256:def456",
        },
        "prompt_envelope",
    )
    jsonl.append(
        run_dir / "decisions.jsonl",
        {
            "schema_version": "0.1.0",
            "decision_id": "decision-0001",
            "status": "pending",
            "question": "Should we add markdown export?",
            "recommended_option_id": "yes",
            "default_option_id": "no",
            "selected_option_id": None,
            "resolved_at": None,
            "options": [{"option_id": "yes", "label": "Yes", "tradeoff": "More features", "action": "create_task"}, {"option_id": "no", "label": "No", "tradeoff": "Stay minimal", "action": "record_constraint"}],
            "impact": {"scope": "low", "budget": "low", "risk": "low", "quality": "medium"},
            "created_at": now_iso(),
            "metadata": {},
        },
        "decision_point",
    )

    compact = CompactCommand(tmp_path, focus="p1 context test").run()
    snapshot = json.loads(compact.snapshot_path.read_text(encoding="utf-8"))

    assert snapshot["compaction_purpose"] == "continuation_state_not_success_evidence"
    assert len(snapshot["failed_tool_observations"]) == 1
    assert snapshot["failed_tool_observations"][0]["tool_name"] == "run_command"
    assert snapshot["failed_tool_observations"][0]["next_hint"] == "diagnose_then_repair_replan_ask_or_stop"
    assert snapshot["capability_manifest_ref"]["modes"] == ["plan", "build", "review"]
    assert "read_file" in snapshot["capability_manifest_ref"]["direct_tool_names"]
    assert "tool_search" in snapshot["capability_manifest_ref"]["deferred_tool_names"]
    assert snapshot["pending_decisions"][0]["decision_id"] == "decision-0001"

    from asteria_runtime.core.context_loader import ContextLoader
    context = ContextLoader(tmp_path, validator).load(plan.run_id)
    loaded_snapshot = context["latest_snapshot"]
    assert loaded_snapshot["compaction_purpose"] == "continuation_state_not_success_evidence"
    assert loaded_snapshot["pending_decisions"][0]["decision_id"] == "decision-0001"
    assert loaded_snapshot["failed_tool_observations"][0]["tool_name"] == "run_command"
    assert loaded_snapshot["capability_manifest_ref"]["modes"] == ["plan", "build", "review"]
