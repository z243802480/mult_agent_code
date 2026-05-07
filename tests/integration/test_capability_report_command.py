from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.commands.capability_report_command import CapabilityReportCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


def test_capability_report_summarizes_acceptance_and_execution_evidence(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    agent_dir = tmp_path / ".agent"
    acceptance_dir = agent_dir / "acceptance"
    run_dir = agent_dir / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    acceptance_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "run_id": "run-1",
                "goal_id": "goal-1",
                "status": "blocked",
                "started_at": "2026-05-07T10:00:00+08:00",
                "ended_at": None,
                "entry_command": "agent /run",
                "current_phase": "EXECUTE",
                "workspace": {"mode": "single_workspace", "path": "."},
                "summary": "blocked",
            }
        ),
        encoding="utf-8",
    )
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": [],
        "root": str(tmp_path),
        "ok": False,
        "returncode": 1,
        "created_at": "2026-05-07T10:00:00+08:00",
        "summary_json": str(acceptance_dir / "latest_summary.json"),
        "scenario_metadata": [
            {
                "scenario": "multi_file_todo_cli",
                "capability": "multi_file_change",
                "tier": "core",
                "kind": "run",
            }
        ],
        "aggregate": {"total": 1, "passed": 0, "failed": 1},
        "trend_warnings": [],
        "scenarios": [
            {
                "scenario": "multi_file_todo_cli",
                "capability": "multi_file_change",
                "tier": "core",
                "ok": False,
                "workspace": None,
                "failure_summary": "verification failed",
                "stdout_tail": "",
                "stderr_tail": "",
                "summary": {},
            }
        ],
    }
    jsonl.append(acceptance_dir / "history.jsonl", report)
    store.write(acceptance_dir / "acceptance_report.json", report, "acceptance_report")
    jsonl.append(
        run_dir / "task_execution_evidence.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "task-execution-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "status": "blocked",
            "summary": "verification command failed",
            "failure_type": "verification_failed",
            "task": {},
            "action": {},
            "candidate": {},
            "contract_check": {},
            "tool_results": [],
            "verification_results": [],
            "created_at": "2026-05-07T10:01:00+08:00",
        },
        "task_execution_evidence",
    )

    result = CapabilityReportCommand(tmp_path).run()

    assert result.acceptance_runs == 1
    assert result.latest_acceptance["release_readiness"] == "blocked"
    assert result.capability_summary["multi_file_change"]["failed"] == 1
    assert result.failure_types["verification_failed"] == 1
    assert "verification command failed" in result.common_blockers
    assert "Capability report" in result.to_text()
