from __future__ import annotations

import json
from pathlib import Path

from asteria_runtime.commands.capability_report_command import CapabilityReportCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_capability_report_summarizes_acceptance_and_execution_evidence(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    agent_dir = tmp_path / ".asteria"
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
                "entry_command": "asteria /run",
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
    jsonl.append(
        run_dir / "model_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "model_call_id": "modelcall-0001",
            "run_id": "run-1",
            "agent_id": "coder",
            "purpose": "task_execution",
            "model_provider": "minimax",
            "model_name": "MiniMax-M2.7",
            "model_tier": "medium",
            "input_tokens": 120,
            "output_tokens": 60,
            "status": "success",
            "created_at": "2026-05-07T10:00:10+08:00",
            "summary": "model call succeeded",
        },
        "model_call",
    )
    jsonl.append(
        run_dir / "model_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "model_call_id": "modelcall-0002",
            "run_id": "run-1",
            "agent_id": "coder",
            "purpose": "task_execution",
            "model_provider": "minimax",
            "model_name": "MiniMax-M2.7",
            "model_tier": "medium",
            "input_tokens": None,
            "output_tokens": None,
            "status": "failure",
            "created_at": "2026-05-07T10:00:20+08:00",
            "summary": "invalid JSON response",
        },
        "model_call",
    )

    result = CapabilityReportCommand(tmp_path).run()

    assert result.acceptance_runs == 1
    assert result.latest_acceptance["release_readiness"] == "blocked"
    assert result.capability_summary["multi_file_change"]["failed"] == 1
    assert result.failure_types["verification_failed"] == 1
    assert result.model_profiles[0]["provider"] == "minimax"
    assert result.model_profiles[0]["purpose"] == "task_execution"
    assert result.model_profiles[0]["success_rate"] == 0.5
    assert result.model_profiles[0]["failure_types"]["provider_response"] == 1
    assert result.model_profiles[0]["recommended_action"] == "use_json_stricter_or_switch_model"
    assert result.model_profile_path == tmp_path / ".asteria" / "model" / "capability_profile.json"
    profile = store.read(result.model_profile_path, "model_capability_profile")
    assert profile["profile_count"] == 1
    assert profile["profiles"][0]["recommended_action"] == "use_json_stricter_or_switch_model"
    assert result.route_guidance["status"] == "review"
    assert "Review affected route purposes" in result.route_guidance["recommended_actions"][0]
    assert "verification command failed" in result.common_blockers
    assert "Model capability profiles" in result.to_text()
    assert "Route guidance: review" in result.to_text()
    assert "Capability report" in result.to_text()


def test_capability_report_backfills_legacy_acceptance_capabilities(tmp_path: Path) -> None:
    jsonl = JsonlStore(SchemaValidator(Path.cwd() / "schemas"))
    acceptance_dir = tmp_path / ".asteria" / "acceptance"
    acceptance_dir.mkdir(parents=True)
    jsonl.append(
        acceptance_dir / "history.jsonl",
        {
            "schema_version": "0.1.0",
            "suite": "core",
            "requested_scenarios": ["password_cli", "safe_file_renamer"],
            "root": str(tmp_path),
            "ok": False,
            "returncode": 1,
            "created_at": "2026-05-07T10:00:00+08:00",
            "summary_json": str(acceptance_dir / "legacy.json"),
            "aggregate": {"total": 2, "passed": 1, "failed": 1},
            "trend_warnings": [],
            "scenarios": [
                {
                    "scenario": "password_cli",
                    "ok": True,
                    "workspace": None,
                    "failure_summary": "",
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "summary": {},
                },
                {
                    "scenario": "safe_file_renamer",
                    "ok": False,
                    "workspace": None,
                    "failure_summary": "recovery-resume failed",
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "summary": {},
                },
            ],
        },
    )

    result = CapabilityReportCommand(tmp_path).run()

    assert "unknown" not in result.capability_summary
    assert result.capability_summary["single_file_cli"]["passed"] == 1
    assert result.capability_summary["config_driven_cli"]["failed"] == 1
    assert result.failure_types["runtime_recovery_failed"] == 1


def test_capability_report_adds_worker_validation_signals_to_model_profile(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    run_dir = tmp_path / ".asteria" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    acceptance_dir = tmp_path / ".asteria" / "acceptance"
    acceptance_dir.mkdir(parents=True)
    store.write(
        acceptance_dir / "acceptance_report.json",
        runtime_os_report(tmp_path),
        "acceptance_report",
    )
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "run_id": "run-1",
                "goal_id": "goal-1",
                "status": "completed",
                "started_at": "2026-05-13T10:00:00+08:00",
                "ended_at": "2026-05-13T10:01:00+08:00",
                "entry_command": "asteria /execute",
                "current_phase": "DONE",
                "workspace": {"mode": "single_workspace", "path": "."},
                "summary": "done",
            }
        ),
        encoding="utf-8",
    )
    jsonl.append(
        run_dir / "model_profiles.jsonl",
        {
            "schema_version": "0.1.0",
            "model_profile_id": "model-profile-0001",
            "purpose": "coding",
            "provider": "runtime",
            "model_name": "medium-route",
            "model_tier": "medium",
            "fallback_profile_ids": [],
        },
        "model_profile",
    )
    jsonl.append(
        run_dir / "context_mounts.jsonl",
        {
            "schema_version": "0.1.0",
            "context_mount_id": "context-mount-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "mount_type": "coding_context",
            "includes": {
                "root_guidance": True,
                "goal_brief": True,
                "task_brief": True,
                "artifact_refs": [],
                "failure_evidence_refs": [],
                "decision_refs": [],
                "validation_refs": [],
                "recent_event_count": 3,
            },
            "summary": "coding context",
        },
        "context_mount",
    )
    jsonl.append(
        run_dir / "runtime_profiles.jsonl",
        {
            "schema_version": "0.1.0",
            "runtime_profile_id": "runtime-profile-0001",
            "agent_id": "CoderAgent",
            "model_profile_id": "model-profile-0001",
            "tool_permission_profile_id": "tools-profile-0001",
            "account_profile_id": "account-profile-0001",
            "sandbox_profile_id": "sandbox-profile-0001",
            "context_mount_id": "context-mount-0001",
            "budget": {"max_model_calls": 1, "max_tool_calls": 5},
        },
        "runtime_profile",
    )
    jsonl.append(
        run_dir / "workers.jsonl",
        {
            "schema_version": "0.1.0",
            "worker_invocation_id": "worker-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "agent_id": "CoderAgent",
            "runtime_profile_id": "runtime-profile-0001",
            "status": "succeeded",
            "started_at": "2026-05-13T10:00:00+08:00",
            "ended_at": "2026-05-13T10:00:30+08:00",
            "summary": "worker completed",
        },
        "worker_invocation",
    )
    jsonl.append(
        run_dir / "validation_results.jsonl",
        {
            "schema_version": "0.1.0",
            "validation_result_id": "validation-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "tool_name": "run_command",
            "command": "pytest tests/test_notes.py",
            "status": "passed",
            "summary": "passed",
            "error": None,
            "data": {},
            "created_at": "2026-05-13T10:00:20+08:00",
        },
        "validation_result",
    )
    jsonl.append(
        run_dir / "events.jsonl",
        {
            "schema_version": "0.1.0",
            "event_id": "event-0001",
            "run_id": "run-1",
            "timestamp": "2026-05-13T10:00:00+08:00",
            "type": "task_graph_selection",
            "actor": "ExecuteCommand",
            "summary": "Selected 1 task.",
            "data": {"reason": "serial_selection", "task_ids": ["task-0001"]},
        },
        "event",
    )
    jsonl.append(
        run_dir / "task_execution_evidence.jsonl",
        {
            "schema_version": "0.1.0",
            "evidence_id": "task-execution-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "status": "succeeded",
            "summary": "candidate verified",
            "failure_type": None,
            "task": {},
            "action": {},
            "candidate": {},
            "contract_check": {
                "merge_gate": {
                    "ok": False,
                    "promotable_files": [],
                    "violations": ["changed files outside write_scope: docs/notes.md"],
                }
            },
            "tool_results": [],
            "verification_results": [],
            "created_at": "2026-05-13T10:00:25+08:00",
        },
        "task_execution_evidence",
    )
    jsonl.append(
        run_dir / "runtime_requests.jsonl",
        {
            "schema_version": "0.1.0",
            "runtime_request_id": "runtime-request-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "request_type": "scope_expansion",
            "risk": "medium",
            "reason": "Need docs/notes.md",
            "details": {"write_scope": ["docs/notes.md"]},
            "status": "decision_created",
            "decision_id": "decision-0001",
            "created_at": "2026-05-13T10:00:26+08:00",
        },
        "runtime_request",
    )
    jsonl.append(
        run_dir / "worker_results.jsonl",
        {
            "schema_version": "0.1.0",
            "worker_result_id": "worker-result-0001",
            "worker_invocation_id": "worker-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "status": "succeeded",
            "artifact_refs": ["artifact-0001"],
            "validation_refs": ["validation-0001"],
            "failure_evidence_refs": [],
            "cost": {"model_calls": 1, "tool_calls": 2},
            "summary": "done",
        },
        "worker_result",
    )

    result = CapabilityReportCommand(tmp_path).run()

    profile = store.read(result.model_profile_path, "model_capability_profile")
    route = profile["profiles"][0]
    assert route["provider"] == "runtime"
    assert route["model"] == "medium-route"
    assert route["purpose"] == "coding"
    assert route["total_workers"] == 1
    assert route["successful_workers"] == 1
    assert route["worker_success_rate"] == 1.0
    assert route["validation_total"] == 1
    assert route["validation_pass_rate"] == 1.0
    assert route["runtime_request_total"] == 1
    assert route["runtime_request_rate"] == 1.0
    assert route["runtime_request_types"]["scope_expansion"] == 1
    assert route["merge_gate_blocks"] == 1
    assert route["failure_types"]["merge_gate"] == 1
    assert result.runtime_os["status"] == "pass"
    assert result.runtime_os["gate"]["status"] == "pass"
    assert result.runtime_os["evidence"]["worker_invocations"] == 1
    assert result.runtime_os["evidence"]["worker_results"] == 1
    assert result.runtime_os["evidence"]["context_mounts"] == 1
    assert result.runtime_os["evidence"]["task_execution_evidence"] == 1
    assert result.runtime_os["evidence"]["task_graph_selections"] == 1
    assert "Runtime OS release evidence" in result.to_text()


def test_capability_report_uses_acceptance_runtime_evidence_without_run_jsonl(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    acceptance_dir = tmp_path / ".asteria" / "acceptance"
    acceptance_dir.mkdir(parents=True)
    store.write(
        acceptance_dir / "acceptance_report.json",
        runtime_os_report(tmp_path),
        "acceptance_report",
    )

    result = CapabilityReportCommand(tmp_path).run()

    assert result.runtime_os["status"] == "pass"
    assert result.runtime_os["release_ready"] is True
    assert result.runtime_os["evidence"]["worker_results"] == 0
    assert result.runtime_os["evidence"]["acceptance_worker_results_jsonl"] is True
    assert "acceptance worker evidence: present" in result.to_text()


def test_capability_report_uses_latest_report_for_trend_readiness(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    acceptance_dir = tmp_path / ".asteria" / "acceptance"
    acceptance_dir.mkdir(parents=True)
    history_report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": ["password_cli"],
        "root": str(tmp_path),
        "ok": True,
        "returncode": 0,
        "created_at": "2026-05-07T10:00:00+08:00",
        "summary_json": str(acceptance_dir / "latest_summary.json"),
        "aggregate": {"total": 1, "passed": 1, "failed": 0},
        "trend_warnings": [],
        "scenarios": [legacy_scenario("password_cli", True)],
    }
    latest_report = dict(history_report)
    latest_report["trend_warnings"] = ["model calls increased by 7 (threshold 5)"]
    jsonl.append(acceptance_dir / "history.jsonl", history_report)
    store.write(acceptance_dir / "acceptance_report.json", latest_report, "acceptance_report")

    result = CapabilityReportCommand(tmp_path).run()

    assert result.latest_acceptance["release_readiness"] == "conditional"


def test_capability_report_marks_closed_repair_as_conditional(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    acceptance_dir = tmp_path / ".asteria" / "acceptance"
    acceptance_dir.mkdir(parents=True)
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": ["markdown_kb"],
        "root": str(tmp_path),
        "ok": False,
        "returncode": 1,
        "created_at": "2026-05-07T10:00:00+08:00",
        "summary_json": str(acceptance_dir / "latest_summary.json"),
        "aggregate": {"total": 1, "passed": 0, "failed": 1},
        "trend_warnings": [],
        "scenarios": [legacy_scenario("markdown_kb", False)],
        "repair_closure": {
            "repair_run_id": "run-1",
            "rerun_summary_json": str(acceptance_dir / "rerun.json"),
            "rerun_ok": True,
            "closed_failures": ["markdown_kb"],
            "remaining_failures": [],
        },
    }
    store.write(acceptance_dir / "acceptance_report.json", report, "acceptance_report")

    result = CapabilityReportCommand(tmp_path).run()

    assert result.latest_acceptance["release_readiness"] == "conditional"
    assert result.latest_acceptance["ok"] is True
    assert result.latest_acceptance["base_ok"] is False
    assert result.latest_acceptance["passed"] == 1
    assert result.latest_acceptance["failed"] == 0
    assert result.capability_summary["search_cli"]["passed"] == 1
    assert result.capability_summary["search_cli"]["failed"] == 0
    assert not any("promote-failures" in action for action in result.next_actions)


def legacy_scenario(name: str, ok: bool) -> dict:
    return {
        "scenario": name,
        "ok": ok,
        "workspace": None,
        "failure_summary": "" if ok else f"{name} failed",
        "stdout_tail": "",
        "stderr_tail": "",
        "summary": {},
    }


def runtime_os_report(tmp_path: Path) -> dict:
    scenarios = [
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
        runtime_scenario("runtime_capability_feedback", {"capability_feedback_recorded": True}),
        runtime_scenario(
            "runtime_evidence_consumption",
            {
                "debug_consumed_runtime_evidence": True,
                "review_consumed_runtime_evidence": True,
            },
        ),
    ]
    return {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": [],
        "root": str(tmp_path),
        "ok": True,
        "returncode": 0,
        "created_at": "2026-05-13T10:00:00+08:00",
        "summary_json": str(tmp_path / ".asteria" / "acceptance" / "latest_summary.json"),
        "aggregate": {"total": len(scenarios), "passed": len(scenarios), "failed": 0},
        "trend_warnings": [],
        "scenarios": scenarios,
        "scenario_metadata": [
            {
                "scenario": item["scenario"],
                "capability": item["capability"],
                "tier": item["tier"],
                "kind": "runtime_os",
            }
            for item in scenarios
        ],
    }


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
        "summary": {"runtime_os": {"capability": capability, "evidence": evidence}},
    }
