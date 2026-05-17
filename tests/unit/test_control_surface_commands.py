import json
from pathlib import Path

from asteria_runtime.commands.doctor_command import DoctorCommand
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


def test_version_command_reports_runtime_diagnostics() -> None:
    result = VersionCommand().run()

    assert "asteria-runtime" in result.to_text()
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["package"] == "asteria-runtime"
    assert payload["version"]
    assert payload["python_version"]
    assert payload["executable"]


def test_package_check_reports_packaging_preflight() -> None:
    result = PackageCheckCommand(Path.cwd()).run()

    assert result.ok
    text = result.to_text()
    assert "Package check" in text
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "pass"
    assert any(check["name"] == "version_sync" for check in payload["checks"])
    assert any(check["name"] == "gray_route_template" for check in payload["checks"])
    assert any(check["name"] == "gray_runbook" for check in payload["checks"])
    assert payload["runbook"]["path"] == "docs/zh/灰度试运行手册.md"
    assert "rollback" in payload["runbook"]["required_sections"]
    assert any("model.routes.gray.example.ps1" in action for action in payload["next_actions"])
    assert any("灰度试运行手册.md" in action for action in payload["next_actions"])
    assert "Run `asteria version --json`" in payload["next_actions"][-1]


def test_status_reports_uninitialized_workspace(tmp_path: Path) -> None:
    result = StatusCommand(tmp_path).run()

    assert result.initialized is False
    assert "Next: asteria init" in result.to_text()
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "uninitialized"
    assert payload["next_actions"] == ["Run `asteria /init --root .`."]


def test_status_reports_initialized_workspace_without_sessions(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = StatusCommand(tmp_path).run()

    assert result.initialized is True
    assert result.current_session_id is None
    assert "No sessions yet." in result.to_text()
    assert result.to_dict()["initialized"] is True


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
    assert payload["gray_task_limits"]["max_tasks_per_iteration"] == 1
    assert "--no-research" in payload["next_actions"][0]
    assert payload["route_guidance"]["status"] == "healthy"
    assert payload["validation_recommendation"]["level"] in {
        "none",
        "targeted",
        "core_subset",
        "full_gray_core",
    }


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
