from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from asteria_runtime.acceptance.runtime_os_catalog import (
    runtime_os_capability_names,
    runtime_os_scenario_names,
)
from asteria_runtime.commands.acceptance_command import (
    AcceptanceCommand,
    AcceptanceFailurePromoter,
    AcceptanceResult,
)
from asteria_runtime.commands.acceptance_gate_command import AcceptanceGateCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.plan_command import PlanCommand
from asteria_runtime.models.fake import FakeModelClient
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_acceptance_command_runs_offline_suite_with_fake_provider(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")
    env["AGENT_MODEL_PROVIDER"] = "fake"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "asteria_runtime",
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
    report_path = tmp_path / "acceptance" / ".asteria" / "acceptance" / "acceptance_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["summary_json"] == str(summary_path)
    assert report["scenarios"][0]["scenario"] == "offline_artifact"
    history_path = tmp_path / "acceptance" / ".asteria" / "acceptance" / "history.jsonl"
    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(history) == 1
    assert history[0]["suite"] == "offline"
    assert history[0]["trend"]["previous"] is None


def test_acceptance_runtime_os_scenarios_feed_release_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # RA7: the runtime-OS acceptance scenarios validate the FSM runtime-management mechanism
    # (probes, parallel-readonly / disjoint-write fanout) via RuntimeAcceptanceClient, which speaks
    # the FSM ExecutionAction contract. AcceptanceCommand runs them in a spawned subprocess (out of
    # reach of the in-process conftest pin), so we pin the legacy FSM path fleet-wide with the
    # rollout override env — it propagates through os.environ.copy() into that subprocess. RA7b
    # migrates or retires these scenarios alongside the FSM deletion.
    monkeypatch.setenv("ASTERIA_MODEL_DRIVEN_TURN", "0")
    root = tmp_path / "runtime-os"
    scenarios = runtime_os_scenario_names()

    result = AcceptanceCommand(
        root,
        suite="core",
        scenarios=scenarios,
        allow_fake=True,
    ).run()
    gate = AcceptanceGateCommand(
        root,
        suite="core",
        min_scenarios=len(scenarios),
        min_capabilities=len(scenarios),
        require_tiers=["core"],
    ).run()

    assert result.ok
    assert gate.ok
    assert gate.runtime_os["status"] == "pass"
    assert gate.runtime_os["covered_capabilities"] == runtime_os_capability_names()


def test_acceptance_failure_promoter_adds_ready_task_to_current_session(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run_store.set_current_session(run["run_id"], "test setup")
    run_dir = tmp_path / ".asteria" / "runs" / run["run_id"]
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

    promoter = AcceptanceFailurePromoter(tmp_path, validator)
    promoted = promoter.promote(report)
    promoter_again = AcceptanceFailurePromoter(tmp_path, validator)
    promoted_again = promoter_again.promote(report)

    assert promoted == ["task-0002"]
    assert promoted_again == []
    assert promoter_again.repair_task_ids == ["task-0002"]
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
        "python -m asteria_runtime /acceptance --suite core --scenario markdown_kb"
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
    assert task["expected_artifacts"] == [".asteria/acceptance/failures/markdown_kb.json"]
    evidence_path = tmp_path / task["expected_artifacts"][0]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["scenario"] == "markdown_kb"
    assert evidence["suite"] == "core"
    assert evidence["promoted_task_id"] == "task-0002"
    assert evidence["failure_summary"] == "expected output file was not created"
    assert evidence["transcript"].endswith("real_model_smoke_transcript.json")
    assert evidence["expected_file"].endswith("markdown_kb.py")
    assert evidence["reproduce"]["cli"] == (
        "python -m asteria_runtime /acceptance --suite core --scenario markdown_kb"
    )
    validator.validate("acceptance_failure_evidence", evidence)
    backlog = json.loads(
        (tmp_path / ".asteria" / "tasks" / "backlog.json").read_text(encoding="utf-8")
    )
    assert backlog["tasks"][1]["task_id"] == "task-0002"
    updated_run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert updated_run["status"] == "running"
    memory_path = tmp_path / ".asteria" / "memory" / "failures.jsonl"
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
        "python -m asteria_runtime /acceptance --suite core --scenario markdown_kb"
        in memories[0]["content"]
    )
    validator.validate("memory_entry", memories[0])


def test_acceptance_failure_promoter_creates_repair_session_without_current_session(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": ["password_cli"],
        "root": str(tmp_path),
        "ok": False,
        "returncode": 1,
        "created_at": "2026-05-07T00:00:00+08:00",
        "summary_json": str(tmp_path / "summary.json"),
        "scenarios": [
            {
                "scenario": "password_cli",
                "ok": False,
                "workspace": str(tmp_path / "password_cli"),
                "failure_summary": "Run still has pending decisions: decision-0001",
                "failure_attribution": {
                    "category": "pending_decision",
                    "retryable": False,
                    "confidence": 0.9,
                    "signals": ["pending decisions"],
                },
                "stdout_tail": "",
                "stderr_tail": "Run still has pending decisions: decision-0001",
                "summary": None,
            }
        ],
    }

    promoted = AcceptanceFailurePromoter(tmp_path, validator).promote(report)

    run_store = RunStore(tmp_path / ".asteria", validator)
    run_id = run_store.current_session_id()
    assert promoted == ["task-0001"]
    assert run_id is not None
    run_dir = tmp_path / ".asteria" / "runs" / run_id
    assert (run_dir / "goal_spec.json").exists()
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert task_plan["tasks"][0]["title"] == "Repair acceptance scenario: password_cli"
    evidence = json.loads(
        (tmp_path / ".asteria" / "acceptance" / "failures" / "password_cli.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["failure_attribution"]["category"] == "pending_decision"
    validator.validate("acceptance_failure_evidence", evidence)


def test_acceptance_failure_promoter_does_not_reuse_paused_repair_session(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    run_store = RunStore(tmp_path / ".asteria", validator)
    stale = run_store.create_run("old acceptance repair", goal_id="goal-acceptance-repair")
    stale_dir = run_store.run_dir(stale["run_id"])
    store.write(
        stale_dir / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "tasks": [
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "title": "Old repair task",
                    "description": "Stale task from an earlier acceptance run",
                    "status": "ready",
                    "priority": "medium",
                    "role": "CoderAgent",
                    "depends_on": [],
                    "acceptance": ["Old repair is complete"],
                    "allowed_tools": ["read_file"],
                    "expected_artifacts": [],
                }
            ],
        },
        "task_board",
    )
    stale["status"] = "paused"
    run_store.update_run(stale)
    run_store.set_current_session(stale["run_id"], "test setup")
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": ["safe_file_renamer"],
        "root": str(tmp_path),
        "ok": False,
        "returncode": 1,
        "created_at": "2026-05-07T00:00:00+08:00",
        "summary_json": str(tmp_path / "summary.json"),
        "scenarios": [
            {
                "scenario": "safe_file_renamer",
                "ok": False,
                "workspace": str(tmp_path / "safe_file_renamer"),
                "failure_summary": "verification failed",
                "stdout_tail": "",
                "stderr_tail": "verification failed",
                "summary": {},
            }
        ],
    }

    promoted = AcceptanceFailurePromoter(tmp_path, validator).promote(report)

    new_run_id = run_store.current_session_id()
    assert promoted == ["task-0001"]
    assert new_run_id is not None
    assert new_run_id != stale["run_id"]
    stale_plan = json.loads((stale_dir / "task_plan.json").read_text(encoding="utf-8"))
    assert len(stale_plan["tasks"]) == 1
    new_plan = json.loads(
        (tmp_path / ".asteria" / "runs" / new_run_id / "task_plan.json").read_text(encoding="utf-8")
    )
    assert new_plan["tasks"][0]["title"] == "Repair acceptance scenario: safe_file_renamer"


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


def test_acceptance_result_prints_trend_warnings(tmp_path: Path) -> None:
    result = AcceptanceResult(
        suite="core",
        scenarios=[],
        root=tmp_path,
        ok=False,
        returncode=1,
        stdout="",
        stderr="",
        trend_warnings=["model calls increased by 6 (threshold 5)"],
    )

    text = result.to_text()

    assert "Trend warnings:" in text
    assert "model calls increased by 6" in text


def test_acceptance_command_timeout_accounts_for_suite_defaults(tmp_path: Path) -> None:
    command = AcceptanceCommand(
        tmp_path,
        suite="core",
        scenario_timeout_seconds=600,
    )

    assert command._command_timeout_seconds([]) == 3660  # noqa: SLF001
    assert command._command_timeout_seconds(["markdown_kb"]) == 660  # noqa: SLF001


def test_acceptance_command_failed_only_uses_latest_failed_scenarios(
    tmp_path: Path,
    monkeypatch,
) -> None:
    InitCommand(tmp_path).run()
    report_path = tmp_path / ".asteria" / "acceptance" / "acceptance_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "suite": "core",
                "requested_scenarios": [],
                "root": str(tmp_path),
                "ok": False,
                "returncode": 1,
                "created_at": "2026-05-12T00:00:00+08:00",
                "summary_json": str(tmp_path / "summary.json"),
                "scenarios": [
                    {
                        "scenario": "password_cli",
                        "ok": True,
                        "workspace": None,
                        "failure_summary": "",
                    },
                    {
                        "scenario": "multi_file_todo_cli",
                        "ok": False,
                        "workspace": None,
                        "failure_summary": "failed",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    captured: dict[str, list[str]] = {}

    def fake_acceptance_run(command, *args, **kwargs):
        del args, kwargs
        captured["command"] = [str(item) for item in command]
        summary_path = Path(command[command.index("--summary-json") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "root": str(tmp_path),
                    "suite": "core",
                    "scenarios": [
                        {
                            "scenario": "multi_file_todo_cli",
                            "ok": True,
                            "workspace": str(tmp_path / "isolated" / "multi_file_todo_cli"),
                            "summary": {},
                            "stdout": "",
                            "stderr": "",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_acceptance_run)

    result = AcceptanceCommand(tmp_path, suite="core", failed_only=True).run()

    assert result.ok
    assert result.scenarios == ["multi_file_todo_cli"]
    assert captured["command"].count("--scenario") == 1
    assert "multi_file_todo_cli" in captured["command"]
    workspace_root = Path(captured["command"][captured["command"].index("--root") + 1])
    assert workspace_root.is_relative_to(tmp_path / ".asteria" / "acceptance" / "workspaces")


def test_acceptance_command_uses_module_runner_when_repo_script_is_missing(
    tmp_path: Path, monkeypatch
) -> None:
    command = AcceptanceCommand(tmp_path, suite="core", allow_fake=True)
    monkeypatch.setattr(command, "_repo_root", lambda: tmp_path / "installed-site-packages")

    runner = command._acceptance_runner_command()  # noqa: SLF001

    assert runner == [sys.executable, "-m", "asteria_runtime.real_model_acceptance"]


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
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_CHEAP_PROVIDER", "fake")
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

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
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
    assert promoted_task["status"] in {"done", "blocked"}
    if promoted_task["status"] == "blocked":
        assert "decision" in (result.promoted_run_text or "").lower()
    assert (run_dir / "final_report.md").exists()
    assert (tmp_path / "offline_artifact.txt").exists()
    memory_path = tmp_path / ".asteria" / "memory" / "failures.jsonl"
    memories = [
        json.loads(line)
        for line in memory_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert memories[0]["type"] == "failure_lesson"
    assert memories[0]["source"]["task_id"] == promoted_task["task_id"]


def test_acceptance_command_can_fail_on_trend_warning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_run = subprocess.run

    def fake_acceptance_run(command, *args, **kwargs):
        command_text = " ".join(str(item) for item in command)
        if "real_model_acceptance.py" not in command_text:
            return original_run(command, *args, **kwargs)
        summary_path = Path(command[command.index("--summary-json") + 1])
        history_path = Path(command[command.index("--history-jsonl") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "ok": True,
            "root": str(tmp_path),
            "suite": "core",
            "created_at": "2026-05-06T12:00:00+08:00",
            "aggregate": {
                "total": 1,
                "passed": 1,
                "failed": 0,
                "model_calls": 12,
                "tool_calls": 2,
                "duration_seconds": 60,
            },
            "trend": {
                "previous": {"created_at": "2026-05-06T11:00:00+08:00"},
                "deltas": {
                    "failed": 0,
                    "duration_seconds": 0,
                    "model_calls": 6,
                    "repair_attempts": 0,
                    "context_compactions": 0,
                },
            },
            "scenarios": [
                {
                    "scenario": "password_cli",
                    "ok": True,
                    "workspace": str(tmp_path / "password_cli"),
                    "summary": {},
                    "stdout": "",
                    "stderr": "",
                }
            ],
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        history_path.write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "Real model acceptance passed", "")

    monkeypatch.setattr(subprocess, "run", fake_acceptance_run)

    result = AcceptanceCommand(
        tmp_path,
        suite="core",
        scenarios=["password_cli"],
        fail_on_trend_warning=True,
        warn_model_call_delta=5,
    ).run()

    report = json.loads(
        (tmp_path / ".asteria" / "acceptance" / "acceptance_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert not result.ok
    assert result.returncode == 1
    assert result.trend_warnings == ["model calls increased by 6 (threshold 5)"]
    assert report["ok"] is True
    assert report["trend_warnings"] == result.trend_warnings
    assert "Trend warnings:" in result.to_text()


def test_acceptance_report_records_failure_attribution_and_repair_workflow(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
                    "suite": "core",
                    "scenarios": [
                        {
                            "scenario": "password_cli",
                            "ok": False,
                            "workspace": str(tmp_path / "password_cli"),
                            "attempts": [
                                {
                                    "attempt": 1,
                                    "returncode": 1,
                                    "retryable": False,
                                    "failure_type": "scenario_failure",
                                    "stderr_tail": "Run still has pending decisions: decision-0001",
                                    "stdout_tail": "",
                                }
                            ],
                            "summary": None,
                            "stdout": "",
                            "stderr": "Run still has pending decisions: decision-0001",
                        }
                    ],
                    "aggregate": {"failed": 1},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, "", "Scenario(s) failed: password_cli")

    monkeypatch.setattr(subprocess, "run", fake_acceptance_run)

    result = AcceptanceCommand(
        tmp_path,
        suite="core",
        scenarios=["password_cli"],
        promote_failures=True,
    ).run()

    report = json.loads(
        (tmp_path / ".asteria" / "acceptance" / "acceptance_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert not result.ok
    assert result.promoted_tasks == ["task-0001"]
    assert report["scenarios"][0]["failure_attribution"]["category"] == "pending_decision"
    assert report["repair_workflow"]["status"] == "promoted"
    assert report["repair_workflow"]["promoted_scenarios"] == ["password_cli"]
    SchemaValidator(Path.cwd() / "schemas").validate("acceptance_report", report)


def test_acceptance_promotion_adds_targeted_repair_focus_for_core_capabilities(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_run = subprocess.run

    def fake_acceptance_run(command, *args, **kwargs):
        command_text = " ".join(str(item) for item in command)
        if "real_model_acceptance.py" not in command_text:
            return original_run(command, *args, **kwargs)
        summary_path = Path(command[command.index("--summary-json") + 1])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "ok": False,
            "root": str(tmp_path),
            "suite": "core",
            "scenarios": [
                {
                    "scenario": "multi_file_todo_cli",
                    "capability": "multi_file_change",
                    "tier": "core",
                    "ok": False,
                    "workspace": str(tmp_path / "multi_file_todo_cli"),
                    "summary": {
                        "expected_file": str(tmp_path / "multi_file_todo_cli" / "todo.py"),
                    },
                    "stdout": "",
                    "stderr": "ModuleNotFoundError: No module named todo_app",
                },
                {
                    "scenario": "config_driven_report",
                    "capability": "configuration_change",
                    "tier": "core",
                    "ok": False,
                    "workspace": str(tmp_path / "config_driven_report"),
                    "summary": {
                        "expected_file": str(
                            tmp_path / "config_driven_report" / "report_from_config.py"
                        ),
                    },
                    "stdout": "",
                    "stderr": "report.md was not created",
                },
            ],
            "aggregate": {"failed": 2},
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, "", "Scenario(s) failed")

    monkeypatch.setattr(subprocess, "run", fake_acceptance_run)

    result = AcceptanceCommand(
        tmp_path,
        suite="core",
        scenarios=["multi_file_todo_cli", "config_driven_report"],
        promote_failures=True,
    ).run()

    run_dir = next((tmp_path / ".asteria" / "runs").iterdir())
    task_plan = json.loads((run_dir / "task_plan.json").read_text(encoding="utf-8"))
    todo_task = next(
        task
        for task in task_plan["tasks"]
        if task["title"] == "Repair acceptance scenario: multi_file_todo_cli"
    )
    report_task = next(
        task
        for task in task_plan["tasks"]
        if task["title"] == "Repair acceptance scenario: config_driven_report"
    )
    todo_evidence = JsonStore(SchemaValidator(Path.cwd() / "schemas")).read(
        tmp_path / ".asteria" / "acceptance" / "failures" / "multi_file_todo_cli.json",
        "acceptance_failure_evidence",
    )
    report_evidence = JsonStore(SchemaValidator(Path.cwd() / "schemas")).read(
        tmp_path / ".asteria" / "acceptance" / "failures" / "config_driven_report.json",
        "acceptance_failure_evidence",
    )

    assert result.promoted_tasks == ["task-0001", "task-0002"]
    assert todo_task["expected_changed_files"] == [
        "todo.py",
        "todo_app/__init__.py",
        "todo_app/cli.py",
        "todo_app/storage.py",
    ]
    assert "cross-file imports" in todo_task["description"]
    assert "python todo.py add" in todo_task["verification_policy"]["commands"][0]
    assert report_task["expected_changed_files"] == ["report_from_config.py", "report.md"]
    assert "report_config.json as the source of truth" in report_task["description"]
    assert (
        "python report_from_config.py report_config.json"
        in (report_task["verification_policy"]["commands"][0])
    )
    assert todo_evidence["repair_focus"]["capability"] == "multi_file_change"
    assert report_evidence["repair_focus"]["capability"] == "configuration_change"


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

    run_dir = tmp_path / ".asteria" / "runs" / plan.run_id
    report = json.loads(
        (tmp_path / ".asteria" / "acceptance" / "acceptance_report.json").read_text(
            encoding="utf-8"
        )
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
