import json
from pathlib import Path

from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.commands.handoff_command import HandoffCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.commands.sessions_command import SessionsCommand
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


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

    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "context_compacted" in events
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

    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "Created handoff package for ReviewerAgent" in events


def test_compact_and_handoff_capture_recovery_context(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    run_store = RunStore(tmp_path / ".agent", validator)
    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    store.write(
        tmp_path / ".agent" / "verification" / "latest.json",
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
        tmp_path / ".agent" / "acceptance" / "failures" / "markdown_kb.json",
        {
            "schema_version": "0.1.0",
            "evidence_id": "acceptance-failure-markdown_kb",
            "suite": "core",
            "scenario": "markdown_kb",
            "failure_summary": "Expected markdown_kb.py was not created",
            "acceptance_report": str(tmp_path / ".agent" / "acceptance" / "acceptance_report.json"),
            "summary_json": str(tmp_path / ".agent" / "acceptance" / "latest_summary.json"),
            "workspace": str(tmp_path / "acceptance" / "markdown_kb"),
            "transcript": str(tmp_path / "acceptance" / "markdown_kb" / "transcript.json"),
            "expected_file": str(tmp_path / "acceptance" / "markdown_kb" / "markdown_kb.py"),
            "stdout_tail": "",
            "stderr_tail": "missing markdown_kb.py",
            "reproduce": {
                "cli": "python -m agent_runtime /acceptance --suite core --scenario markdown_kb",
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
    store.write(tmp_path / ".agent" / "tasks" / "backlog.json", task_plan, "task_board")
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
    assert snapshot["acceptance_failures"][0]["scenario"] == "markdown_kb"
    assert snapshot["acceptance_failures"][0]["evidence_path"] == (
        ".agent/acceptance/failures/markdown_kb.json"
    )
    assert "acceptance failure evidence" in snapshot["open_risks"][1]
    assert snapshot["failures"][0]["summary"] == "1 failed"
    assert "Need user decision" in snapshot["report_summaries"]["review_report"]
    assert snapshot["next_actions"][0] == "Resolve decision decision-0002 with /decide"

    assert package["recommended_next_command"] == "decide --decision-id decision-0002"
    assert package["task_summary"]["remaining"] == 2
    assert package["pending_decisions"][0]["question"] == "Should we add a UI now?"
    assert package["verification_summary"]["platform"] == "windows"
    assert package["acceptance_failures"][0]["failure_summary"] == (
        "Expected markdown_kb.py was not created"
    )
    assert ".agent/acceptance/failures/markdown_kb.json" in package["recent_artifacts"]
    assert "password_tool.py" in package["recent_artifacts"]
    assert "Need user decision" in package["report_summaries"]["review_report"]


def test_sessions_command_can_show_latest_recovery_context(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "build a password test tool", model_client=FakePlanClient()).run()
    HandoffCommand(tmp_path, to_role="FutureRun").run()
    JsonStore(SchemaValidator(Path.cwd() / "schemas")).write(
        tmp_path / ".agent" / "verification" / "latest.json",
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

    assert context["snapshot_path"].startswith(".agent\\context\\snapshots\\") or context[
        "snapshot_path"
    ].startswith(".agent/context/snapshots/")
    assert context["handoff_path"].startswith(".agent\\context\\handoffs\\") or context[
        "handoff_path"
    ].startswith(".agent/context/handoffs/")
    assert context["recommended_next_command"] == "execute"
    assert context["verification"]["status"] == "passed"
    assert context["task_summary"]["remaining"] == 1
    assert "snapshot:" in text
    assert "handoff:" in text
    assert "next: execute" in text
    assert "verification: passed (windows, 2026-04-30T10:00:00+08:00)" in text
