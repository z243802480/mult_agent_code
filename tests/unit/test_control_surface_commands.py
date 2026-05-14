import json
from pathlib import Path

from agent_runtime.commands.doctor_command import DoctorCommand
from agent_runtime.commands.gate_status_command import GateStatusCommand
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.status_command import StatusCommand


def test_status_reports_uninitialized_workspace(tmp_path: Path) -> None:
    result = StatusCommand(tmp_path).run()

    assert result.initialized is False
    assert "Next: agent init" in result.to_text()
    assert result.to_dict() == {
        "root": str(tmp_path.resolve()),
        "initialized": False,
        "current_session_id": None,
        "current_context": {},
        "recent_sessions": [],
    }


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
    assert any(check["name"] == "model_strong" for check in payload["checks"])


def test_doctor_fails_for_missing_workspace_guidance(tmp_path: Path) -> None:
    result = DoctorCommand(tmp_path).run()

    assert not result.ok
    assert "workspace is not initialized" in result.to_text()
    assert result.to_dict()["ok"] is False


def test_gate_status_moves_from_gate_to_gray_to_core(tmp_path: Path) -> None:
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
    assert payload["gray_report"]["gray_ready"] is True
