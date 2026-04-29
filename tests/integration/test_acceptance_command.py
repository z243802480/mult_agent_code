from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agent_runtime.commands.acceptance_command import AcceptanceFailurePromoter, AcceptanceResult
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


def test_acceptance_command_runs_offline_suite_with_fake_provider(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    env["AGENT_MODEL_PROVIDER"] = "fake"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_runtime",
            "/acceptance",
            "--suite",
            "offline",
            "--root",
            str(tmp_path / "acceptance"),
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

    assert "Acceptance" in completed.stdout
    assert "Status: pass" in completed.stdout
    assert "Report:" in completed.stdout
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["scenarios"][0]["scenario"] == "offline_artifact"
    report_path = tmp_path / "acceptance" / ".agent" / "acceptance" / "acceptance_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["summary_json"] == str(summary_path)
    assert report["scenarios"][0]["scenario"] == "offline_artifact"


def test_acceptance_failure_promoter_adds_ready_task_to_current_session(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    run_store = RunStore(tmp_path / ".agent", validator)
    run = run_store.create_run("test")
    run_store.set_current_session(run["run_id"], "test setup")
    run_dir = tmp_path / ".agent" / "runs" / run["run_id"]
    task_plan = {
        "schema_version": "0.1.0",
        "tasks": [
            {
                "schema_version": "0.1.0",
                "task_id": "task-0001",
                "title": "Existing task",
                "description": "Existing completed task",
                "status": "done",
                "priority": "medium",
                "role": "CoderAgent",
                "depends_on": [],
                "acceptance": ["Existing task is done"],
                "allowed_tools": ["read_file"],
                "expected_artifacts": [],
            }
        ],
    }
    store.write(run_dir / "task_plan.json", task_plan, "task_board")
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": [],
        "root": str(tmp_path),
        "ok": False,
        "returncode": 1,
        "created_at": "2026-04-29T00:00:00+08:00",
        "summary_json": str(tmp_path / "summary.json"),
        "scenarios": [
            {
                "scenario": "markdown_kb",
                "ok": False,
                "workspace": str(tmp_path / "scenario"),
                "failure_summary": "expected output file was not created",
                "stdout_tail": "",
                "stderr_tail": "missing markdown_kb.py",
                "summary": {
                    "transcript": str(tmp_path / "scenario" / "real_model_smoke_transcript.json"),
                    "expected_file": str(tmp_path / "scenario" / "markdown_kb.py"),
                },
            }
        ],
    }

    promoted = AcceptanceFailurePromoter(tmp_path, validator).promote(report)
    promoted_again = AcceptanceFailurePromoter(tmp_path, validator).promote(report)

    assert promoted == ["task-0002"]
    assert promoted_again == []
    updated = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert len(updated["tasks"]) == 2
    task = updated["tasks"][1]
    assert task["status"] == "ready"
    assert task["title"] == "Repair acceptance scenario: markdown_kb"
    assert "expected output file was not created" in task["description"]
    assert "Acceptance report:" in task["description"]
    assert str(tmp_path / "summary.json") in task["description"]
    assert "python -m agent_runtime /acceptance --suite core --scenario markdown_kb" in task["description"]
    assert "python scripts/real_model_acceptance.py --suite core --scenario markdown_kb" in task["description"]
    assert "real_model_smoke_transcript.json" in task["description"]
    assert "markdown_kb.py" in task["description"]
    assert "reproduce with:" in task["notes"]
    assert "The reproduction command succeeds" in task["acceptance"][1]
    backlog = json.loads((tmp_path / ".agent" / "tasks" / "backlog.json").read_text(encoding="utf-8"))
    assert backlog["tasks"][1]["task_id"] == "task-0002"
    updated_run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert updated_run["status"] == "running"


def test_acceptance_result_prints_promotion_error(tmp_path: Path) -> None:
    result = AcceptanceResult(
        suite="core",
        scenarios=[],
        root=tmp_path,
        ok=False,
        returncode=1,
        stdout="",
        stderr="",
        promotion_error="Cannot promote acceptance failures: no current session found.",
    )

    assert "Promotion error: Cannot promote acceptance failures" in result.to_text()


def test_acceptance_result_prints_promoted_run_text(tmp_path: Path) -> None:
    result = AcceptanceResult(
        suite="core",
        scenarios=["markdown_kb"],
        root=tmp_path,
        ok=False,
        returncode=1,
        stdout="",
        stderr="",
        promoted_tasks=["task-0002"],
        promoted_run_text="Run: run-1\nStatus: blocked",
    )

    text = result.to_text()

    assert "Promoted failure tasks: 1" in text
    assert "Promoted task run:" in text
    assert "Run: run-1" in text
