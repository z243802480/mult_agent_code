from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agent_runtime.commands.acceptance_command import (
    AcceptanceCommand,
    AcceptanceFailurePromoter,
    AcceptanceResult,
)
from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.plan_command import PlanCommand
from agent_runtime.models.fake import FakeModelClient
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
    history_path = tmp_path / "acceptance" / ".agent" / "acceptance" / "history.jsonl"
    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(history) == 1
    assert history[0]["suite"] == "offline"
    assert history[0]["trend"]["previous"] is None


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
    assert "Failure evidence:" in task["description"]
    assert str(tmp_path / "summary.json") in task["description"]
    assert (
        "python -m agent_runtime /acceptance --suite core --scenario markdown_kb"
        in task["description"]
    )
    assert (
        "python scripts/real_model_acceptance.py --suite core --scenario markdown_kb"
        in task["description"]
    )
    assert "real_model_smoke_transcript.json" in task["description"]
    assert "markdown_kb.py" in task["description"]
    assert "reproduce with:" in task["notes"]
    assert "The reproduction command succeeds" in task["acceptance"][1]
    assert task["expected_artifacts"] == [".agent/acceptance/failures/markdown_kb.json"]
    evidence_path = tmp_path / task["expected_artifacts"][0]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["scenario"] == "markdown_kb"
    assert evidence["suite"] == "core"
    assert evidence["promoted_task_id"] == "task-0002"
    assert evidence["failure_summary"] == "expected output file was not created"
    assert evidence["transcript"].endswith("real_model_smoke_transcript.json")
    assert evidence["expected_file"].endswith("markdown_kb.py")
    assert evidence["reproduce"]["cli"] == (
        "python -m agent_runtime /acceptance --suite core --scenario markdown_kb"
    )
    validator.validate("acceptance_failure_evidence", evidence)
    backlog = json.loads(
        (tmp_path / ".agent" / "tasks" / "backlog.json").read_text(encoding="utf-8")
    )
    assert backlog["tasks"][1]["task_id"] == "task-0002"
    updated_run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert updated_run["status"] == "running"
    memory_path = tmp_path / ".agent" / "memory" / "failures.jsonl"
    memories = [
        json.loads(line)
        for line in memory_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(memories) == 1
    assert memories[0]["type"] == "failure_lesson"
    assert memories[0]["source"]["scenario"] == "markdown_kb"
    assert memories[0]["source"]["task_id"] == "task-0002"
    assert memories[0]["source"]["evidence"] == str(evidence_path)
    assert (
        "python -m agent_runtime /acceptance --suite core --scenario markdown_kb"
        in memories[0]["content"]
    )
    validator.validate("memory_entry", memories[0])


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


def test_acceptance_result_prints_promoted_rerun_text(tmp_path: Path) -> None:
    result = AcceptanceResult(
        suite="core",
        scenarios=["markdown_kb"],
        root=tmp_path,
        ok=True,
        returncode=0,
        stdout="",
        stderr="",
        promoted_tasks=["task-0002"],
        repair_run_id="run-1",
        rerun_summary_json=tmp_path / "rerun.json",
        rerun_ok=True,
        closed_failures=["markdown_kb"],
        remaining_failures=[],
    )

    text = result.to_text()

    assert "Promoted failure rerun:" in text
    assert "Status: pass" in text
    assert "Repair run: run-1" in text
    assert "Closed failures: markdown_kb" in text


def test_acceptance_failure_can_be_promoted_and_run_in_current_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "seed current session", model_client=FakeModelClient()).run()
    original_run = subprocess.run

    def fake_acceptance_run(command, *args, **kwargs):
        command_text = " ".join(str(item) for item in command)
        if "real_model_acceptance.py" not in command_text:
            return original_run(command, *args, **kwargs)
        summary_path = Path(command[command.index("--summary-json") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "root": str(tmp_path),
                    "scenarios": [
                        {
                            "scenario": "markdown_kb",
                            "ok": False,
                            "workspace": str(tmp_path / "markdown_kb"),
                            "summary": {
                                "transcript": str(
                                    tmp_path / "markdown_kb" / "real_model_smoke_transcript.json"
                                ),
                                "expected_file": str(tmp_path / "markdown_kb" / "markdown_kb.py"),
                            },
                            "stdout": "",
                            "stderr": "Expected output file was not created",
                        }
                    ],
                    "error": "Scenario(s) failed: markdown_kb",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, "", "Scenario(s) failed: markdown_kb")

    monkeypatch.setattr(subprocess, "run", fake_acceptance_run)

    result = AcceptanceCommand(
        tmp_path,
        suite="core",
        scenarios=["markdown_kb"],
        promote_failures=True,
        run_promoted=True,
        promoted_run_max_iterations=1,
    ).run()

    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    promoted_task = next(
        task
        for task in task_plan["tasks"]
        if task["title"] == "Repair acceptance scenario: markdown_kb"
    )

    assert not result.ok
    assert result.promoted_tasks == [promoted_task["task_id"]]
    assert result.promoted_run_text is not None
    assert "Run:" in result.promoted_run_text
    assert promoted_task["status"] == "done"
    assert (run_dir / "final_report.md").exists()
    assert (tmp_path / "offline_artifact.txt").exists()
    memory_path = tmp_path / ".agent" / "memory" / "failures.jsonl"
    memories = [
        json.loads(line)
        for line in memory_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert memories[0]["type"] == "failure_lesson"
    assert memories[0]["source"]["task_id"] == promoted_task["task_id"]


def test_acceptance_failure_can_be_rerun_after_promoted_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    InitCommand(tmp_path).run()
    plan = PlanCommand(tmp_path, "seed current session", model_client=FakeModelClient()).run()
    original_run = subprocess.run
    acceptance_calls = 0

    def fake_acceptance_run(command, *args, **kwargs):
        nonlocal acceptance_calls
        command_text = " ".join(str(item) for item in command)
        if "real_model_acceptance.py" not in command_text:
            return original_run(command, *args, **kwargs)
        acceptance_calls += 1
        summary_path = Path(command[command.index("--summary-json") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        scenario_summary = {
            "scenario": "markdown_kb",
            "workspace": str(tmp_path / "markdown_kb"),
            "summary": {
                "transcript": str(tmp_path / "markdown_kb" / "real_model_smoke_transcript.json"),
                "expected_file": str(tmp_path / "markdown_kb" / "markdown_kb.py"),
            },
            "stdout": "",
        }
        if acceptance_calls == 1:
            scenario_summary.update(
                {
                    "ok": False,
                    "stderr": "Expected output file was not created",
                }
            )
            summary = {
                "ok": False,
                "root": str(tmp_path),
                "scenarios": [scenario_summary],
                "error": "Scenario(s) failed: markdown_kb",
            }
            returncode = 1
            stderr = "Scenario(s) failed: markdown_kb"
        else:
            scenario_summary.update({"ok": True, "stderr": ""})
            summary = {
                "ok": True,
                "root": str(tmp_path),
                "scenarios": [scenario_summary],
            }
            returncode = 0
            stderr = ""
        summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode, "", stderr)

    monkeypatch.setattr(subprocess, "run", fake_acceptance_run)

    result = AcceptanceCommand(
        tmp_path,
        suite="core",
        scenarios=["markdown_kb"],
        promote_failures=True,
        rerun_promoted=True,
        promoted_run_max_iterations=1,
    ).run()

    run_dir = tmp_path / ".agent" / "runs" / plan.run_id
    report = json.loads(
        (tmp_path / ".agent" / "acceptance" / "acceptance_report.json").read_text(encoding="utf-8")
    )

    assert acceptance_calls == 2
    assert result.ok
    assert result.returncode == 0
    assert result.rerun_ok is True
    assert result.closed_failures == ["markdown_kb"]
    assert result.remaining_failures == []
    assert result.promoted_run_text is not None
    assert (run_dir / "final_report.md").exists()
    assert report["ok"] is False
    assert report["repair_closure"]["repair_run_id"] == plan.run_id
    assert report["repair_closure"]["rerun_ok"] is True
    assert report["repair_closure"]["closed_failures"] == ["markdown_kb"]
    assert report["repair_closure"]["remaining_failures"] == []
