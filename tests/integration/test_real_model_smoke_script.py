from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.real_model_smoke import (
    CommandRecord,
    _accept_budget_paused_success,
    is_transient_provider_failure,
    pending_decision_ids,
    recovery_option_id,
)


def test_real_model_smoke_script_validates_offline_flow_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_smoke.py",
            "--root",
            str(workspace),
            "--allow-fake",
            "--goal",
            "create offline artifact",
            "--expected-file",
            "offline_artifact.txt",
            "--expected-text",
            "offline verification artifact",
            "--summary-json",
            str(summary_path),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Real model smoke passed" in completed.stdout
    assert (workspace / "offline_artifact.txt").exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_id"].startswith("run-")
    assert Path(summary["final_report"]).exists()
    assert summary["duration_seconds"] >= 0
    assert summary["diagnostics"]["run_status"] == "completed"
    assert summary["diagnostics"]["review_status"] == "pass"
    assert summary["diagnostics"]["model_calls"] > 0
    assert summary["diagnostics"]["tool_calls"] > 0
    assert [command["name"] for command in summary["commands"]] == [
        "init",
        "model-check",
        "run",
    ]


def test_real_model_smoke_script_rejects_fake_provider_by_default(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_smoke.py",
            "--root",
            str(tmp_path / "workspace"),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Use --allow-fake only for script tests" in completed.stderr


def test_real_model_smoke_finds_pending_decisions_for_recovery(tmp_path: Path) -> None:
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "decisions.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"decision_id": "decision-0001", "status": "pending"}),
                json.dumps({"decision_id": "decision-0002", "status": "resolved"}),
                json.dumps({"decision_id": "decision-0003", "status": "pending"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert pending_decision_ids(tmp_path, "run-1") == ["decision-0001", "decision-0003"]


def test_real_model_smoke_continues_budget_guard_during_bounded_recovery() -> None:
    decision = {
        "decision_id": "decision-0001",
        "metadata": {"kind": "budget_guard"},
        "options": [
            {"option_id": "continue_once"},
            {"option_id": "stop_and_review"},
        ],
    }

    assert recovery_option_id(decision) == "continue_once"


def test_real_model_smoke_defaults_non_budget_recovery_decisions() -> None:
    decision = {
        "decision_id": "decision-0001",
        "metadata": {"kind": "runtime_request"},
        "options": [
            {"option_id": "review_contract"},
            {"option_id": "reject_request"},
        ],
    }

    assert recovery_option_id(decision) is None


def test_real_model_smoke_approves_one_time_policy_recovery() -> None:
    decision = {
        "decision_id": "decision-0001",
        "metadata": {"kind": "execution_policy_approval"},
        "options": [
            {"option_id": "approve_once"},
            {"option_id": "skip"},
        ],
    }

    assert recovery_option_id(decision) == "approve_once"


def test_real_model_smoke_accepts_review_pass_with_pending_budget_guard(tmp_path: Path) -> None:
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "decisions.jsonl").write_text(
        json.dumps(
            {
                "decision_id": "decision-0001",
                "status": "pending",
                "metadata": {"kind": "budget_guard"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert _accept_budget_paused_success(
        run_dir,
        {"run_id": "run-1", "status": "paused"},
        {"overall": {"status": "pass"}},
    )


def test_real_model_gate_runs_offline_when_explicitly_allowed(tmp_path: Path) -> None:
    workspace = tmp_path / "gate-workspace"
    summary_path = tmp_path / "gate-summary.json"
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["AGENT_MODEL_STRONG_PROVIDER"] = "fake"
    env["AGENT_MODEL_MEDIUM_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_gate.py",
            "--root",
            str(workspace),
            "--summary-json",
            str(summary_path),
            "--allow-fake",
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Real model gate passed" in completed.stdout
    report = json.loads(summary_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["checks"]["strong_model_check"] is True
    assert report["checks"]["medium_model_check"] is True
    assert report["checks"]["smoke"] is True
    assert report["checks"]["strong_route_used"] is True
    assert report["checks"]["medium_route_used"] is True
    assert report["model_call_summary"]["total_model_calls"] > 0
    assert report["routes"]["strong"]["provider"] == "fake"
    assert report["routes"]["medium"]["provider"] == "fake"


def test_real_model_smoke_treats_remote_close_as_transient() -> None:
    record = CommandRecord(
        name="run",
        command=["asteria", "/run"],
        returncode=1,
        stdout="",
        stderr="Remote end closed connection without response",
    )

    assert is_transient_provider_failure(record)


def test_real_model_gate_requires_strong_and_medium_routes(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("AGENT_MODEL_STRONG_PROVIDER", None)
    env.pop("AGENT_MODEL_MEDIUM_PROVIDER", None)
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_gate.py",
            "--root",
            str(tmp_path / "gate-workspace"),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "AGENT_MODEL_STRONG_PROVIDER is required" in completed.stderr
