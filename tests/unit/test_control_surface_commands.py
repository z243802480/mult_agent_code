import json
from pathlib import Path

from asteria_runtime.commands.doctor_command import DoctorCommand
from asteria_runtime.commands.gate_command import GateCommand
from asteria_runtime.commands.gate_status_command import GateStatusCommand
from asteria_runtime.commands.gate_status_command import _validation_recommendation_for_changed_files
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.package_check_command import PackageCheckCommand
from asteria_runtime.commands.status_command import StatusCommand
from asteria_runtime.commands.version_command import VersionCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
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


def test_package_check_reports_packaging_preflight() -> None:
    result = PackageCheckCommand(Path.cwd()).run()

    assert result.ok
    text = result.to_text()
    assert "Package check" in text
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "pass"
    assert any(check["name"] == "version_sync" for check in payload["checks"])
    gray_modules = next(check for check in payload["checks"] if check["name"] == "gray_command_modules")
    assert "gray-run" in gray_modules["summary"]
    assert any(check["name"] == "gray_route_template" for check in payload["checks"])
    assert any(check["name"] == "gray_runbook" for check in payload["checks"])
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
    assert payload["runbook"]["path"] == "docs/zh/灰度试运行手册.md"
    assert "rollback" in payload["runbook"]["required_sections"]
    assert any("model.routes.gray.example.ps1" in action for action in payload["next_actions"])
    assert any("灰度试运行手册.md" in action for action in payload["next_actions"])
    assert "Run `asteria version --json`" in payload["next_actions"][-1]


def test_status_reports_uninitialized_workspace(tmp_path: Path) -> None:
    result = StatusCommand(tmp_path).run()

    assert result.initialized is False
    assert "Conclusion: Workspace is not initialized." in result.to_text()
    assert "Next: asteria init" in result.to_text()
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "uninitialized"
    assert payload["next_actions"] == ["Run `asteria /init --root .`."]
    _assert_control_surface_contract(
        payload,
        command="status",
        audience="user_workflow",
        required_fields={
            "schema_version",
            "status",
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

    payload = StatusCommand(tmp_path).run().to_dict()

    assert payload["recommended_next_command"] == "review"
    assert payload["next_actions"] == ["Run `asteria review`."]


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

    payload = StatusCommand(tmp_path).run().to_dict()

    assert payload["recommended_next_command"] == "accept"
    assert payload["next_actions"] == ["Run `asteria accept`."]


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
    assert payload["next_actions"] == []


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
    gate_stage = next(stage for stage in result.stages["release"] if stage["name"] == "acceptance-gate")
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
            "data": {"reason": "parallel_safe_batch_selection", "task_ids": ["task-0001", "task-0002"]},
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
    assert worker_tree["collaboration_summary"]["failure_evidence_refs"] == [
        "task-failure-0001"
    ]
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
    assert payload["gray_task_limits"]["max_iterations"] == 3
    assert payload["plugin_control"]["hook_policy"]["plugins_enabled"] is False
    assert "plugin" in payload["error_taxonomy"]["categories"]
    assert next(check for check in payload["checks"] if check["name"] == "plugins")[
        "error_type"
    ] == "plugin"
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
    assert any("灰度试运行手册.md" in action for action in payload["next_actions"])


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


def test_gate_status_moves_from_gate_to_gray_to_core(tmp_path: Path, monkeypatch) -> None:
    _configure_release_routes(monkeypatch)
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "missing_real_model_gate"
    _assert_control_surface_contract(
        result.to_dict(),
        command="gate-status",
        audience="maintainer_release_readiness",
        required_fields={
            "schema_version",
            "stage",
            "rollout_state",
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
        json.dumps({"ok": True, "recommended_actions": ["run gray"]}),
        encoding="utf-8",
    )
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "ready_for_gray_suite"
    assert result.to_dict()["rollout_state"] == "conditional"

    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    (verification_dir / "real_model_acceptance_gray.json").write_text(
        json.dumps(
            {
                "ok": True,
                "gray_ready": True,
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
    assert "gray_ready: True" in result.to_text()

    (verification_dir / "real_model_acceptance_core.json").write_text(
        json.dumps({"ok": True, "aggregate": {"total": 6, "passed": 6}}),
        encoding="utf-8",
    )
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "ready_for_small_real_task_gray"
    payload = result.to_dict()
    assert payload["stage"] == "ready_for_small_real_task_gray"
    assert payload["rollout_state"] == "release_ready"
    assert payload["release_ready"] is True
    assert payload["blocking_reason"] is None
    assert payload["gates"]["gray_suite"]["gray_ready"] is True
    assert payload["gray_report"]["gray_ready"] is True
    assert payload["route_environment"]["ready"] is True
    assert payload["promotion_release_risks"]["pending"] == 0
    assert payload["gray_task_limits"]["max_tasks_per_iteration"] == 1
    assert "--no-research" in payload["next_actions"][0]
    assert payload["route_guidance"]["status"] == "healthy"
    assert payload["validation_recommendation"]["level"] in {
        "none",
        "targeted",
        "core_subset",
        "full_gray_core",
    }


def test_gate_status_uses_latest_gray_acceptance_summary(
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
    stale = verification_dir / "real_model_acceptance_gray.json"
    fresh = verification_dir / "real_model_acceptance_gray_after_fix.json"
    stale.write_text(
        json.dumps(
            {
                "ok": False,
                "suite": "gray",
                "gray_ready": False,
                "aggregate": {"total": 7, "passed": 3, "failed": 4},
            }
        ),
        encoding="utf-8",
    )
    fresh.write_text(
        json.dumps(
            {
                "ok": True,
                "suite": "gray",
                "gray_ready": True,
                "aggregate": {
                    "total": 7,
                    "passed": 7,
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

    assert payload["stage"] == "ready_for_small_real_task_gray"
    assert payload["gates"]["gray_suite"]["passed"] == 7
    assert payload["evidence_sources"]["gray_suite"].endswith(
        "real_model_acceptance_gray_after_fix.json"
    )


def test_gate_status_prefers_passing_canonical_gray_summary(
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
    (verification_dir / "real_model_acceptance_gray.json").write_text(
        json.dumps(
            {
                "ok": True,
                "suite": "gray",
                "gray_ready": True,
                "aggregate": {
                    "total": 7,
                    "passed": 7,
                    "failed": 0,
                    "route_evidence": {"strong_used": True, "medium_used": True},
                },
            }
        ),
        encoding="utf-8",
    )
    (verification_dir / "real_model_acceptance_gray_named_history.json").write_text(
        json.dumps(
            {
                "ok": True,
                "suite": "gray",
                "gray_ready": True,
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

    assert payload["gates"]["gray_suite"]["total"] == 7
    assert payload["evidence_sources"]["gray_suite"].endswith("real_model_acceptance_gray.json")


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
    (verification_dir / "real_model_acceptance_gray.json").write_text(
        json.dumps(
            {
                "ok": True,
                "gray_ready": True,
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
    assert payload["rollout_state"] == "blocked"
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
    (verification_dir / "real_model_acceptance_gray.json").write_text(
        json.dumps(
            {
                "ok": True,
                "gray_ready": True,
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

    assert payload["stage"] == "ready_for_small_real_task_gray"
    assert payload["rollout_state"] == "release_ready"
    assert payload["route_environment"]["medium"]["source"] == "global"
    assert payload["route_environment"]["medium"]["provider"] == "minimax"


def test_gate_status_blocks_gray_when_capability_route_guidance_is_blocked(
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
    assert payload["rollout_state"] == "blocked"
    assert payload["route_guidance"]["status"] == "blocked"


def test_gate_status_blocks_gray_when_candidate_promotions_are_unresolved(
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
    assert payload["rollout_state"] == "blocked"
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
    (gate_dir / "real_model_gate_report.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    verification_dir = tmp_path / ".asteria" / "verification"
    verification_dir.mkdir(parents=True)
    (verification_dir / "real_model_acceptance_gray.json").write_text(
        json.dumps(
            {
                "ok": True,
                "gray_ready": True,
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
    assert broad["level"] == "full_gray_core"


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


def test_validation_recommendation_treats_governance_changes_as_full_gray_core() -> None:
    schema = _validation_recommendation_for_changed_files(["schemas/plugin_manifest.schema.json"])
    policy = _validation_recommendation_for_changed_files(["templates/policies.default.json"])
    hook = _validation_recommendation_for_changed_files(
        ["src/asteria_runtime/core/runtime_hooks.py"]
    )
    assert schema["level"] == "full_gray_core"
    assert "governance" in schema["reason"].lower() or "schema" in schema["reason"].lower()
    assert policy["level"] == "full_gray_core"
    assert hook["level"] == "full_gray_core"


def test_gate_status_blocks_release_when_plugin_manifests_are_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _configure_release_routes(monkeypatch)
    _write_release_ready_gate_files(tmp_path)
    (tmp_path / ".asteria" / "policies.json").write_text(
        json.dumps({
            "schema_version": "0.1.0",
            "hooks": {
                "enabled": True,
                "plugins_enabled": False,
                "allowed_hook_names": ["before_tool_call", "after_tool_call"],
            },
        }),
        encoding="utf-8",
    )
    _write_plugin_manifest(tmp_path, hook_subscriptions=["unknown_hook"])
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "plugin_manifests_blocked"
    payload = result.to_dict()
    assert payload["rollout_state"] == "blocked"
    assert payload["plugin_risks"]["blocked"] is True
    assert len(payload["plugin_risks"]["blocked_manifests"]) > 0

