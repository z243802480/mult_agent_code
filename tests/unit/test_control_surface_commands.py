import json
from pathlib import Path

from agent_runtime.commands.doctor_command import DoctorCommand
from agent_runtime.commands.gate_status_command import GateStatusCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.package_check_command import PackageCheckCommand
from agent_runtime.commands.status_command import StatusCommand
from agent_runtime.commands.version_command import VersionCommand


def test_version_command_reports_runtime_diagnostics() -> None:
    result = VersionCommand().run()

    assert "agent-runtime" in result.to_text()
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["package"] == "agent-runtime"
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
    assert any("model.routes.gray.example.ps1" in action for action in payload["next_actions"])
    assert "Run `agent version --json`" in payload["next_actions"][-1]


def test_status_reports_uninitialized_workspace(tmp_path: Path) -> None:
    result = StatusCommand(tmp_path).run()

    assert result.initialized is False
    assert "Next: agent init" in result.to_text()
    payload = result.to_dict()
    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "uninitialized"
    assert payload["next_actions"] == ["Run `agent /init --root .`."]


def test_status_reports_initialized_workspace_without_sessions(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = StatusCommand(tmp_path).run()

    assert result.initialized is True
    assert result.current_session_id is None
    assert "No sessions yet." in result.to_text()
    assert result.to_dict()["initialized"] is True


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
        "AGENT_MODEL_MEDIUM_PROVIDER",
        "AGENT_MODEL_MEDIUM_NAME",
        "AGENT_MODEL_MEDIUM_API_KEY",
    ]
    assert "preferred_backend" in payload["sandbox"]
    assert payload["gray_task_limits"]["max_iterations"] == 3


def test_doctor_reports_exact_missing_medium_route_variables(
    tmp_path: Path, monkeypatch
) -> None:
    InitCommand(tmp_path).run()
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "glm-4.7")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_PROVIDER", raising=False)

    result = DoctorCommand(tmp_path).run()

    payload = result.to_dict()
    assert payload["ok"] is True
    assert payload["routes"]["medium"]["configured"] is False
    assert payload["failed_checks"] == ["git", "model_medium", "real_model_gate"]
    assert any(
        "AGENT_MODEL_MEDIUM_PROVIDER, AGENT_MODEL_MEDIUM_NAME, AGENT_MODEL_MEDIUM_API_KEY"
        in action
        for action in payload["next_actions"]
    )


def test_doctor_fails_for_missing_workspace_guidance(tmp_path: Path) -> None:
    result = DoctorCommand(tmp_path).run()

    assert not result.ok
    assert "workspace is not initialized" in result.to_text()
    assert result.to_dict()["ok"] is False


def test_gate_status_moves_from_gate_to_gray_to_core(tmp_path: Path, monkeypatch) -> None:
    _configure_release_routes(monkeypatch)
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "missing_real_model_gate"

    gate_dir = tmp_path / ".agent" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True, "recommended_actions": ["run gray"]}),
        encoding="utf-8",
    )
    result = GateStatusCommand(tmp_path).run()
    assert result.stage == "ready_for_gray_suite"
    assert result.to_dict()["rollout_state"] == "conditional"

    verification_dir = tmp_path / ".agent" / "verification"
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


def test_gate_status_blocks_release_when_current_routes_are_missing(tmp_path: Path, monkeypatch) -> None:
    _configure_release_routes(monkeypatch)
    monkeypatch.delenv("AGENT_MODEL_MEDIUM_PROVIDER", raising=False)
    gate_dir = tmp_path / ".agent" / "model"
    gate_dir.mkdir(parents=True)
    (gate_dir / "real_model_gate_report.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    verification_dir = tmp_path / ".agent" / "verification"
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
    assert "AGENT_MODEL_MEDIUM_PROVIDER" in payload["route_environment"]["missing_required"]


def _configure_release_routes(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "glm-4.7")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.setenv("AGENT_MODEL_STRONG_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_NAME", "MiniMax-M2.7")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "minimax-key")
