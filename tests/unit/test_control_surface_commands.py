import json
import os
from pathlib import Path

from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.gate_command import GateCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.validation_run_command import ValidationRunCommand
from asteria_runtime.commands.gate_status_command import (
    _real_provider_matrix_next_actions,
    _release_evidence_route_guidance,
    _validation_recommendation_for_changed_files,
)
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.package_check_command import PackageCheckCommand
from asteria_runtime.commands.review_command import ReviewCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.commands.version_command import VersionCommand
from asteria_runtime.commands.weekly_report_command import WeeklyReportCommand
from asteria_runtime.commands.roadmap_command import RoadmapCommand
from asteria_runtime.core.real_provider_matrix import (
    classify_matrix_case_retry,
    latest_real_provider_matrix,
    summarize_real_provider_matrix,
)
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


def _assert_control_surface_contract(
    payload: dict,
    *,
    command: str,
    audience: str,
    required_fields: set[str],
) -> None:
    contract = payload["control_surface"]

    assert contract["schema_version"] == "0.1.0"
    assert contract["command"] == command
    assert contract["audience"] == audience
    assert contract["stability"] == "additive"
    assert required_fields <= set(contract["stable_fields"])
    assert set(contract["stable_fields"]) <= set(payload)
    SchemaValidator(Path("schemas")).validate("control_surface", contract)


def test_version_command_reports_runtime_diagnostics() -> None:
    result = VersionCommand().run()

    assert "asteria-runtime" in result.to_text()
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["package"] == "asteria-runtime"
    assert payload["version"]
    assert payload["python_version"]
    assert payload["executable"]
    _assert_control_surface_contract(
        payload,
        command="version",
        audience="maintainer_preflight",
        required_fields={
            "schema_version",
            "package",
            "version",
            "python_version",
            "executable",
        },
    )


def test_weekly_report_command_reports_ops_control_surface(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = WeeklyReportCommand(tmp_path, week_id="2026-W23").run()
    payload = result.to_dict()

    assert payload["schema_version"] == "0.1.0"
    assert payload["week_id"] == "2026-W23"
    _assert_control_surface_contract(
        payload,
        command="weekly-report",
        audience="maintainer_ops_reporting",
        required_fields={
            "schema_version",
            "root",
            "week_id",
            "report_path",
            "status",
            "summary",
            "next_actions",
        },
    )


def test_roadmap_command_reports_ops_control_surface(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = RoadmapCommand(tmp_path, output=tmp_path / "roadmap.md").run()
    payload = result.to_dict()

    assert payload["schema_version"] == "0.1.0"
    _assert_control_surface_contract(
        payload,
        command="roadmap-update",
        audience="maintainer_ops_reporting",
        required_fields={
            "schema_version",
            "root",
            "roadmap_path",
            "markdown_path",
            "status",
            "next_actions",
        },
    )


def test_package_check_reports_packaging_preflight() -> None:
    result = PackageCheckCommand(Path.cwd()).run()

    assert result.ok
    text = result.to_text()
    assert "Package check" in text
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "pass"
    assert any(check["name"] == "version_sync" for check in payload["checks"])
    validation_modules = next(
        check for check in payload["checks"] if check["name"] == "validation_command_modules"
    )
    assert "validation-run" in validation_modules["summary"]
    assert any(check["name"] == "validation_route_template" for check in payload["checks"])
    assert any(check["name"] == "validation_runbook" for check in payload["checks"])
    hook_plugins = next(
        check for check in payload["checks"] if check["name"] == "hook_plugin_control_surface"
    )
    assert hook_plugins["ok"] is True
    assert hook_plugins["error_type"] == "plugin"
    assert "plugin" in payload["error_taxonomy"]["categories"]
    _assert_control_surface_contract(
        payload,
        command="package-check",
        audience="maintainer_preflight",
        required_fields={
            "schema_version",
            "root",
            "ok",
            "status",
            "checks",
            "failed_checks",
            "runbook",
            "error_taxonomy",
            "next_actions",
        },
    )
    assert payload["runbook"]["path"] == "docs/zh/验证试运行手册.md"
    assert "rollback" in payload["runbook"]["required_sections"]
    assert any(
        "model.routes.validation.example.ps1" in action for action in payload["next_actions"]
    )
    assert any("验证试运行手册.md" in action for action in payload["next_actions"])
    assert "Run `asteria version --json`" in payload["next_actions"][-1]


def test_status_reports_uninitialized_workspace(tmp_path: Path) -> None:
    result = StatusCommand(tmp_path).run()

    assert result.initialized is False
    assert "Conclusion: Workspace is not initialized." in result.to_text()
    assert "Next: asteria init" in result.to_text()
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "uninitialized"
    assert payload["workflow_state"] == "needs_init"
    assert payload["current_phase"] == "UNINITIALIZED"
    assert (
        payload["current_blocker"]
        == "Workspace is not initialized; run `asteria /init --root .` first."
    )
    assert payload["can_review"] is False
    assert payload["can_accept"] is False
    assert payload["next_actions"] == ["Run `asteria /init --root .`."]
    _assert_control_surface_contract(
        payload,
        command="status",
        audience="user_workflow",
        required_fields={
            "schema_version",
            "status",
            "workflow_state",
            "runtime_progress",
            "current_phase",
            "current_blocker",
            "can_review",
            "can_accept",
            "current_session_id",
            "recommended_next_command",
            "next_actions",
        },
    )


def test_status_reports_initialized_workspace_without_sessions(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = StatusCommand(tmp_path).run()

    assert result.initialized is True
    assert result.current_session_id is None
    assert "No sessions yet." in result.to_text()
    payload = result.to_dict()
    assert payload["initialized"] is True
    assert payload["plugin_control"]["hook_policy"]["plugins_enabled"] is False


def test_status_recommends_review_after_completed_done_tasks(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run.update({"status": "completed", "current_phase": "DONE", "summary": "done"})
    run_store.update_run(run)
    run_store.set_current_session(run["run_id"], "test")
    JsonStore(validator).write(
        run_store.run_dir(run["run_id"]) / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Done task",
                    "status": "done",
                }
            ],
        },
        "task_board",
    )

    result = StatusCommand(tmp_path).run()
    payload = result.to_dict()

    assert payload["recommended_next_command"] == "review"
    assert payload["workflow_state"] == "ready_for_review"
    assert payload["current_phase"] == "DONE"
    assert payload["current_blocker"] is None
    assert payload["can_review"] is True
    assert payload["can_accept"] is False
    assert payload["next_actions"] == ["Run `asteria review`."]
    assert "Workflow: ready_for_review" in result.to_text()
    assert "Current phase: DONE" in result.to_text()
    assert "Can review: yes" in result.to_text()


def test_status_recommends_accept_after_reviewed_pass(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run.update({"status": "completed", "current_phase": "REVIEWED", "summary": "reviewed"})
    run_store.update_run(run)
    run_store.set_current_session(run["run_id"], "test")
    JsonStore(validator).write(
        run_store.run_dir(run["run_id"]) / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "tasks": [{"task_id": "task-0001", "title": "Done task", "status": "done"}],
        },
        "task_board",
    )

    result = StatusCommand(tmp_path).run()
    payload = result.to_dict()

    assert payload["recommended_next_command"] == "accept"
    assert payload["workflow_state"] == "ready_for_accept"
    assert payload["current_phase"] == "REVIEWED"
    assert payload["current_blocker"] is None
    assert payload["can_review"] is False
    assert payload["can_accept"] is True
    assert payload["next_actions"] == ["Run `asteria accept`."]
    assert "Workflow: ready_for_accept" in result.to_text()
    assert "Can accept: yes" in result.to_text()


def test_status_has_no_next_command_after_acceptance(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run.update({"status": "completed", "current_phase": "ACCEPTED", "summary": "accepted"})
    run_store.update_run(run)
    run_store.set_current_session(run["run_id"], "test")
    JsonStore(validator).write(
        run_store.run_dir(run["run_id"]) / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "tasks": [{"task_id": "task-0001", "title": "Done task", "status": "done"}],
        },
        "task_board",
    )

    payload = StatusCommand(tmp_path).run().to_dict()

    assert payload["recommended_next_command"] is None
    assert payload["workflow_state"] == "accepted"
    assert payload["current_phase"] == "ACCEPTED"
    assert payload["can_review"] is False
    assert payload["can_accept"] is False
    assert payload["next_actions"] == []


def test_status_reports_blocked_model_route_health(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run.update({"status": "running", "current_phase": "EXECUTE", "summary": "executing"})
    run_store.update_run(run)
    run_store.set_current_session(run["run_id"], "test")
    run_dir = run_store.run_dir(run["run_id"])
    JsonlStore(validator).append(
        run_dir / "model_route_resolutions.jsonl",
        {
            "tier": "strong",
            "purpose": "coding",
            "provider": "unknown",
            "model_name": "unknown",
            "configured": False,
            "missing": ["AGENT_MODEL_STRONG_PROVIDER or AGENT_MODEL_PROVIDER"],
            "next_action": "Configure model route requirements: AGENT_MODEL_STRONG_PROVIDER.",
        },
    )

    result = StatusCommand(tmp_path).run()
    payload = result.to_dict()

    assert payload["status"] == "blocked"
    assert payload["workflow_state"] == "blocked"
    assert payload["route_health"]["status"] == "blocked"
    assert payload["route_health"]["recommended_next_command"] == "model-check"
    assert "Configure model route requirements" in payload["current_blocker"]
    assert payload["next_actions"] == ["Run `asteria debug`."]
    assert "Model routes: blocked" in result.to_text()
    assert "strong: unknown/unknown configured=False" in result.to_text()








def test_status_surfaces_latest_model_progress_deadline(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run.update({"status": "running", "current_phase": "EXECUTE", "summary": "executing"})
    run_store.update_run(run)
    run_store.set_current_session(run["run_id"], "test")
    run_dir = run_store.run_dir(run["run_id"])
    progress = UserProgressLogger(run_dir / "user_progress.jsonl", validator)
    progress.record(
        run_id=run["run_id"],
        channel="model",
        event_type="delta",
        phase="execute",
        status="running",
        title="Model response",
        summary="Model streamed a response chunk.",
        content_delta="partial",
        model_provider="minimax",
        model_name="MiniMax-M2.7",
        telemetry={
            "role": "CoderAgent",
            "role_purpose": "coding",
            "model_tier": "medium",
            "deadline_profile": "worker",
            "deadline_ms": 90000,
            "deadline_remaining_ms": 61000,
            "runtime_profile_id": "runtime-profile-task-0001",
            "model_profile_id": "model-profile-task-0001",
            "task_id": "task-0001",
        },
        data={
            "agent_role_contract": {
                "role": "CoderAgent",
                "purpose": "coding",
                "deadline_profile": "worker",
                "provider_call_seconds": 90,
                "stream_idle_timeout_seconds": 30,
                "max_model_calls": 1,
            }
        },
    )

    result = StatusCommand(tmp_path).run()
    payload = result.to_dict()
    progress_payload = payload["latest_model_progress"]

    assert progress_payload["role"] == "CoderAgent"
    assert progress_payload["model_tier"] == "medium"
    assert progress_payload["deadline_remaining_ms"] == 61000
    assert progress_payload["runtime_profile_id"] == "runtime-profile-task-0001"
    assert payload["current_context"]["latest_model_progress"] == progress_payload
    assert "Model progress: CoderAgent/medium minimax/MiniMax-M2.7 delta running" in (
        result.to_text()
    )
    assert "deadline_remaining_ms=61000" in result.to_text()
    assert "latest_model=delta CoderAgent minimax/MiniMax-M2.7" in result.to_text()


def test_validation_run_command_reports_execution_control_surface(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    payload = ValidationRunCommand(tmp_path, dry_run=True).run().to_dict()

    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "blocked"
    _assert_control_surface_contract(
        payload,
        command="validation-run",
        audience="maintainer_validation_execution",
        required_fields={
            "schema_version",
            "validation_run_id",
            "status",
            "summary_path",
            "run_id",
            "next_actions",
        },
    )


def test_validation_run_dry_run_reports_control_surface(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    result = ValidationRunCommand(tmp_path, dry_run=True).run()
    payload = result.to_dict()

    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] in {"dry_run", "blocked"}
    _assert_control_surface_contract(
        payload,
        command="validation-run",
        audience="maintainer_validation_execution",
        required_fields={
            "schema_version",
            "validation_run_id",
            "status",
            "summary_path",
            "run_id",
            "next_actions",
        },
    )


def test_gate_release_stage_passes_when_all_heavy_checks_are_skipped(tmp_path: Path) -> None:
    result = GateCommand(
        tmp_path,
        stage="release",
        skip_lint=True,
        skip_typecheck=True,
        skip_tests=True,
        skip_acceptance_gate=True,
    ).run()

    assert result.ok
    assert result.status == "ready"
    payload = result.to_dict()
    assert payload["mode"] == "release"
    assert payload["stages"]["release"] == []
    _assert_control_surface_contract(
        payload,
        command="gate",
        audience="maintainer_release_validation",
        required_fields={
            "schema_version",
            "root",
            "status",
            "ok",
            "mode",
            "stages",
            "latest_observation_plan",
            "next_actions",
        },
    )
    text = result.to_text()
    assert "Conclusion: Ready for the requested gate stage." in text
    assert "Mode: release" in text


def test_gate_release_stage_blocks_without_acceptance_report(tmp_path: Path) -> None:
    result = GateCommand(
        tmp_path,
        stage="release",
        skip_lint=True,
        skip_typecheck=True,
        skip_tests=True,
    ).run()

    assert not result.ok
    assert result.status == "blocked"
    gate_stage = next(
        stage for stage in result.stages["release"] if stage["name"] == "acceptance-gate"
    )
    assert gate_stage["ok"] is False
    assert "No acceptance report provided" in gate_stage["summary"]
    text = result.to_text()
    assert "Conclusion: Blocked; resolve the listed gate evidence before proceeding." in text
    assert "Blockers:" in text
    assert "Evidence chain:" in text
    assert any("acceptance-gate" in action for action in result.next_actions)


def test_gate_surfaces_latest_observation_plan(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    agent_dir = tmp_path / ".asteria"
    run = RunStore(agent_dir, validator).create_run("test")
    RunStore(agent_dir, validator).set_current_session(run["run_id"], "test")
    JsonlStore(validator).append(
        agent_dir / "runs" / run["run_id"] / "observation_plans.jsonl",
        {
            "schema_version": "0.1.0",
            "observation_plan_id": "observation-plan-0001",
            "run_id": run["run_id"],
            "task_id": "task-0001",
            "trigger": "unit",
            "failed_observation_count": 1,
            "actions": [{"action": "repair"}],
            "blockers": ["run_command: tests failed"],
            "evidence_refs": ["tool_calls.jsonl"],
            "recommended_route": "repair",
            "reason": "repair: run_command tests failed",
            "created_at": now_iso(),
        },
        "observation_plan",
    )

    result = GateCommand(
        tmp_path,
        stage="release",
        skip_lint=True,
        skip_typecheck=True,
        skip_tests=True,
    ).run()

    assert result.latest_observation_plan["recommended_route"] == "repair"
    text = result.to_text()
    assert "Latest agent next action: repair" in text
    assert "latest_next_action=repair" in text


def test_gate_status_surfaces_latest_observation_plan(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    agent_dir = tmp_path / ".asteria"
    run = RunStore(agent_dir, validator).create_run("test")
    RunStore(agent_dir, validator).set_current_session(run["run_id"], "test")
    JsonlStore(validator).append(
        agent_dir / "runs" / run["run_id"] / "observation_plans.jsonl",
        {
            "schema_version": "0.1.0",
            "observation_plan_id": "observation-plan-0001",
            "run_id": run["run_id"],
            "task_id": "task-0001",
            "trigger": "unit",
            "failed_observation_count": 1,
            "actions": [{"action": "ask"}],
            "blockers": ["permission required"],
            "evidence_refs": ["runtime_requests.jsonl"],
            "recommended_route": "ask",
            "reason": "ask: permission required",
            "created_at": now_iso(),
        },
        "observation_plan",
    )

    result = GateStatusCommand(tmp_path).run()

    assert result.latest_observation_plan["recommended_route"] == "ask"
    payload = result.to_dict()
    assert payload["latest_observation_plan"]["reason"] == "ask: permission required"
    assert "Latest agent next action: ask" in result.to_text()


def test_gate_status_ignores_observation_plan_superseded_by_release_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    agent_dir = tmp_path / ".asteria"
    run_store = RunStore(agent_dir, validator)
    run = run_store.create_run("test")
    run_store.set_current_session(run["run_id"], "test")
    JsonlStore(validator).append(
        run_store.run_dir(run["run_id"]) / "observation_plans.jsonl",
        {
            "schema_version": "0.1.0",
            "observation_plan_id": "observation-plan-old",
            "run_id": run["run_id"],
            "task_id": "task-0001",
            "trigger": "unit",
            "failed_observation_count": 1,
            "actions": [{"action": "repair"}],
            "blockers": ["old failure"],
            "evidence_refs": ["tool_calls.jsonl"],
            "recommended_route": "repair",
            "reason": "repair: old failure",
            "created_at": "2020-01-01T00:00:00+00:00",
        },
        "observation_plan",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["latest_observation_plan"] == {}
    assert "runtime_readiness_gate" not in payload


def test_gate_status_does_not_reaudit_disjoint_write_execution(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path("schemas"))
    agent_dir = tmp_path / ".asteria"
    run_store = RunStore(agent_dir, validator)
    run = run_store.create_run("test")
    run_store.set_current_session(run["run_id"], "test")
    run_dir = run_store.run_dir(run["run_id"])
    JsonlStore(validator).append(
        run_dir / "subagent_child_plans.jsonl",
        {
            "schema_version": "0.1.0",
            "subagent_child_plan_id": "subagent-child-plan-0001",
            "run_id": run["run_id"],
            "parent_task_id": "task-parent",
            "target_task_id": "task-0001",
            "parent_decision_id": "agent-loop-decision-0001",
            "parent_execution_id": "agent-loop-execution-0001",
            "worker_invocation_id": "worker-0001",
            "worker_result_id": "worker-result-0001",
            "runtime_profile_id": "runtime-profile-subagent",
            "planner_id": "RuntimeSubagentPlanner",
            "decomposition_strategy": "disjoint_write_child_tasks",
            "scheduling_strategy": "parallel_disjoint_writes_after_merge_gate",
            "max_child_workers": 2,
            "coordination_policy": {
                "write_allowed": True,
                "requires_merge_gate": True,
                "requires_disjoint_write_scope": True,
            },
            "status": "planned",
            "parallel_safety": "disjoint_writes",
            "child_tasks": [
                {
                    "child_task_id": "child-0001",
                    "task_id": "task-0001",
                    "title": "Write A",
                    "objective": "Write A.",
                    "acceptance": ["A written"],
                    "read_scope": ["."],
                    "write_scope": ["docs/a.md"],
                    "allowed_tools": ["write_file", "run_command"],
                    "depends_on": [],
                    "risk": "medium",
                    "parallel_safety": "disjoint_writes",
                    "worker_role": "implementation_child",
                    "write_allowed": True,
                    "expected_output": ["docs/a.md"],
                    "verification_expectation": {"requires_verification": True},
                },
                {
                    "child_task_id": "child-0002",
                    "task_id": "task-0001",
                    "title": "Write B",
                    "objective": "Write B.",
                    "acceptance": ["B written"],
                    "read_scope": ["."],
                    "write_scope": ["docs/b.md"],
                    "allowed_tools": ["write_file", "run_command"],
                    "depends_on": [],
                    "risk": "medium",
                    "parallel_safety": "disjoint_writes",
                    "worker_role": "implementation_child",
                    "write_allowed": True,
                    "expected_output": ["docs/b.md"],
                    "verification_expectation": {"requires_verification": True},
                },
            ],
            "evidence_refs": ["agent_loop_execution_results.jsonl"],
            "created_at": now_iso(),
        },
        "subagent_child_plan",
    )
    for index, file_name in ((1, "docs/a.md"), (2, "docs/b.md")):
        JsonlStore(validator).append(
            run_dir / "candidate_promotions.jsonl",
            {
                "schema_version": "0.1.0",
                "promotion_id": f"promotion-000{index}",
                "run_id": run["run_id"],
                "task_id": f"child-000{index}",
                "candidate_id": f"candidate-000{index}",
                "workspace": str(run_dir / "cw" / f"000{index}"),
                "strategy": "temp_workspace",
                "workspace_policy": "isolated_copy",
                "backend_reason": "test",
                "branch_name": None,
                "promotable_files": [file_name],
                "promoted_files": [file_name],
                "status": "promoted",
                "approval_mode": "manual",
                "merge_gate": {
                    "ok": True,
                    "promotable_files": [file_name],
                    "violations": [],
                },
                "failure": None,
                "decision": None,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            },
            "candidate_promotion",
        )

    result = GateStatusCommand(tmp_path).run()

    assert "Disjoint write gate:" not in result.to_text()


def test_status_reports_candidate_promotion_summary(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run_store.set_current_session(run["run_id"], "test")
    run_dir = run_store.run_dir(run["run_id"])
    JsonlStore(validator).append(
        run_dir / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": run["run_id"],
            "task_id": "task-0001",
            "candidate_id": "candidate-0001",
            "workspace": str(run_dir / "cw" / "0001"),
            "strategy": "temp_workspace",
            "workspace_policy": "isolated_copy",
            "backend_reason": "test",
            "branch_name": None,
            "promotable_files": ["tool.py"],
            "promoted_files": [],
            "status": "pending_manual_approval",
            "approval_mode": "manual",
            "merge_gate": {"ok": True},
            "failure": None,
            "decision": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        },
        "candidate_promotion",
    )

    result = StatusCommand(tmp_path).run()

    payload = result.to_dict()
    assert payload["candidate_promotions"]["total"] == 1
    assert payload["candidate_promotions"]["status_counts"] == {"pending_manual_approval": 1}
    assert "Candidate promotions: 1 total" in result.to_text()


def test_status_reports_worker_tree_summary(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run_store.set_current_session(run["run_id"], "test")
    run_dir = run_store.run_dir(run["run_id"])
    jsonl = JsonlStore(validator)
    for index, status in enumerate(["succeeded", "failed"], start=1):
        worker_id = f"worker-{index:04d}"
        jsonl.append(
            run_dir / "workers.jsonl",
            {
                "schema_version": "0.1.0",
                "worker_invocation_id": worker_id,
                "run_id": run["run_id"],
                "task_id": f"task-{index:04d}",
                "agent_id": "CoderAgent",
                "runtime_profile_id": f"runtime-profile-worker-{index:04d}",
                "status": status,
                "started_at": now_iso(),
                "ended_at": now_iso(),
                "summary": "test worker",
                **(
                    {
                        "parent_worker_invocation_id": "worker-0001",
                        "parent_task_id": "task-0001",
                        "worker_kind": "subagent_readonly_child",
                        "parallel_safety": "readonly",
                        "child_plan_refs": ["subagent-child-plan-0001"],
                    }
                    if index == 2
                    else {"worker_kind": "subagent", "parallel_safety": "serial"}
                ),
            },
            "worker_invocation",
        )
        jsonl.append(
            run_dir / "worker_results.jsonl",
            {
                "schema_version": "0.1.0",
                "worker_result_id": f"worker-result-{index:04d}",
                "worker_invocation_id": worker_id,
                "run_id": run["run_id"],
                "task_id": f"task-{index:04d}",
                "status": status,
                "artifact_refs": [],
                "validation_refs": [],
                "failure_evidence_refs": [] if status == "succeeded" else ["task-failure-0001"],
                "cost": {"model_calls": 1, "tool_calls": 2},
                "summary": "worker result",
            },
            "worker_result",
        )
    jsonl.append(
        run_dir / "events.jsonl",
        {
            "schema_version": "0.1.0",
            "event_id": "event-0001",
            "run_id": run["run_id"],
            "timestamp": now_iso(),
            "type": "task_graph_selection",
            "actor": "ExecutionCoordinator",
            "summary": "Selected workers",
            "data": {
                "reason": "parallel_safe_batch_selection",
                "task_ids": ["task-0001", "task-0002"],
            },
        },
        "event",
    )

    result = StatusCommand(tmp_path).run()

    worker_tree = result.to_dict()["current_context"]["worker_tree"]
    assert worker_tree["total_workers"] == 2
    assert worker_tree["successful_workers"] == 1
    assert worker_tree["failed_workers"] == 1
    assert worker_tree["parallel_batches"] == 1
    assert worker_tree["total_model_calls"] == 2
    assert worker_tree["agent_run_graph"]["status"] == "blocked"
    assert worker_tree["agent_run_graph"]["max_concurrency_observed"] == 2
    assert worker_tree["collaboration_summary"]["failure_evidence_refs"] == ["task-failure-0001"]
    assert worker_tree["orphan_workers"] == []
    assert len(worker_tree["roots"]) == 1
    assert worker_tree["roots"][0]["worker_invocation_id"] == "worker-0001"
    assert worker_tree["roots"][0]["children"][0]["worker_invocation_id"] == "worker-0002"
    assert worker_tree["roots"][0]["children"][0]["parent_worker_invocation_id"] == "worker-0001"
    assert worker_tree["roots"][0]["children"][0]["child_plan_refs"] == ["subagent-child-plan-0001"]
    assert "Workers: 1 succeeded / 2 total" in result.to_text()


def test_doctor_checks_initialized_workspace_and_routes(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "minimax-key")

    result = DoctorCommand(tmp_path).run()

    assert result.ok
    text = result.to_text()
    assert "model_strong: ok" in text
    assert "model_medium: ok" in text
    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["schema_version"] == "0.1.0"
    assert any(check["name"] == "model_strong" for check in payload["checks"])
    assert payload["routes"]["strong"]["configured"] is True
    assert payload["route_requirements"]["medium"] == [
        "AGENT_MODEL_MEDIUM_PROVIDER or AGENT_MODEL_PROVIDER",
        "AGENT_MODEL_MEDIUM_NAME or provider default",
        "AGENT_MODEL_MEDIUM_API_KEY or provider/global API key",
    ]
    assert "preferred_backend" in payload["sandbox"]
    assert payload["validation_task_limits"]["max_iterations"] == 3
    assert payload["plugin_control"]["hook_policy"]["plugins_enabled"] is False
    assert "plugin" in payload["error_taxonomy"]["categories"]
    assert (
        next(check for check in payload["checks"] if check["name"] == "plugins")["error_type"]
        == "plugin"
    )
    _assert_control_surface_contract(
        payload,
        command="doctor",
        audience="maintainer_preflight",
        required_fields={
            "schema_version",
            "ok",
            "status",
            "checks",
            "routes",
            "route_requirements",
            "plugin_control",
            "next_actions",
        },
    )


def test_doctor_flags_canned_output_for_fake_default_route(tmp_path: Path, monkeypatch) -> None:
    # ADR-0016 §3 honesty: with no model env configured the `cheap` tier resolves to the fake
    # default, which fabricates output. Doctor must not present it as a plain green route — it warns
    # and says CANNED explicitly, but stays non-blocking (offline is intentional).
    InitCommand(tmp_path).run()
    for key in list(os.environ):
        if key.startswith("AGENT_MODEL") or key.endswith("_API_KEY"):
            monkeypatch.delenv(key, raising=False)

    result = DoctorCommand(tmp_path).run()
    payload = result.to_dict()

    # `cheap` is not a doctor check (only strong/medium are), but it IS in the routes table — the
    # honesty flag + base_url must mark it as canned there.
    cheap_route = payload["routes"]["cheap"]
    assert cheap_route["returns_canned_output"] is True
    assert "canned placeholder" in str(cheap_route["base_url"])

    # A fully-offline `strong` route DOES render as a check: it must warn CANNED, stay non-blocking.
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "fake")
    offline_payload = DoctorCommand(tmp_path).run().to_dict()
    strong_check = next(c for c in offline_payload["checks"] if c["name"] == "model_strong")
    assert strong_check["ok"] is True
    assert strong_check["severity"] == "warning"
    assert "CANNED" in strong_check["summary"]
    assert offline_payload["routes"]["strong"]["returns_canned_output"] is True


def test_doctor_reports_blocked_plugin_manifest(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    _write_plugin_manifest(tmp_path, hook_subscriptions=["unknown_hook"])
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "minimax-key")

    payload = DoctorCommand(tmp_path).run().to_dict()

    plugin_check = next(check for check in payload["checks"] if check["name"] == "plugins")
    assert plugin_check["ok"] is False
    assert plugin_check["severity"] == "warning"
    assert plugin_check["error_type"] == "plugin"
    assert payload["plugin_control"]["status_counts"]["blocked"] == 1


def test_status_reports_plugin_control_risk(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    _write_plugin_manifest(tmp_path, hook_subscriptions=["unknown_hook"])

    result = StatusCommand(tmp_path).run()
    payload = result.to_dict()

    assert payload["status"] == "blocked"
    assert payload["plugin_control"]["ok"] is False
    assert "Blocked plugin manifests" in " ".join(payload["plugin_control"]["warnings"])


def test_doctor_reports_exact_missing_medium_route_variables(tmp_path: Path, monkeypatch) -> None:
    InitCommand(tmp_path).run()
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "glm-4.7")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "openai-compatible")
    monkeypatch.setenv("AGENT_MODEL_NAME", "worker-model")
    monkeypatch.delenv("AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_PROVIDER", raising=False)

    result = DoctorCommand(tmp_path).run()

    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["routes"]["medium"]["configured"] is False
    assert payload["failed_checks"] == ["git", "model_medium", "real_model_gate"]
    assert any(
        "AGENT_MODEL_API_KEY or OPENAI_API_KEY" in action for action in payload["next_actions"]
    )
    assert any("验证试运行手册.md" in action for action in payload["next_actions"])


def test_doctor_accepts_global_minimax_as_effective_medium_route(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_API_KEY", raising=False)

    payload = DoctorCommand(tmp_path).run().to_dict()

    assert payload["routes"]["medium"]["configured"] is True
    assert payload["routes"]["medium"]["provider"] == "minimax"
    assert payload["routes"]["medium"]["source"] == "global"
    assert "model_medium" not in payload["failed_checks"]


def test_doctor_reports_tier_fallback_as_effective_medium_route(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.delenv("AGENT_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_PROVIDER", raising=False)

    payload = DoctorCommand(tmp_path).run().to_dict()

    assert payload["routes"]["medium"]["configured"] is True
    assert payload["routes"]["medium"]["provider"] == "glm"
    assert payload["routes"]["medium"]["source"] == "fallback_tier:strong"


def test_doctor_fails_for_missing_workspace_guidance(tmp_path: Path) -> None:
    result = DoctorCommand(tmp_path).run()

    assert not result.ok
    assert "workspace is not initialized" in result.to_text()
    assert result.to_dict()["ok"] is False


def test_gate_status_moves_from_gate_to_validation_to_core(tmp_path: Path, monkeypatch) -> None:
    _configure_release_routes(monkeypatch)
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "missing_real_model_gate"
    _assert_control_surface_contract(
        result.to_dict(),
        command="gate-status",
        audience="maintainer_release_validation",
        required_fields={
            "schema_version",
            "stage",
            "release_state",
            "release_ready",
            "gates",
            "route_environment",
            "validation_recommendation",
            "next_actions",
        },
    )

    gate_dir = tmp_path / ".asteria" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True, "recommended_actions": ["run validation"]}),
        encoding="utf-8",
    )
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "ready_for_validation_suite"
    assert result.to_dict()["release_state"] == "conditional"

    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    (verification_dir / "real_model_acceptance_validation.json").write_text(
        json.dumps(
            {
                "ok": True,
                "validation_ready": True,
                "aggregate": {
                    "total": 4,
                    "passed": 4,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "ready_for_core_acceptance"
    assert "validation_ready: True" in result.to_text()

    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "aggregate": {"total": 6, "passed": 6}}),
        encoding="utf-8",
    )
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "ready_for_small_real_task_validation"
    payload = result.to_dict()
    assert payload["stage"] == "ready_for_small_real_task_validation"
    assert payload["release_state"] == "release_ready"
    assert payload["release_ready"] is True
    assert payload["blocking_reason"] is None
    assert payload["gates"]["validation_suite"]["validation_ready"] is True
    assert payload["validation_report"]["validation_ready"] is True
    assert payload["route_environment"]["ready"] is True
    assert payload["promotion_release_risks"]["pending"] == 0
    assert payload["validation_task_limits"]["max_tasks_per_iteration"] == 1
    assert "--no-research" in payload["next_actions"][0]
    assert payload["route_guidance"]["status"] == "healthy"
    assert payload["validation_recommendation"]["level"] in {
        "none",
        "targeted",
        "core_subset",
        "full_validation_core",
    }


def test_gate_status_blocks_release_on_failing_real_correctness(
    tmp_path: Path, monkeypatch
) -> None:
    # ADR-0018: even when every acceptance scenario passes STRUCTURALLY (report ok==True), the
    # release gate must NOT be release-ready if the acceptance runs' REAL verification
    # (run_tests/run_command exit codes) failed. Closes the "structural pass hides real code
    # failure" fabrication gap (研发总计划 §16.1 line 467: 真代码正确性 gate 取代 UX 结构指标).
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)

    # Baseline: no real-correctness evidence => None => not blocked (never fabricate a fail).
    assert GateStatusCommand(tmp_path).run().stage == "ready_for_small_real_task_validation"

    # Attach a core acceptance scenario whose recorded run FAILED its executable verification.
    workspace = tmp_path / "accept_ws"
    run_dir = workspace / ".asteria" / "runs" / "run-accept-0001"
    run_dir.mkdir(parents=True)
    (run_dir / "tool_calls.jsonl").write_text(
        json.dumps({"tool_name": "run_command", "status": "error"}) + "\n",
        encoding="utf-8",
    )
    verification_dir = tmp_path / ".asteria" / "verification"
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps(
            {
                "ok": True,  # structurally passes ...
                "aggregate": {"total": 10, "passed": 10},
                "scenarios": [
                    {
                        "ok": True,
                        "workspace": str(workspace),
                        "summary": {"run_id": "run-accept-0001"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "acceptance_correctness_failed"  # ... real correctness blocks it
    assert payload["release_ready"] is False
    assert payload["release_state"] == "blocked"
    assert payload["acceptance_correctness"]["status"] == "fail"
    assert "run_tests/run_command" in payload["blocking_reason"]


def test_gate_status_route_table_surfaces_offline_tiers(tmp_path: Path, monkeypatch) -> None:
    # strong/medium point at a real provider; cheap stays on the fake/offline provider. route_table
    # must expose all three tiers and honestly flag cheap as silently returning canned output —
    # without letting cheap block gate readiness (route_environment stays strong+medium only).
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "k")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "k")
    monkeypatch.setenv("AGENT_MODEL_CHEAP_PROVIDER", "fake")

    payload = GateStatusCommand(tmp_path).run().to_dict()
    table = payload["route_table"]

    assert set(table["tiers"]) == {"strong", "medium", "cheap"}
    assert table["tiers"]["cheap"]["provider"] == "fake"
    assert table["offline_tiers"] == ["cheap"]
    assert table["silently_offline"] is True
    # cheap being offline must NOT leak into the readiness-driving route_environment.
    assert "cheap" not in payload["route_environment"]
    assert "Offline tiers" in GateStatusCommand(tmp_path).run().to_text()


def test_gate_status_reports_v02_rolling_validation_summary(tmp_path: Path, monkeypatch) -> None:
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    bundle_dir = tmp_path / ".asteria" / "evidence_bundles"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "evidence-test.manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "v0_2_rolling_validation": {
                    "status": "needs_evidence",
                    "sample_count": 5,
                    "required_sample_range": {"min": 3, "max": 5},
                    "coverage": {
                        "route": False,
                        "context": True,
                        "capability": True,
                        "loop": False,
                        "worker": True,
                    },
                    "next_actions": ["Collect missing evidence categories: route, loop."],
                },
            }
        ),
        encoding="utf-8",
    )

    result = GateStatusCommand(tmp_path).run()
    payload = result.to_dict()

    assert payload["v0_2_rolling_validation"]["status"] == "needs_evidence"
    assert payload["v0_2_rolling_validation"]["sample_count"] == 5
    assert payload["v0_2_rolling_validation"]["missing_evidence_categories"] == [
        "route",
        "loop",
    ]
    assert "Collect missing evidence categories: route, loop." in payload["next_actions"]
    assert "v0.2 rolling validation: needs_evidence" in result.to_text()


def test_gate_status_uses_latest_validation_acceptance_summary(tmp_path: Path, monkeypatch) -> None:
    _configure_release_routes(monkeypatch)
    gate_dir = tmp_path / ".asteria" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    stale = verification_dir / "real_model_acceptance_validation.json"
    fresh = verification_dir / "real_model_acceptance_validation_after_fix.json"
    stale.write_text(
        json.dumps(
            {
                "ok": False,
                "suite": "validation",
                "validation_ready": False,
                "aggregate": {"total": 8, "passed": 4, "failed": 4},
            }
        ),
        encoding="utf-8",
    )
    fresh.write_text(
        json.dumps(
            {
                "ok": True,
                "suite": "validation",
                "validation_ready": True,
                "aggregate": {
                    "total": 8,
                    "passed": 8,
                    "failed": 0,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "suite": "core", "aggregate": {"total": 10, "passed": 10}}),
        encoding="utf-8",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "ready_for_small_real_task_validation"
    assert payload["gates"]["validation_suite"]["passed"] == 8
    assert payload["evidence_sources"]["validation_suite"].endswith(
        "real_model_acceptance_validation_after_fix.json"
    )


def test_gate_status_closes_failed_validation_scenario_with_newer_targeted_rerun(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_release_routes(monkeypatch)
    gate_dir = tmp_path / ".asteria" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    full = verification_dir / "real_model_acceptance_validation.json"
    targeted = verification_dir / "real_model_acceptance_validation_multi_file_scope.json"
    full.write_text(
        json.dumps(
            {
                "ok": False,
                "complete": False,
                "suite": "validation",
                "validation_ready": False,
                "scenario_metadata": [
                    {"scenario": "validation_file_artifact"},
                    {"scenario": "validation_multi_file_scope"},
                    {"scenario": "validation_debug_repair"},
                    {"scenario": "validation_doc_update"},
                    {"scenario": "validation_small_cli"},
                    {"scenario": "validation_subagent_delegation"},
                    {"scenario": "validation_refactor"},
                    {"scenario": "runtime_request_resume"},
                ],
                "scenarios": [
                    {"scenario": "validation_file_artifact", "ok": True},
                    {"scenario": "validation_multi_file_scope", "ok": False},
                    {"scenario": "validation_debug_repair", "ok": True},
                    {"scenario": "validation_doc_update", "ok": True},
                    {"scenario": "validation_small_cli", "ok": True},
                    {"scenario": "validation_subagent_delegation", "ok": True},
                    {"scenario": "validation_refactor", "ok": True},
                    {"scenario": "runtime_request_resume", "ok": True},
                ],
                "aggregate": {
                    "total": 8,
                    "passed": 7,
                    "failed": 1,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    targeted.write_text(
        json.dumps(
            {
                "ok": True,
                "suite": "smoke",
                "requested_scenarios": ["validation_multi_file_scope"],
                "scenarios": [{"scenario": "validation_multi_file_scope", "ok": True}],
                "aggregate": {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    os.utime(targeted, (full.stat().st_mtime + 10, full.stat().st_mtime + 10))
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "suite": "core", "aggregate": {"total": 10, "passed": 10}}),
        encoding="utf-8",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "ready_for_small_real_task_validation"
    assert payload["gates"]["validation_suite"]["passed"] == 8
    assert payload["validation_report"]["repair_closure"]["closed_failures"] == [
        "validation_multi_file_scope"
    ]


def test_gate_status_prefers_passing_canonical_validation_summary(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_release_routes(monkeypatch)
    gate_dir = tmp_path / ".asteria" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    (verification_dir / "real_model_acceptance_validation.json").write_text(
        json.dumps(
            {
                "ok": True,
                "suite": "validation",
                "validation_ready": True,
                "aggregate": {
                    "total": 8,
                    "passed": 8,
                    "failed": 0,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_validation_named_history.json").write_text(
        json.dumps(
            {
                "ok": True,
                "suite": "validation",
                "validation_ready": True,
                "aggregate": {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "suite": "core", "aggregate": {"total": 10, "passed": 10}}),
        encoding="utf-8",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["gates"]["validation_suite"]["total"] == 8
    assert payload["evidence_sources"]["validation_suite"].endswith(
        "real_model_acceptance_validation.json"
    )


def test_gate_status_does_not_treat_validation_subset_as_full_suite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _configure_release_routes(monkeypatch)
    gate_dir = tmp_path / ".asteria" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    (verification_dir / "real_model_acceptance_validation_subset.json").write_text(
        json.dumps(
            {
                "ok": True,
                "suite": "validation",
                "requested_scenarios": ["validation_refactor", "runtime_request_resume"],
                "scenario_metadata": [
                    {"scenario": "validation_refactor"},
                    {"scenario": "runtime_request_resume"},
                ],
                "validation_ready": True,
                "aggregate": {
                    "total": 2,
                    "passed": 2,
                    "failed": 0,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "suite": "core", "aggregate": {"total": 10, "passed": 10}}),
        encoding="utf-8",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "ready_for_validation_suite"
    assert payload["gates"]["validation_suite"]["present"] is False
    assert payload["readiness_explanation"]["status"] == "missing_release_suite_evidence"




def test_gate_status_blocks_release_when_current_routes_are_missing(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_release_routes(monkeypatch)
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_CN_API_KEY", raising=False)
    gate_dir = tmp_path / ".asteria" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    (verification_dir / "real_model_acceptance_validation.json").write_text(
        json.dumps(
            {
                "ok": True,
                "validation_ready": True,
                "aggregate": {
                    "total": 4,
                    "passed": 4,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "aggregate": {"total": 10, "passed": 10}}),
        encoding="utf-8",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "current_environment_incomplete"
    assert payload["release_state"] == "blocked"
    assert payload["release_ready"] is False
    assert (
        "AGENT_MODEL_MEDIUM_PROVIDER or AGENT_MODEL_PROVIDER"
        in payload["route_environment"]["missing_required"]
    )


def test_gate_status_accepts_global_minimax_fallback_for_medium(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_release_routes(monkeypatch)
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_NAME", raising=False)
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    gate_dir = tmp_path / ".asteria" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    (verification_dir / "real_model_acceptance_validation.json").write_text(
        json.dumps(
            {
                "ok": True,
                "validation_ready": True,
                "aggregate": {
                    "total": 4,
                    "passed": 4,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "aggregate": {"total": 10, "passed": 10}}),
        encoding="utf-8",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "ready_for_small_real_task_validation"
    assert payload["release_state"] == "release_ready"
    assert payload["route_environment"]["medium"]["source"] == "global"
    assert payload["route_environment"]["medium"]["provider"] == "minimax"


def test_gate_status_blocks_validation_when_capability_route_guidance_is_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    validator = SchemaValidator(Path.cwd() / "schemas")
    JsonStore(validator).write(
        tmp_path / ".asteria" / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "runtime",
                    "model": "medium-route",
                    "purpose": "coding",
                    "model_tier": "medium",
                    "total_calls": 2,
                    "success_calls": 0,
                    "failure_calls": 2,
                    "success_rate": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_workers": 2,
                    "successful_workers": 0,
                    "failed_workers": 2,
                    "worker_success_rate": 0.0,
                    "validation_total": 0,
                    "validation_passed": 0,
                    "validation_pass_rate": 0.0,
                    "runtime_request_total": 0,
                    "runtime_request_rate": 0.0,
                    "runtime_request_types": {},
                    "merge_gate_blocks": 0,
                    "failure_types": {},
                    "recent_failures": [],
                    "recommended_action": "review_worker_route_before_scaling",
                }
            ],
        },
        "model_capability_profile",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "route_guidance_blocked"
    assert payload["release_state"] == "blocked"
    assert payload["route_guidance"]["status"] == "blocked"


def test_gate_status_demotes_stale_route_guidance_with_fresh_release_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    gate_path = tmp_path / ".asteria" / "model" / "real_model_gate_report.json"
    gate_path.write_text(
        json.dumps(
            {
                "ok": True,
                "routes": {
                    "strong": {"provider": "glm", "model": "glm-5.1"},
                    "medium": {"provider": "minimax", "model": "MiniMax-M2.7"},
                },
                "model_call_summary": {"run_id": "run-fresh", "total_model_calls": 3},
            }
        ),
        encoding="utf-8",
    )
    validator = SchemaValidator(Path.cwd() / "schemas")
    JsonStore(validator).write(
        tmp_path / ".asteria" / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 4,
            "profiles": [
                {
                    "provider": "zai",
                    "model": "glm-4.7",
                    "purpose": "goal_spec",
                    "model_tier": "strong",
                    "total_calls": 5,
                    "success_calls": 3,
                    "failure_calls": 2,
                    "success_rate": 0.6,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_workers": 0,
                    "successful_workers": 0,
                    "failed_workers": 0,
                    "worker_success_rate": 0.0,
                    "validation_total": 0,
                    "validation_passed": 0,
                    "validation_pass_rate": 0.0,
                    "runtime_request_total": 0,
                    "runtime_request_rate": 0.0,
                    "runtime_request_types": {},
                    "merge_gate_blocks": 0,
                    "failure_types": {"timeout": 2},
                    "recent_failures": [],
                    "recommended_action": "keep_route",
                },
                {
                    "provider": "runtime",
                    "model": "medium-route",
                    "purpose": "coding",
                    "model_tier": "medium",
                    "total_calls": 2,
                    "success_calls": 0,
                    "failure_calls": 2,
                    "success_rate": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_workers": 2,
                    "successful_workers": 0,
                    "failed_workers": 2,
                    "worker_success_rate": 0.0,
                    "validation_total": 0,
                    "validation_passed": 0,
                    "validation_pass_rate": 0.0,
                    "runtime_request_total": 0,
                    "runtime_request_rate": 0.0,
                    "runtime_request_types": {},
                    "merge_gate_blocks": 0,
                    "failure_types": {},
                    "recent_failures": [],
                    "recommended_action": "review_worker_route_before_scaling",
                },
                {
                    "provider": "glm",
                    "model": "glm-5.1",
                    "purpose": "coding",
                    "model_tier": "strong",
                    "total_calls": 2,
                    "success_calls": 0,
                    "failure_calls": 2,
                    "success_rate": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_workers": 2,
                    "successful_workers": 0,
                    "failed_workers": 2,
                    "worker_success_rate": 0.0,
                    "validation_total": 0,
                    "validation_passed": 0,
                    "validation_pass_rate": 0.0,
                    "runtime_request_total": 0,
                    "runtime_request_rate": 0.0,
                    "runtime_request_types": {},
                    "merge_gate_blocks": 0,
                    "failure_types": {},
                    "recent_failures": [],
                    "recommended_action": "review_worker_route_before_scaling",
                },
                {
                    "provider": "fake",
                    "model": "fake-offline",
                    "purpose": "research",
                    "model_tier": "cheap",
                    "total_calls": 0,
                    "success_calls": 0,
                    "failure_calls": 0,
                    "success_rate": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_workers": 2,
                    "successful_workers": 0,
                    "failed_workers": 2,
                    "worker_success_rate": 0.0,
                    "validation_total": 0,
                    "validation_passed": 0,
                    "validation_pass_rate": 0.0,
                    "runtime_request_total": 0,
                    "runtime_request_rate": 0.0,
                    "runtime_request_types": {},
                    "merge_gate_blocks": 0,
                    "failure_types": {},
                    "recent_failures": [],
                    "recommended_action": "review_worker_route_before_scaling",
                },
            ],
        },
        "model_capability_profile",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "ready_for_small_real_task_validation"
    assert payload["release_ready"] is True
    assert payload["route_guidance"]["status"] == "healthy"
    assert payload["route_guidance"]["review"] == []
    assert payload["route_guidance"]["release_evidence_override"]["demoted_blockers"] == 3


def test_release_route_guidance_rewrites_actions_for_active_review_only() -> None:
    guidance = {
        "status": "blocked",
        "blocking": [
            {
                "purpose": "coding",
                "provider": "glm",
                "model": "glm-4.7",
                "model_tier": "strong",
                "recommended_action": "review_worker_route_before_scaling",
                "severity": 3,
            }
        ],
        "review": [
            {
                "purpose": "goal_spec",
                "provider": "zai",
                "model": "glm-4.7",
                "model_tier": "strong",
                "recommended_action": "retry_or_downgrade_strong_goal_spec",
                "severity": 2,
            }
        ],
        "provider_route_strategy": {
            "decision": "retry_or_downgrade",
            "model": "glm-4.7",
        },
        "recommended_actions": [
            "Pause scaling affected routes until provider, worker, or budget issues are resolved."
        ],
    }
    gate = {
        "ok": True,
        "routes": {"strong": {"provider": "glm", "model": "glm-4.7"}},
        "model_call_summary": {"run_id": "run-fresh"},
    }
    validation = {
        "ok": True,
        "validation_ready": True,
        "aggregate": {
            "route_evidence": {
                "strong_used": True,
                "medium_used": True,
            }
        },
    }
    core = {"ok": True}

    normalized = _release_evidence_route_guidance(guidance, gate, validation, core)

    assert normalized["status"] == "review"
    assert normalized["blocking"] == []
    assert normalized["active_review"] == normalized["review"]
    assert normalized["historical_review"][0]["release_evidence_status"] == "superseded"
    assert normalized["recommended_actions"] == [
        "Keep strong goal_spec on retry/downgrade guard; rerun one small validation sample before widening."
    ]


def test_gate_status_blocks_release_when_recent_model_call_contract_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run_dir = run_store.run_dir(run["run_id"])
    JsonlStore(validator).append(
        run_dir / "model_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "model_call_id": "modelcall-0001",
            "run_id": run["run_id"],
            "agent_id": "GoalSpecAgent",
            "purpose": "goal_spec",
            "model_provider": "glm",
            "model_name": "glm-4.7",
            "model_tier": "strong",
            "input_tokens": 10,
            "output_tokens": 20,
            "status": "success",
            "created_at": now_iso(),
            "summary": "legacy call missing role contract",
        },
        "model_call",
    )

    result = GateStatusCommand(tmp_path).run()
    payload = result.to_dict()

    assert payload["stage"] == "model_call_contract_blocked"
    assert payload["release_ready"] is False
    assert payload["model_call_contract"]["status"] == "blocked"
    assert payload["model_call_contract"]["violations"][0]["missing"] == [
        "agent_role_contract",
        "deadline_ms",
        "streaming",
    ]
    assert "Model call contract: blocked" in result.to_text()


def test_gate_status_accepts_recent_model_call_contract_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run_dir = run_store.run_dir(run["run_id"])
    JsonlStore(validator).append(
        run_dir / "model_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "model_call_id": "modelcall-0001",
            "run_id": run["run_id"],
            "agent_id": "GoalSpecAgent",
            "agent_role": "GoalSpecAgent",
            "agent_role_contract": {
                "role": "GoalSpecAgent",
                "purpose": "goal_spec",
                "default_model_tier": "strong",
                "deadline_profile": "strong_goal_spec",
                "provider_call_seconds": 120,
                "stream_idle_timeout_seconds": 30,
                "max_model_calls": 1,
                "responsibilities": [],
                "escalation_policy": "test",
            },
            "deadline_profile": "strong_goal_spec",
            "deadline_ms": 120000,
            "purpose": "goal_spec",
            "model_provider": "glm",
            "model_name": "glm-4.7",
            "model_tier": "strong",
            "input_tokens": 10,
            "output_tokens": 20,
            "duration_ms": 100,
            "streaming": {
                "requested": True,
                "supported": True,
                "mode": "streaming",
                "chunk_count": 1,
                "deadline_ms": 120000,
                "idle_timeout_ms": 30000,
            },
            "status": "success",
            "created_at": now_iso(),
            "summary": "contract-ready call",
        },
        "model_call",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "ready_for_small_real_task_validation"
    assert payload["model_call_contract"]["status"] == "healthy"
    assert payload["model_call_contract"]["checked_calls"] == 1


def test_gate_status_prefers_real_model_gate_run_for_model_call_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_store = RunStore(tmp_path / ".asteria", validator)
    legacy = run_store.create_run("legacy")
    fresh = run_store.create_run("fresh")
    JsonlStore(validator).append(
        run_store.run_dir(legacy["run_id"]) / "model_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "model_call_id": "modelcall-legacy",
            "run_id": legacy["run_id"],
            "agent_id": "GoalSpecAgent",
            "purpose": "goal_spec",
            "model_provider": "glm",
            "model_name": "glm-4.7",
            "model_tier": "strong",
            "input_tokens": 10,
            "output_tokens": 20,
            "status": "success",
            "created_at": now_iso(),
            "summary": "legacy call missing role contract",
        },
        "model_call",
    )
    JsonlStore(validator).append(
        run_store.run_dir(fresh["run_id"]) / "model_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "model_call_id": "modelcall-fresh",
            "run_id": fresh["run_id"],
            "agent_id": "GoalSpecAgent",
            "agent_role": "GoalSpecAgent",
            "agent_role_contract": {
                "role": "GoalSpecAgent",
                "purpose": "goal_spec",
                "default_model_tier": "strong",
                "deadline_profile": "strong_goal_spec",
                "provider_call_seconds": 120,
                "stream_idle_timeout_seconds": 30,
                "max_model_calls": 1,
                "responsibilities": [],
                "escalation_policy": "test",
            },
            "deadline_profile": "strong_goal_spec",
            "deadline_ms": 120000,
            "purpose": "goal_spec",
            "model_provider": "glm",
            "model_name": "glm-5.1",
            "model_tier": "strong",
            "input_tokens": 10,
            "output_tokens": 20,
            "duration_ms": 100,
            "streaming": {
                "requested": True,
                "supported": True,
                "mode": "streaming",
                "chunk_count": 1,
                "deadline_ms": 120000,
                "idle_timeout_ms": 30000,
            },
            "status": "success",
            "created_at": now_iso(),
            "summary": "contract-ready gate call",
        },
        "model_call",
    )
    (tmp_path / ".asteria" / "model" / "real_model_gate_report.json").write_text(
        json.dumps(
            {
                "ok": True,
                "model_call_summary": {
                    "run_id": fresh["run_id"],
                    "total_model_calls": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "ready_for_small_real_task_validation"
    assert payload["model_call_contract"]["status"] == "healthy"
    assert payload["model_call_contract"]["checked_calls"] == 1
    assert payload["model_call_contract"]["evidence_scope"] == "real_model_gate_run"


def test_gate_status_blocks_validation_when_candidate_promotions_are_unresolved(
    tmp_path: Path, monkeypatch
) -> None:
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    JsonlStore(validator).append(
        run_store.run_dir(run["run_id"]) / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": run["run_id"],
            "task_id": "task-0001",
            "candidate_id": "candidate-0001",
            "workspace": str(tmp_path / ".asteria" / "runs" / run["run_id"] / "cw" / "0001"),
            "strategy": "temp_workspace",
            "workspace_policy": "isolated_copy",
            "backend_reason": "test",
            "branch_name": None,
            "promotable_files": ["tool.py"],
            "promoted_files": [],
            "status": "pending_manual_approval",
            "approval_mode": "manual",
            "merge_gate": {"ok": True},
            "failure": None,
            "decision": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        },
        "candidate_promotion",
    )

    payload = GateStatusCommand(tmp_path).run().to_dict()

    assert payload["stage"] == "candidate_promotion_risk_blocked"
    assert payload["release_state"] == "blocked"
    assert payload["release_ready"] is False
    assert payload["promotion_release_risks"]["pending"] == 1
    assert payload["promotion_release_risks"]["risk_policy"]["max_pending_release_promotions"] == 0
    assert "promotion_failed" in payload["promotion_release_risks"]["release_blocking_statuses"]
    assert "Resolve release-blocking candidate promotions" in payload["blocking_reason"]


def _configure_release_routes(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "glm-4.7")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.setenv("AGENT_MODEL_STRONG_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_NAME", "MiniMax-M2.7")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "minimax-key")


def _write_release_ready_gate_files(tmp_path: Path) -> None:
    gate_dir = tmp_path / ".asteria" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}), encoding="utf-8"
    )
    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    (verification_dir / "real_model_acceptance_validation.json").write_text(
        json.dumps(
            {
                "ok": True,
                "validation_ready": True,
                "aggregate": {
                    "total": 4,
                    "passed": 4,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "aggregate": {"total": 10, "passed": 10}}),
        encoding="utf-8",
    )


def test_gate_status_recommends_validation_by_change_shape() -> None:
    docs = _validation_recommendation_for_changed_files(["docs/zh/运行命令.md"])
    source = _validation_recommendation_for_changed_files(["src/asteria_runtime/cli.py"])
    broad = _validation_recommendation_for_changed_files(
        [
            "src/asteria_runtime/core/a.py",
            "src/asteria_runtime/core/b.py",
            "src/asteria_runtime/commands/c.py",
            "src/asteria_runtime/acceptance/d.py",
        ]
    )

    assert docs["level"] == "targeted"
    assert source["level"] == "core_subset"
    assert broad["level"] == "full_validation_core"


def _write_plugin_manifest(
    root: Path,
    *,
    hook_subscriptions: list[str] | None = None,
) -> None:
    plugin_dir = root / ".asteria" / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "audit.plugin.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "plugin_id": "example.audit",
                "name": "Example Audit Plugin",
                "version": "0.1.0",
                "enabled": True,
                "entrypoint": "plugins/example_audit.py",
                "hook_subscriptions": hook_subscriptions or ["after_tool_call"],
                "permissions": {
                    "network": False,
                    "shell": False,
                    "write_workspace": False,
                    "read_secrets": False,
                },
                "capabilities": ["audit-log"],
                "description": "Records audit metadata.",
            }
        ),
        encoding="utf-8",
    )


def test_validation_recommendation_treats_governance_changes_as_full_validation_core() -> None:
    schema = _validation_recommendation_for_changed_files(["schemas/plugin_manifest.schema.json"])
    policy = _validation_recommendation_for_changed_files(["templates/policies.default.json"])
    hook = _validation_recommendation_for_changed_files(
        ["src/asteria_runtime/core/runtime_hooks.py"]
    )
    assert schema["level"] == "full_validation_core"
    assert "governance" in schema["reason"].lower() or "schema" in schema["reason"].lower()
    assert policy["level"] == "full_validation_core"
    assert hook["level"] == "full_validation_core"


def test_gate_status_blocks_release_when_plugin_manifests_are_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    (tmp_path / ".asteria" / "policies.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "hooks": {
                    "enabled": True,
                    "plugins_enabled": False,
                    "allowed_hook_names": ["before_tool_call", "after_tool_call"],
                },
            }
        ),
        encoding="utf-8",
    )
    _write_plugin_manifest(tmp_path, hook_subscriptions=["unknown_hook"])
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "plugin_manifests_blocked"
    payload = result.to_dict()
    assert payload["release_state"] == "blocked"
    assert payload["plugin_risks"]["blocked"] is True
    assert len(payload["plugin_risks"]["blocked_manifests"]) > 0


def test_status_gate_and_gate_status_include_latest_real_provider_matrix(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    InitCommand(tmp_path).run()
    _write_real_provider_matrix_summary(tmp_path)

    status_result = StatusCommand(tmp_path).run()
    status_payload = status_result.to_dict()
    assert status_payload["latest_real_provider_matrix"]["provider_mode"] == "real"
    assert status_payload["latest_real_provider_matrix"]["latest_route"] == "repair"
    assert status_payload["latest_real_provider_matrix"]["agent_loop_recorded"] == 2
    assert status_payload["latest_real_provider_matrix"]["recovery_satisfied"] == 1
    assert status_payload["latest_real_provider_matrix"]["context_strategy_recorded"] == 2
    assert status_payload["latest_real_provider_matrix"]["context_modes"] == {
        "focused": 1,
        "slim": 2,
    }
    assert status_payload["latest_real_provider_matrix"]["slim_model_calls"] == 2
    assert status_payload["latest_real_provider_matrix"]["strong_model_calls"] == 1
    assert status_payload["latest_real_provider_matrix"]["task_execution_model_calls"] == 2
    assert status_payload["latest_real_provider_matrix"]["task_repair_model_calls"] == 1
    assert status_payload["latest_real_provider_matrix"]["run_review_model_calls"] == 1
    assert status_payload["latest_real_provider_matrix"]["budget_repair_attempts"] == 1
    trend = status_payload["latest_real_provider_matrix"]["trend"]
    assert trend["sample_count"] == 1
    assert (
        trend["cases"]["single_file_bugfix"]["latest_retry_classification"]
        == "failed_after_repair"
    )
    assert "Latest real-provider matrix: 1/2 passed" in status_result.to_text()
    assert "agent loop: 2/2 recorded, recovery 1/1 covered" in status_result.to_text()
    assert "context: 2/2 recorded, slim 2/3 calls" in status_result.to_text()
    assert "models: strong=1, task_execution=2, task_repair=1, run_review=1" in status_result.to_text()
    assert "single_file_bugfix: task_execution avg=1.0" in status_result.to_text()
    assert "route=repair" in "\n".join(status_payload["evidence_chain"])

    gate_status_result = GateStatusCommand(tmp_path).run()
    gate_status_payload = gate_status_result.to_dict()
    assert gate_status_payload["latest_real_provider_matrix"]["latest_task_kind"] == "bugfix"
    assert "Latest real-provider matrix: 1/2 passed" in gate_status_result.to_text()
    assert "context: 2/2 recorded, slim 2/3 calls" in gate_status_result.to_text()
    assert "Latest real-provider P0 matrix failed" in gate_status_payload["next_actions"][0]
    assert "requires repair" in gate_status_payload["next_actions"][0]
    assert "asteria debug" in gate_status_payload["next_actions"][1]
    assert any(
        "planner/tool-contract evidence" in action
        for action in gate_status_payload["next_actions"]
    )

    gate_result = GateCommand(tmp_path).run()
    gate_payload = gate_result.to_dict()
    assert gate_payload["latest_real_provider_matrix"]["latest_case"] == "single_file_bugfix"
    assert "Latest real-provider matrix: 1/2 passed" in gate_result.to_text()
    assert "real_provider_matrix=1/2 route=repair" in "\n".join(gate_result._evidence_chain())


def test_latest_real_provider_matrix_prefers_real_over_newer_fake(tmp_path: Path) -> None:
    agent_dir = tmp_path / ".asteria"
    real_dir = agent_dir / "verification" / "real_provider_matrix" / "real-run"
    fake_dir = agent_dir / "verification" / "real_provider_matrix" / "fake-run"
    real_dir.mkdir(parents=True)
    fake_dir.mkdir(parents=True)
    real_payload = dict(_real_provider_matrix_payload())
    real_payload["provider_mode"] = "real"
    real_payload["created_at"] = "2026-06-03T10:00:00Z"
    fake_payload = dict(_real_provider_matrix_payload())
    fake_payload["provider_mode"] = "fake"
    fake_payload["created_at"] = "2026-06-04T10:00:00Z"
    fake_payload["cases"] = [
        {
            **fake_payload["cases"][0],
            "name": "context_maintenance",
            "route": "context_slimming",
        }
    ]
    (real_dir / "matrix_summary.json").write_text(json.dumps(real_payload), encoding="utf-8")
    (fake_dir / "matrix_summary.json").write_text(json.dumps(fake_payload), encoding="utf-8")

    latest = latest_real_provider_matrix(agent_dir)

    assert latest["provider_mode"] == "real"
    assert latest["summary_path"].endswith("real-run\\matrix_summary.json") or latest[
        "summary_path"
    ].endswith("real-run/matrix_summary.json")


def test_latest_real_provider_matrix_trends_single_file_bugfix_retries(tmp_path: Path) -> None:
    agent_dir = tmp_path / ".asteria"
    matrix_root = agent_dir / "verification" / "real_provider_matrix"
    first = dict(_real_provider_matrix_payload())
    first["created_at"] = "2026-06-03T10:00:00Z"
    second = dict(_real_provider_matrix_payload())
    second["created_at"] = "2026-06-04T10:00:00Z"
    second["ok"] = True
    second["passed"] = 2
    second["failed"] = 0
    second["cases"] = [_single_file_bugfix_case(task_execution_calls=3, repair_attempts=0)]
    second["case_count"] = 1
    _write_matrix_payload(matrix_root / "matrix-1", first)
    _write_matrix_payload(matrix_root / "matrix-2", second)

    latest = latest_real_provider_matrix(agent_dir)

    trend = latest["trend"]
    bugfix = trend["cases"]["single_file_bugfix"]
    assert trend["sample_count"] == 2
    assert bugfix["sample_count"] == 2
    assert bugfix["task_execution_model_calls_max"] == 3
    assert bugfix["retry_classifications"] == {
        "extra_execution_without_repair": 1,
        "failed_after_repair": 1,
    }
    assert not any("single_file_bugfix still entered repair" in item for item in trend["warnings"])


def test_matrix_case_retry_classification_names_extra_execution_without_repair() -> None:
    case = _single_file_bugfix_case(task_execution_calls=2, repair_attempts=0)

    assert classify_matrix_case_retry(case) == "extra_execution_without_repair"


def test_matrix_case_retry_classification_prioritizes_provider_transient() -> None:
    case = _single_file_bugfix_case(task_execution_calls=1, repair_attempts=1)
    case["failure_summary"] = "TLS EOF while reading provider stream"
    case["context_strategy"] = {
        **case["context_strategy"],
        "failed_model_calls": 1,
        "failed_model_call_types": {"network": 1},
    }

    assert classify_matrix_case_retry(case) == "provider_transient"


def test_matrix_case_retry_classification_uses_legacy_purpose_counts() -> None:
    case = _single_file_bugfix_case(task_execution_calls=0, repair_attempts=0)
    context = case["context_strategy"]
    context.pop("task_execution_model_calls", None)
    context.pop("task_repair_model_calls", None)
    context.pop("run_review_model_calls", None)
    context["purposes"] = {"task_execution": 2}

    assert classify_matrix_case_retry(case) == "extra_execution_without_repair"


def test_real_provider_matrix_next_actions_explain_extra_bugfix_execution() -> None:
    matrix = {
        "ok": True,
        "summary_path": "matrix-summary.json",
        "trend": {
            "cases": {
                "single_file_bugfix": {
                    "retry_classifications": {"extra_execution_without_repair": 2},
                    "strong_model_calls_max": 0,
                }
            },
            "warnings": [],
        },
    }

    actions = _real_provider_matrix_next_actions(matrix)

    assert actions == [
        (
            "Review single_file_bugfix prompt/schema for extra medium execution without repair; "
            "compare task_execution model calls in matrix-summary.json."
        )
    ]


def test_real_provider_matrix_next_actions_follow_latest_bugfix_classification() -> None:
    matrix = {
        "ok": True,
        "summary_path": "matrix-summary.json",
        "trend": {
            "cases": {
                "single_file_bugfix": {
                    "latest_retry_classification": "stable_single_execution",
                    "retry_classifications": {
                        "repair_loop": 1,
                        "stable_single_execution": 1,
                    },
                    "strong_model_calls_max": 0,
                }
            },
            "warnings": [],
        },
    }

    assert _real_provider_matrix_next_actions(matrix) == []


def test_real_provider_matrix_next_actions_route_provider_transient_to_model_check() -> None:
    matrix = {
        "ok": False,
        "latest_route": "repair",
        "latest_task_kind": "bugfix",
        "latest_case": "single_file_bugfix",
        "latest_retry_classification": "provider_transient",
        "summary_path": "matrix_summary.json",
        "trend": {
            "cases": {
                "single_file_bugfix": {
                    "latest_retry_classification": "provider_transient",
                    "retry_classifications": {"provider_transient": 1},
                }
            }
        },
    }

    actions = _real_provider_matrix_next_actions(matrix)

    assert any("model-check" in action for action in actions)
    assert any("provider transient" in action for action in actions)
    assert not any("asteria debug" in action for action in actions)


def test_review_markdown_report_includes_latest_real_provider_matrix(tmp_path: Path) -> None:
    report = ReviewCommand(tmp_path)._markdown_report(
        _minimal_eval_report(),
        latest_real_provider_matrix=summarize_real_provider_matrix(
            _real_provider_matrix_payload(),
            tmp_path
            / ".asteria"
            / "verification"
            / "real_provider_matrix"
            / "run-1"
            / "matrix_summary.json",
        ),
    )

    assert "## Latest Real Provider Matrix" in report
    assert "Latest real-provider matrix: 1/2 passed" in report
    assert "context: 2/2 recorded, slim 2/3 calls" in report
    assert "single_file_bugfix" in report
    assert "repair" in report


def _write_real_provider_matrix_summary(root: Path) -> Path:
    path = root / ".asteria" / "verification" / "real_provider_matrix" / "run-1"
    return _write_matrix_payload(path, _real_provider_matrix_payload())


def _write_matrix_payload(path: Path, payload: dict) -> Path:
    path.mkdir(parents=True)
    summary_path = path / "matrix_summary.json"
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    return summary_path


def _single_file_bugfix_case(
    *,
    task_execution_calls: int,
    repair_attempts: int,
) -> dict:
    case = dict(_real_provider_matrix_payload()["cases"][1])
    case["ok"] = True
    case["failure_type"] = None
    case["failure_summary"] = None
    case["agent_loop"] = {
        **case["agent_loop"],
        "exit_reason": "completed",
        "recommended_command": None,
        "budget_repair_attempts": repair_attempts,
        "recovery_required": False,
        "recovery_satisfied": True,
    }
    case["context_strategy"] = {
        **case["context_strategy"],
        "model_call_count": task_execution_calls + repair_attempts + 1,
        "strong_model_calls": 0,
        "failed_model_calls": 0,
        "task_execution_model_calls": task_execution_calls,
        "task_repair_model_calls": repair_attempts,
        "run_review_model_calls": 0,
        "fast_path_task_kinds": {"single_file_bugfix": task_execution_calls},
        "purposes": {
            "task_execution": task_execution_calls,
            "task_repair": repair_attempts,
        },
        "purpose_context_modes": {
            "task_execution": {"slim": task_execution_calls},
            "task_repair": {"slim": repair_attempts},
        },
    }
    return case


def _real_provider_matrix_payload() -> dict:
    return {
        "schema_version": "0.1.0",
        "matrix": "p0",
        "provider_mode": "real",
        "created_at": "2026-05-24T19:00:00Z",
        "ok": False,
        "case_count": 2,
        "passed": 1,
        "failed": 1,
        "duration_seconds": 12.3,
        "output_dir": "matrix-output",
        "cases": [
            {
                "name": "file_output",
                "task_kind": "file_output",
                "route": "artifact_creation",
                "reason": "Create requested file.",
                "ok": True,
                "workspace": "matrix-output/file_output",
                "summary_json": "matrix-output/file_output_summary.json",
                "expected_file": "hello.txt",
                "expected_text": "hello",
                "run_id": "run-file",
                "final_report": "matrix-output/file_output/.asteria/runs/run-file/final_report.md",
                "diagnostics": {},
                "agent_loop": {
                    "status": "recorded",
                    "summary_path": "matrix-output/file_output/.asteria/runs/run-file/agent_loop_run_summary.json",
                    "exit_reason": "completed",
                    "recommended_command": None,
                    "latest_action": "tool",
                    "rounds_completed": 1,
                    "max_rounds": 2,
                    "budget_status": "within_budget",
                    "budget_highest_label": "model_calls",
                    "budget_model_calls": 2,
                    "budget_tool_calls": 3,
                    "budget_repair_attempts": 0,
                    "context_pressure_status": "within_budget",
                    "context_window_ratio": 0.1,
                    "recovery_required": False,
                    "recovery_satisfied": True,
                },
                "context_strategy": {
                    "status": "recorded",
                    "model_calls_path": "file_output/model_calls.jsonl",
                    "model_call_count": 2,
                    "context_modes": {"slim": 2},
                    "fast_path_task_kinds": {"simple_file": 2},
                    "model_tiers": {"medium": 2},
                    "purposes": {"task_execution": 1, "run_review": 1},
                    "purpose_context_modes": {
                        "task_execution": {"slim": 1},
                        "run_review": {"slim": 1},
                    },
                    "context_mode_recorded": 2,
                    "slim_model_calls": 2,
                    "strong_model_calls": 0,
                    "failed_model_calls": 0,
                    "task_execution_model_calls": 1,
                    "task_repair_model_calls": 0,
                    "run_review_model_calls": 1,
                    "average_context_estimated_tokens": 1500,
                    "max_context_estimated_tokens": 2000,
                },
                "failure_type": None,
                "failure_summary": None,
                "evidence_refs": ["file-output/final_report.json"],
            },
            {
                "name": "single_file_bugfix",
                "task_kind": "bugfix",
                "route": "repair",
                "reason": "Verification failed and needs repair.",
                "ok": False,
                "workspace": "matrix-output/single_file_bugfix",
                "summary_json": "matrix-output/single_file_bugfix_summary.json",
                "expected_file": "calc.py",
                "expected_text": "def add",
                "run_id": None,
                "final_report": None,
                "diagnostics": {},
                "agent_loop": {
                    "status": "recorded",
                    "summary_path": "matrix-output/single_file_bugfix/.asteria/runs/run-bugfix/agent_loop_run_summary.json",
                    "exit_reason": "tool_failed",
                    "recommended_command": "debug",
                    "latest_action": "repair",
                    "rounds_completed": 2,
                    "max_rounds": 3,
                    "budget_status": "within_budget",
                    "budget_highest_label": "tool_budget_units",
                    "budget_model_calls": 4,
                    "budget_tool_calls": 7,
                    "budget_repair_attempts": 1,
                    "context_pressure_status": "within_budget",
                    "context_window_ratio": 0.2,
                    "recovery_required": True,
                    "recovery_satisfied": True,
                },
                "context_strategy": {
                    "status": "recorded",
                    "model_calls_path": "bugfix/model_calls.jsonl",
                    "model_call_count": 1,
                    "context_modes": {"focused": 1},
                    "fast_path_task_kinds": {"complex_change": 1},
                    "model_tiers": {"strong": 1},
                    "purposes": {"task_execution": 1, "task_repair": 1},
                    "purpose_context_modes": {"task_execution": {"focused": 1}},
                    "context_mode_recorded": 1,
                    "slim_model_calls": 0,
                    "strong_model_calls": 1,
                    "failed_model_calls": 1,
                    "task_execution_model_calls": 1,
                    "task_repair_model_calls": 1,
                    "run_review_model_calls": 0,
                    "average_context_estimated_tokens": 3000,
                    "max_context_estimated_tokens": 3000,
                },
                "failure_type": "SmokeFailure",
                "failure_summary": "pytest failed",
                "evidence_refs": ["bugfix/eval_report.json", "bugfix/tool_calls.jsonl"],
            },
        ],
    }


def _minimal_eval_report() -> dict:
    return {
        "overall": {"status": "partial", "score": 0.5, "reason": "needs repair"},
        "goal_eval": {"requirement_coverage": 0.8},
        "artifact_eval": {"artifacts_present": True},
        "outcome_eval": {"verification_pass_rate": 0.5},
        "trajectory_eval": {},
        "cost_eval": {},
        "failure_classification": {
            "category": "verification_failed",
            "recommended_command": "debug",
            "reason": "Verification failed.",
        },
    }
