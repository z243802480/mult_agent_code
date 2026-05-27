from __future__ import annotations

import json
from pathlib import Path

import pytest

from asteria_runtime.commands.capability_report_command import CapabilityReportCommand
from asteria_runtime.core.prompt_envelope import capability_manifest_hash
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from tests.helpers.runtime_os import runtime_os_pass_report

pytestmark = pytest.mark.release_gate


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
    store.write(
        run_dir / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "run_id": "run-1",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Fix module",
                    "description": "Fix module",
                    "status": "done",
                    "priority": "medium",
                    "role": "CoderAgent",
                    "depends_on": [],
                    "acceptance": ["verified"],
                    "allowed_tools": ["run_command"],
                    "expected_artifacts": ["repairable.py"],
                    "task_kind": "bugfix",
                    "parallel_safety": "serial",
                    "completion_contract": {
                        "requires_changed_artifact": True,
                        "requires_verification": True,
                        "allows_expected_failure": False,
                    },
                    "created_at": "2026-05-13T10:00:00+08:00",
                    "updated_at": "2026-05-13T10:00:00+08:00",
                    "notes": "",
                }
            ],
        },
        "task_board",
    )
    jsonl.append(
        run_dir / "observation_plans.jsonl",
        {
            "schema_version": "0.1.0",
            "observation_plan_id": "observation-plan-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "trigger": "task_attempt:verification",
            "failed_observation_count": 1,
            "actions": [{"action": "repair"}],
            "blockers": ["run_command: tests failed"],
            "evidence_refs": ["tool_calls.jsonl"],
            "recommended_route": "repair",
            "reason": "repair: tests failed",
            "created_at": "2026-05-13T10:00:28+08:00",
        },
        "observation_plan",
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
    manifest = {
        "modes": ["build"],
        "direct_tools": [{"name": "read_file"}],
        "deferred_tools": [],
        "mcp_tools": [],
        "skills": [],
        "subagents": [],
        "verification": [{"name": "run_tests"}],
        "boundaries": {"active_mode": "build"},
    }
    manifest_hash = capability_manifest_hash(manifest)
    store.write(
        run_dir / "prompt_envelope_execute.json",
        {
            "schema_version": "0.1.0",
            "run_id": "run-1",
            "mode": "execute",
            "sections": [
                {
                    "name": "capability_manifest",
                    "source": "AgentHarness",
                    "priority": "system",
                    "cache_scope": "dynamic",
                    "token_estimate": 10,
                    "content_hash": "sha256:section",
                    "summary": "manifest",
                    "evidence_refs": [],
                    "cache_break_reasons": ["tools_or_modes_changed"],
                }
            ],
            "section_order": ["capability_manifest"],
            "capability_manifest": manifest,
            "content_hash": "sha256:prompt",
        },
        "prompt_envelope",
    )
    context_envelope_path = (
        run_dir / "context_envelopes" / "context_envelope_task-0001.json"
    )
    store.write(
        context_envelope_path,
        {
            "schema_version": "0.1.0",
            "envelope_id": "context-envelope-task-0001",
            "audience": "worker",
            "mode": "execute",
            "intent": "task_execution",
            "root": str(tmp_path),
            "run_id": "run-1",
            "created_at": "2026-05-07T10:00:27+08:00",
            "sections": [
                {
                    "name": "task_context",
                    "included": True,
                    "summary": "worker context",
                }
            ],
            "refs": ["task_graph.json"],
            "redaction_policy": {"backend_fields_allowed": True},
            "payload_hash": "sha256:context",
            "payload": {"task_id": "task-0001"},
        },
        "context_envelope",
    )
    jsonl.append(
        run_dir / "model_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "model_call_id": "modelcall-0001",
            "run_id": "run-1",
            "agent_id": "CoderAgent",
            "prompt_envelope_hash": "sha256:prompt",
            "prompt_envelope_path": str(run_dir / "prompt_envelope_execute.json"),
            "context_envelope_hash": "sha256:context",
            "context_envelope_path": str(context_envelope_path),
            "capability_manifest_hash": manifest_hash,
            "purpose": "task_execution",
            "model_provider": "runtime",
            "model_name": "medium-route",
            "model_tier": "medium",
            "status": "success",
            "created_at": "2026-05-07T10:00:28+08:00",
            "summary": "ok",
        },
        "model_call",
    )
    store.write(
        run_dir / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "run_id": "run-1",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": "Fix module",
                    "description": "Fix module",
                    "status": "done",
                    "priority": "medium",
                    "role": "CoderAgent",
                    "depends_on": [],
                    "acceptance": ["verified"],
                    "allowed_tools": ["run_command"],
                    "expected_artifacts": ["repairable.py"],
                    "task_kind": "bugfix",
                    "parallel_safety": "serial",
                    "completion_contract": {
                        "requires_changed_artifact": True,
                        "requires_verification": True,
                        "allows_expected_failure": False,
                    },
                    "created_at": "2026-05-13T10:00:00+08:00",
                    "updated_at": "2026-05-13T10:00:00+08:00",
                    "notes": "",
                }
            ],
        },
        "task_board",
    )
    jsonl.append(
        run_dir / "observation_plans.jsonl",
        {
            "schema_version": "0.1.0",
            "observation_plan_id": "observation-plan-0001",
            "run_id": "run-1",
            "task_id": "task-0001",
            "trigger": "task_attempt:verification",
            "failed_observation_count": 1,
            "actions": [{"action": "repair"}],
            "blockers": ["run_command: tests failed"],
            "evidence_refs": ["tool_calls.jsonl"],
            "recommended_route": "repair",
            "reason": "repair: tests failed",
            "created_at": "2026-05-13T10:00:28+08:00",
        },
        "observation_plan",
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
    assert route["route_signal_total"] == 1
    assert route["route_signal_success"] == 1
    assert route["route_signal_success_rate"] == 1.0
    assert route["route_task_kinds"]["bugfix"] == 1
    assert route["route_decisions"]["repair"] == 1
    assert result.runtime_os["status"] == "pass"
    assert result.runtime_os["gate"]["status"] == "pass"
    assert result.runtime_os["evidence"]["worker_invocations"] == 1
    assert result.runtime_os["evidence"]["worker_results"] == 1
    assert result.runtime_os["evidence"]["context_mounts"] == 1
    assert result.runtime_os["evidence"]["task_execution_evidence"] == 1
    assert result.runtime_os["evidence"]["task_graph_selections"] == 1
    manifest_audit = result.runtime_os["evidence"]["capability_manifest_audit"]
    assert manifest_audit["manifest_hashes"] == [manifest_hash]
    assert manifest_audit["context_envelope_hashes"] == ["sha256:context"]
    assert manifest_audit["cache_break_reasons"] == ["tools_or_modes_changed"]
    assert manifest_audit["model_metadata_complete"] is True
    assert manifest_audit["context_envelope_metadata_complete"] is True
    assert "Runtime OS release evidence" in result.to_text()
    assert "capability manifest audit" in result.to_text()
    assert "context envelope audit" in result.to_text()


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
    return runtime_os_pass_report(tmp_path)


def test_capability_report_merges_real_provider_matrix_signals(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    matrix_dir = tmp_path / ".asteria" / "verification" / "real_provider_matrix" / "matrix-1"
    workspace = matrix_dir / "workspaces" / "file_output"
    run_dir = workspace / ".asteria" / "runs" / "run-matrix"
    run_dir.mkdir(parents=True)
    jsonl.append(
        run_dir / "model_calls.jsonl",
        {
            "schema_version": "0.1.0",
            "model_call_id": "modelcall-matrix-0001",
            "run_id": "run-matrix",
            "agent_id": "CoderAgent",
            "purpose": "task_execution",
            "model_provider": "openai-compatible",
            "model_name": "matrix-model",
            "model_tier": "medium",
            "input_tokens": 100,
            "output_tokens": 30,
            "status": "success",
            "created_at": "2026-05-24T18:00:00+08:00",
            "summary": "matrix case ok",
        },
        "model_call",
    )
    store.write(
        matrix_dir / "matrix_summary.json",
        {
            "schema_version": "0.1.0",
            "matrix": "p0",
            "created_at": "2026-05-24T18:00:00+00:00",
            "ok": True,
            "output_dir": str(matrix_dir),
            "case_count": 1,
            "passed": 1,
            "failed": 0,
            "duration_seconds": 1.0,
            "cases": [
                {
                    "name": "file_output",
                    "task_kind": "file_output",
                    "route": "artifact_creation",
                    "reason": "bounded file output",
                    "ok": True,
                    "workspace": str(workspace),
                    "summary_json": str(matrix_dir / "file_output_summary.json"),
                    "expected_file": "p0_matrix_file_output.txt",
                    "expected_text": "P0 matrix file output ok",
                    "run_id": "run-matrix",
                    "final_report": str(run_dir / "final_report.md"),
                    "diagnostics": {},
                    "failure_type": None,
                    "failure_summary": None,
                    "evidence_refs": [str(run_dir / "final_report.md")],
                }
            ],
        },
    )

    result = CapabilityReportCommand(tmp_path).run()

    profile = store.read(result.model_profile_path, "model_capability_profile")
    route = profile["profiles"][0]
    assert route["provider"] == "openai-compatible"
    assert route["model"] == "matrix-model"
    assert route["matrix_signal_total"] == 1
    assert route["matrix_signal_success"] == 1
    assert route["matrix_signal_failure"] == 0
    assert route["matrix_signal_success_rate"] == 1.0
    assert route["matrix_task_kinds"] == {"file_output": 1}
    assert route["matrix_routes"] == {"artifact_creation": 1}
    assert route["recent_matrix_signals"] == [
        "2026-05-24T18:00:00+00:00:file_output:artifact_creation:success"
    ]
    assert "matrix=1.00/1" in result.to_text()


def test_capability_report_surfaces_failed_real_provider_matrix_route_guidance(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    matrix_dir = tmp_path / ".asteria" / "verification" / "real_provider_matrix" / "matrix-2"
    workspace = matrix_dir / "workspaces" / "verification_failure_repair"
    workspace.mkdir(parents=True)
    store.write(
        matrix_dir / "matrix_summary.json",
        {
            "schema_version": "0.1.0",
            "matrix": "p0",
            "created_at": "2026-05-24T19:00:00+00:00",
            "ok": False,
            "output_dir": str(matrix_dir),
            "case_count": 2,
            "passed": 1,
            "failed": 1,
            "duration_seconds": 2.0,
            "cases": [
                {
                    "name": "file_output",
                    "task_kind": "file_output",
                    "route": "artifact_creation",
                    "reason": "bounded file output",
                    "ok": True,
                    "workspace": str(workspace),
                    "summary_json": str(matrix_dir / "file_output_summary.json"),
                    "expected_file": "p0_matrix_file_output.txt",
                    "expected_text": "P0 matrix file output ok",
                    "run_id": "run-matrix-ok",
                    "final_report": str(workspace / "final_report_ok.md"),
                    "diagnostics": {},
                    "failure_type": None,
                    "failure_summary": None,
                    "evidence_refs": [str(workspace / "final_report_ok.md")],
                    "provider": "openai-compatible",
                    "model": "matrix-model",
                    "purpose": "task_execution",
                    "model_tier": "medium",
                },
                {
                    "name": "verification_failure_repair",
                    "task_kind": "verification_failure",
                    "route": "repair",
                    "reason": "verification failed after candidate output",
                    "ok": False,
                    "workspace": str(workspace),
                    "summary_json": str(matrix_dir / "repair_summary.json"),
                    "expected_file": "repair_target.py",
                    "expected_text": "return x + 1",
                    "run_id": "run-matrix-fail",
                    "final_report": str(workspace / "final_report_fail.md"),
                    "diagnostics": {"route": "repair"},
                    "failure_type": "verification_failed",
                    "failure_summary": "pytest failed for repair target",
                    "evidence_refs": [str(workspace / "pytest.log")],
                    "provider": "openai-compatible",
                    "model": "matrix-model",
                    "purpose": "task_execution",
                    "model_tier": "medium",
                },
            ],
        },
        "real_provider_matrix_summary",
    )

    result = CapabilityReportCommand(tmp_path).run()

    profile = store.read(result.model_profile_path, "model_capability_profile")
    route = profile["profiles"][0]
    assert route["matrix_signal_total"] == 2
    assert route["matrix_signal_success"] == 1
    assert route["matrix_signal_failure"] == 1
    assert route["matrix_signal_success_rate"] == 0.5
    assert route["recommended_action"] == "review_real_provider_matrix_before_scaling"
    assert result.latest_real_provider_matrix["latest_route"] == "repair"
    assert result.matrix_route_guidance["status"] == "blocked"
    assert result.matrix_route_guidance["latest_task_kind"] == "verification_failure"
    assert any(
        "real-provider P0 matrix failure" in action and "requires repair" in action
        for action in result.next_actions
    )
    text = result.to_text()
    assert "Latest real-provider matrix: 1/2 passed" in text
    assert "Matrix route guidance: blocked" in text
    assert "requires repair" in text
