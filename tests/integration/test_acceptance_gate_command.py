from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from asteria_runtime.commands.acceptance_gate_command import AcceptanceGateCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


def test_acceptance_gate_passes_clean_report(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "scenarios": [
                scenario("file_smoke", True),
                scenario("password_cli", True),
                scenario("markdown_kb", True),
                scenario("safe_file_renamer", True),
                scenario("multi_file_todo_cli", True),
                scenario("config_driven_report", True),
            ],
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        suite="core",
        min_scenarios=6,
        require_runtime_os=False,
    ).run()

    assert result.ok
    assert result.release_status == "ready"
    assert result.passed_count == 6
    assert "Status: pass" in result.to_text()


def test_acceptance_gate_blocks_trend_warnings_by_default(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "trend_warnings": ["model calls increased by 6 (threshold 5)"],
            "scenarios": [scenario("password_cli", True)],
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        min_capabilities=1,
        require_tiers=[],
        require_runtime_os=False,
    ).run()

    assert not result.ok
    assert result.release_status == "blocked"
    assert "acceptance trend warnings are present" in result.failures
    assert "asteria /acceptance-history" in result.next_actions[0]


def test_acceptance_gate_allows_closed_repair_with_conditional_status(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": False,
            "returncode": 1,
            "scenarios": [scenario("markdown_kb", False)],
            "repair_closure": {
                "repair_run_id": "run-1",
                "rerun_summary_json": str(tmp_path / "rerun.json"),
                "rerun_ok": True,
                "closed_failures": ["markdown_kb"],
                "remaining_failures": [],
            },
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        min_capabilities=0,
        require_tiers=[],
        require_runtime_os=False,
    ).run()

    assert result.ok
    assert result.release_status == "conditional"
    assert "base acceptance failed" in result.warnings[0]


def test_acceptance_gate_counts_closed_failures_toward_capability_coverage(
    tmp_path: Path,
) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": False,
            "returncode": 1,
            "scenarios": [
                scenario("password_cli", True),
                scenario("markdown_kb", False),
                scenario("safe_file_renamer", False),
            ],
            "repair_closure": {
                "repair_run_id": "run-1",
                "rerun_summary_json": str(tmp_path / "rerun.json"),
                "rerun_ok": True,
                "closed_failures": ["markdown_kb", "safe_file_renamer"],
                "remaining_failures": [],
            },
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        suite="core",
        min_scenarios=3,
        min_capabilities=3,
        require_tiers=["core"],
        require_runtime_os=False,
    ).run()

    assert result.ok
    assert result.passed_count == 3
    assert result.release_status == "conditional"


def test_acceptance_gate_cli_exits_nonzero_for_blocked_release(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": False,
            "returncode": 1,
            "scenarios": [scenario("password_cli", False)],
        },
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "asteria_runtime",
            "/acceptance-gate",
            "--root",
            str(tmp_path),
            "--report",
            str(report_path),
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Release status: blocked" in completed.stdout
    assert "repair closure did not prove recovery" in completed.stdout


def test_acceptance_gate_blocks_insufficient_capability_coverage(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "scenarios": [scenario("file_smoke", True), scenario("password_cli", True)],
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        suite="core",
        min_scenarios=2,
        require_runtime_os=False,
    ).run()

    assert not result.ok
    assert any("capability coverage" in failure for failure in result.failures)
    assert any("broader acceptance suite" in action for action in result.next_actions)


def test_acceptance_gate_backfills_legacy_scenario_capabilities(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "scenario_metadata": [],
            "scenarios": [
                legacy_scenario("file_smoke", True),
                legacy_scenario("password_cli", True),
                legacy_scenario("markdown_kb", True),
                legacy_scenario("safe_file_renamer", True),
            ],
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        suite="core",
        min_scenarios=4,
        min_capabilities=4,
        require_runtime_os=False,
    ).run()

    assert result.ok


def test_acceptance_gate_requires_runtime_os_evidence_for_core(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "scenarios": [scenario("password_cli", True)],
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        suite="core",
        min_scenarios=1,
        min_capabilities=1,
        require_tiers=["core"],
    ).run()

    assert not result.ok
    assert "runtime OS acceptance evidence is incomplete" in result.failures
    assert result.runtime_os["status"] == "fail"
    assert "runtime_parallel_readonly" in result.runtime_os["missing_capabilities"]


def test_acceptance_gate_passes_with_runtime_os_evidence(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "scenarios": [
                runtime_scenario("runtime_parallel_readonly"),
                runtime_scenario("runtime_disjoint_writes"),
                runtime_scenario(
                    "runtime_worker_failure",
                    {
                        "failure_evidence": True,
                        "candidate_isolated": True,
                        "promotion_failure_recorded": True,
                    },
                ),
                runtime_scenario("runtime_merge_gate_block", {"merge_gate_blocked": True}),
                runtime_scenario("runtime_request_resume", {"resume_recovered": True}),
                runtime_scenario(
                    "runtime_context_package_slice",
                    {
                        "context_package_sliced": True,
                        "context_package_scope_partitioned": True,
                    },
                ),
                runtime_scenario(
                    "runtime_sandbox_backend_selection",
                    {"sandbox_backend_recorded": True},
                ),
                runtime_scenario(
                    "runtime_planner_scope_quality",
                    {"planner_scope_narrowed": True, "runtime_request_created": True},
                ),
                runtime_scenario(
                    "runtime_capability_feedback",
                    {"capability_feedback_recorded": True},
                ),
                runtime_scenario(
                    "runtime_evidence_consumption",
                    {
                        "debug_consumed_runtime_evidence": True,
                        "review_consumed_runtime_evidence": True,
                    },
                ),
            ],
        },
    )

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        suite="core",
        min_scenarios=10,
        min_capabilities=10,
        require_tiers=["core"],
    ).run()

    assert result.ok
    assert result.runtime_os["status"] == "pass"
    assert "Runtime OS gate:" in result.to_text()


def test_acceptance_gate_blocks_unresolved_candidate_promotions(tmp_path: Path) -> None:
    report_path = write_report(
        tmp_path,
        {
            "suite": "core",
            "ok": True,
            "returncode": 0,
            "scenarios": [
                runtime_scenario("runtime_parallel_readonly"),
                runtime_scenario("runtime_disjoint_writes"),
                runtime_scenario(
                    "runtime_worker_failure",
                    {
                        "failure_evidence": True,
                        "candidate_isolated": True,
                        "promotion_failure_recorded": True,
                    },
                ),
                runtime_scenario("runtime_merge_gate_block", {"merge_gate_blocked": True}),
                runtime_scenario("runtime_request_resume", {"resume_recovered": True}),
                runtime_scenario(
                    "runtime_context_package_slice",
                    {
                        "context_package_sliced": True,
                        "context_package_scope_partitioned": True,
                    },
                ),
                runtime_scenario(
                    "runtime_sandbox_backend_selection",
                    {"sandbox_backend_recorded": True},
                ),
                runtime_scenario(
                    "runtime_planner_scope_quality",
                    {"planner_scope_narrowed": True, "runtime_request_created": True},
                ),
                runtime_scenario(
                    "runtime_capability_feedback",
                    {"capability_feedback_recorded": True},
                ),
                runtime_scenario(
                    "runtime_evidence_consumption",
                    {
                        "debug_consumed_runtime_evidence": True,
                        "review_consumed_runtime_evidence": True,
                    },
                ),
            ],
        },
    )
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    _append_candidate_promotion(run_dir, "pending_manual_approval")

    result = AcceptanceGateCommand(
        tmp_path,
        report_path=report_path,
        suite="core",
        min_scenarios=10,
        min_capabilities=10,
        require_tiers=["core"],
    ).run()

    assert not result.ok
    assert "candidate promotion queue has unresolved release risks" in result.failures
    assert result.runtime_os["promotion_release_risks"]["pending"] == 1


def scenario(name: str, ok: bool) -> dict:
    capability = {
        "file_smoke": "artifact_creation",
        "password_cli": "single_file_cli",
        "markdown_kb": "search_cli",
        "safe_file_renamer": "config_driven_cli",
        "multi_file_todo_cli": "multi_file_change",
        "config_driven_report": "configuration_change",
    }.get(name, "unknown")
    return {
        "scenario": name,
        "capability": capability,
        "tier": "smoke" if name == "file_smoke" else "core",
        "ok": ok,
        "workspace": None,
        "failure_summary": "" if ok else f"{name} failed",
        "stdout_tail": "",
        "stderr_tail": "",
        "summary": {},
    }


def legacy_scenario(name: str, ok: bool) -> dict:
    item = scenario(name, ok)
    item.pop("capability")
    item.pop("tier")
    return item


def runtime_scenario(name: str, extra_evidence: dict | None = None) -> dict:
    capability = {
        "runtime_context_package_slice": "context_package_slice",
        "runtime_sandbox_backend_selection": "sandbox_backend_selection",
        "runtime_planner_scope_quality": "planner_scope_quality",
        "runtime_capability_feedback": "capability_feedback",
    }.get(name, name)
    evidence = {
        "workers_jsonl": True,
        "worker_results_jsonl": True,
        "runtime_profiles_jsonl": True,
        "context_mounts_jsonl": True,
        "validation_results_jsonl": True,
        "task_execution_evidence_jsonl": True,
    }
    evidence.update(extra_evidence or {})
    return {
        "scenario": name,
        "capability": capability,
        "tier": "core",
        "ok": True,
        "workspace": None,
        "failure_summary": "",
        "stdout_tail": "",
        "stderr_tail": "",
        "summary": {
            "runtime_os": {
                "capability": capability,
                "evidence": evidence,
            }
        },
    }


def write_report(tmp_path: Path, overrides: dict) -> Path:
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": [],
        "root": str(tmp_path),
        "ok": True,
        "returncode": 0,
        "created_at": "2026-05-06T12:00:00+08:00",
        "summary_json": str(tmp_path / ".asteria" / "acceptance" / "latest_summary.json"),
        "aggregate": {},
        "trend": {},
        "trend_warnings": [],
        "scenarios": [],
        "scenario_metadata": [],
    }
    report.update(overrides)
    if report["scenarios"] and not report.get("scenario_metadata"):
        report["scenario_metadata"] = [
            {
                "scenario": item["scenario"],
                "capability": item.get("capability", "unknown"),
                "tier": item.get("tier", "core"),
                "kind": "run",
            }
            for item in report["scenarios"]
        ]
    report.setdefault("aggregate", {})
    report.setdefault("trend", {})
    report.setdefault("trend_warnings", [])
    report_path = tmp_path / ".asteria" / "acceptance" / "acceptance_report.json"
    JsonStore(SchemaValidator(Path.cwd() / "schemas")).write(
        report_path,
        report,
        "acceptance_report",
    )
    return report_path


def _append_candidate_promotion(run_dir: Path, status: str) -> None:
    JsonlStore(SchemaValidator(Path.cwd() / "schemas")).append(
        run_dir / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "candidate_id": "candidate-0001",
            "workspace": str(run_dir / "cw" / "0001"),
            "strategy": "temp_workspace",
            "workspace_policy": "isolated_copy",
            "backend_reason": "test",
            "branch_name": None,
            "promotable_files": ["tool.py"],
            "promoted_files": [],
            "status": status,
            "approval_mode": "manual",
            "merge_gate": {"ok": True},
            "failure": None,
            "decision": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        },
        "candidate_promotion",
    )
