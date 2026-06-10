from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from asteria_runtime import real_model_smoke as smoke_runtime

from scripts.real_model_smoke import (
    CommandRecord,
    SmokeResult,
    _accept_budget_paused_success,
    is_transient_provider_failure,
    validate_artifacts,
)
from asteria_runtime.real_model_gate import (
    GateCommand,
    GateResult,
    model_check_ok,
    reconcile_model_checks_from_smoke,
)


def test_real_model_smoke_detects_current_source_checkout() -> None:
    source_root = smoke_runtime.source_checkout_root()

    assert source_root == Path.cwd() / "src"
    assert smoke_runtime.merge_pythonpath(str(source_root), "existing") == (
        f"{source_root}{os.pathsep}existing"
    )

pytestmark = [pytest.mark.real_provider, pytest.mark.real_provider_smoke]


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


def test_real_model_smoke_observes_blocked_run_without_recovery_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-1", "status": "blocked"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "goal_spec.json").write_text("{}\n", encoding="utf-8")
    result = smoke_runtime.SmokeResult(
        workspace=workspace,
        run_id=None,
        expected_file=workspace / "artifact.txt",
        final_report=None,
        transcript=workspace / "transcript.json",
    )
    command_names: list[str] = []

    def record_command(*args: object, name: str, **kwargs: object) -> smoke_runtime.CommandRecord:
        del args, kwargs
        command_names.append(name)
        return smoke_runtime.CommandRecord(name=name, command=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(smoke_runtime, "run_command", record_command)
    monkeypatch.setattr(
        smoke_runtime,
        "run_agent_run_with_retries",
        lambda args, active_result: smoke_runtime.CommandRecord(
            name="run",
            command=[],
            returncode=0,
            stdout="Status: blocked",
            stderr="",
        ),
    )
    monkeypatch.setattr(smoke_runtime, "current_run_id", lambda active_workspace: "run-1")
    monkeypatch.setattr(
        smoke_runtime,
        "validate_artifacts",
        lambda *args, **kwargs: (_ for _ in ()).throw(smoke_runtime.SmokeFailure("blocked")),
    )

    with pytest.raises(smoke_runtime.SmokeFailure, match="blocked"):
        smoke_runtime.run_smoke(
            argparse.Namespace(
                python=sys.executable,
                goal="create artifact",
                max_iterations=1,
                max_tasks_per_iteration=1,
                no_research=True,
                run_attempts=1,
                expected_text="artifact",
            ),
            result,
        )

    assert command_names == ["init", "model-check"]
    assert not (run_dir / "agent_loop_decisions.jsonl").exists()


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


def test_real_model_smoke_rejects_missing_runtime_final_report(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    expected_file = workspace / "buggy_math.py"
    expected_file.parent.mkdir(parents=True, exist_ok=True)
    expected_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-1", "status": "running"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "goal_spec.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "task_plan.json").write_text(
        json.dumps({"tasks": [{"task_id": "task-1", "status": "done"}]}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"type": "run_completed"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "tool_calls.jsonl").write_text(json.dumps({"id": "tool-1"}) + "\n", encoding="utf-8")
    (run_dir / "model_calls.jsonl").write_text(
        json.dumps({"id": "model-1"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "cost_report.json").write_text(
        json.dumps({"model_calls": 1, "tool_calls": 1, "status": "within_budget"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "task_execution_evidence.jsonl").write_text(
        json.dumps(
            {
                "status": "done",
                "verification_results": [{"ok": True}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = SmokeResult(
        workspace=workspace,
        run_id="run-1",
        expected_file=expected_file,
        final_report=None,
        transcript=workspace / "real_model_smoke_transcript.json",
    )

    with pytest.raises(smoke_runtime.SmokeFailure, match="final_report.md"):
        validate_artifacts(
            workspace,
            "run-1",
            result=result,
            expected_file=expected_file,
            expected_text="return a + b",
        )


def test_real_model_smoke_rejects_verified_artifact_with_unfinished_tasks(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    expected_file = workspace / "shapes.py"
    expected_file.parent.mkdir(parents=True, exist_ok=True)
    expected_file.write_text("class Shape:\n    pass\n", encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-1", "status": "paused"}) + "\n",
        encoding="utf-8",
    )
    for name in ("goal_spec.json", "eval_report.json"):
        (run_dir / name).write_text(json.dumps({"overall": {"status": "fail"}}) + "\n", encoding="utf-8")
    (run_dir / "review_report.md").write_text("# Review\n", encoding="utf-8")
    (run_dir / "final_report.md").write_text("# Final\n", encoding="utf-8")
    (run_dir / "task_plan.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"task_id": "task-1", "status": "done"},
                    {"task_id": "task-2", "status": "blocked"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"type": "task_completed"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "tool_calls.jsonl").write_text(json.dumps({"id": "tool-1"}) + "\n", encoding="utf-8")
    (run_dir / "model_calls.jsonl").write_text(
        json.dumps({"id": "model-1"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "cost_report.json").write_text(
        json.dumps({"model_calls": 1, "tool_calls": 1, "status": "within_budget"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "task_execution_evidence.jsonl").write_text(
        json.dumps(
            {
                "status": "done",
                "candidate": {"changed_files": ["shapes.py"], "promoted_files": ["shapes.py"]},
                "verification_results": [{"ok": True}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = SmokeResult(
        workspace=workspace,
        run_id="run-1",
        expected_file=expected_file,
        final_report=None,
        transcript=workspace / "real_model_smoke_transcript.json",
    )

    with pytest.raises(smoke_runtime.SmokeFailure, match="status is 'paused'"):
        validate_artifacts(
            workspace,
            "run-1",
            result=result,
            expected_file=expected_file,
            expected_text="class Shape",
        )


def test_real_model_smoke_does_not_synthesize_missing_reports(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    expected_file = workspace / "hello_runtime.txt"
    expected_file.parent.mkdir(parents=True, exist_ok=True)
    expected_file.write_text("real model smoke ok\n", encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": "run-1", "status": "running"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "goal_spec.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "task_plan.json").write_text(
        json.dumps({"tasks": [{"task_id": "task-1", "status": "done"}]}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        json.dumps({"type": "task_completed"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "tool_calls.jsonl").write_text(json.dumps({"id": "tool-1"}) + "\n", encoding="utf-8")
    (run_dir / "model_calls.jsonl").write_text(
        json.dumps({"id": "model-1"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "cost_report.json").write_text(
        json.dumps({"model_calls": 1, "tool_calls": 1, "status": "within_budget"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "task_execution_evidence.jsonl").write_text(
        json.dumps(
            {
                "status": "done",
                "candidate": {
                    "changed_files": ["hello_runtime.txt"],
                    "promoted_files": ["hello_runtime.txt"],
                },
                "verification_results": [{"ok": True}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = SmokeResult(
        workspace=workspace,
        run_id="run-1",
        expected_file=expected_file,
        final_report=None,
        transcript=workspace / "real_model_smoke_transcript.json",
    )

    with pytest.raises(smoke_runtime.SmokeFailure, match="final_report.md"):
        validate_artifacts(
            workspace,
            "run-1",
            result=result,
            expected_file=expected_file,
            expected_text="real model smoke ok",
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


def test_real_model_smoke_treats_stream_deadline_as_transient() -> None:
    record = CommandRecord(
        name="run",
        command=["asteria", "/run"],
        returncode=1,
        stdout="",
        stderr="OpenAICompatibleProviderError: stream deadline exceeded",
    )

    assert is_transient_provider_failure(record)


def test_real_model_gate_requires_model_check_call_ok() -> None:
    assert model_check_ok(
        GateCommand(
            name="model-check",
            command=["python"],
            returncode=0,
            stdout="Config: ok\nCall: ok\n",
            stderr="",
        )
    )
    assert not model_check_ok(
        GateCommand(
            name="model-check",
            command=["python"],
            returncode=0,
            stdout="Config: ok\nCall: skipped/failed\n",
            stderr="",
        )
    )


def test_real_model_gate_reconciles_model_check_timeout_from_smoke_evidence() -> None:
    result = GateResult(workspace=Path("unused-workspace"))
    result.checks["strong_model_check"] = False
    result.checks["medium_model_check"] = True
    result.model_call_summary = {}

    reconcile_model_checks_from_smoke(
        result,
        [
            {
                "model_tier": "strong",
                "status": "success",
                "agent_role_contract": {"role": "ReviewAgent"},
                "deadline_ms": 90000,
                "streaming": {"mode": "streaming", "deadline_ms": 90000},
            }
        ],
    )

    assert result.checks["strong_model_check"] is True
    assert result.model_call_summary["model_checks_reconciled_by_smoke"] == ["strong"]


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
