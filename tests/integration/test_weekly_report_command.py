from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.commands.init_command import InitCommand
from agent_runtime.commands.weekly_report_command import WeeklyReportCommand
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


def test_weekly_report_summarizes_long_run_acceptance_and_model_profile(
    tmp_path: Path,
) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    jsonl = JsonlStore(validator)
    agent_dir = tmp_path / ".agent"
    daily_dir = agent_dir / "daily" / "release-hardening"
    daily_dir.mkdir(parents=True)
    store.write(
        daily_dir / "daily_report.json",
        {
            "schema_version": "0.1.0",
            "date": "release-hardening",
            "cycle_id": "release-hardening",
            "schedule_type": "long_running_cycle",
            "root": str(tmp_path),
            "status": "blocked",
            "created_at": "2026-05-12T10:00:00+08:00",
            "plan_path": str(daily_dir / "daily_plan.json"),
            "executed": True,
            "goal": "Stabilize release gate",
            "objective": "Stabilize release gate",
            "progress": {
                "planned_actions": 1,
                "attempted_actions": 1,
                "completed_actions": 0,
                "failed_actions": 1,
            },
            "stop_reason": "failure limit reached (1/1)",
            "budget": {},
            "results": [],
            "summary": "Executed 1 action(s), 0 passed.",
            "risks": ["Acceptance still has failing scenarios: config_driven_report"],
            "model_profile": {"status": "ready", "profile_count": 1},
            "next_actions": ["Run failed-only acceptance."],
        },
        "daily_report",
    )
    acceptance_dir = agent_dir / "acceptance"
    acceptance_dir.mkdir(parents=True)
    acceptance = runtime_os_report(tmp_path)
    acceptance["ok"] = False
    acceptance["returncode"] = 1
    acceptance["aggregate"] = {
        "total": len(acceptance["scenarios"]) + 1,
        "passed": len(acceptance["scenarios"]),
        "failed": 1,
    }
    acceptance["scenarios"].append(
        {
            "scenario": "config_driven_report",
            "capability": "configuration_change",
            "tier": "core",
            "ok": False,
            "workspace": None,
            "failure_summary": "report.md was not created",
        }
    )
    acceptance["scenario_metadata"].append(
        {
            "scenario": "config_driven_report",
            "capability": "configuration_change",
            "tier": "core",
            "kind": "run",
        }
    )
    store.write(acceptance_dir / "acceptance_report.json", acceptance, "acceptance_report")
    jsonl.append(acceptance_dir / "history.jsonl", acceptance)
    run_dir = agent_dir / "runs" / "run-1"
    run_dir.mkdir(parents=True)
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
            "started_at": "2026-05-12T10:00:00+08:00",
            "ended_at": "2026-05-12T10:00:10+08:00",
            "summary": "done",
        },
        "worker_invocation",
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
    jsonl.append(
        run_dir / "events.jsonl",
        {
            "schema_version": "0.1.0",
            "event_id": "event-0001",
            "run_id": "run-1",
            "timestamp": "2026-05-12T10:00:00+08:00",
            "type": "task_graph_selection",
            "actor": "ExecuteCommand",
            "summary": "Selected 1 task.",
            "data": {"reason": "serial_selection"},
        },
        "event",
    )
    model_dir = agent_dir / "model"
    model_dir.mkdir(parents=True)
    store.write(
        model_dir / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "minimax",
                    "model": "MiniMax-M2.7",
                    "purpose": "task_execution",
                    "model_tier": "medium",
                    "total_calls": 3,
                    "success_calls": 1,
                    "failure_calls": 2,
                    "success_rate": 0.3333,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "average_input_tokens": 33.33,
                    "average_output_tokens": 16.67,
                    "failure_types": {"provider_response": 2},
                    "recommended_action": "use_json_stricter_or_switch_model",
                    "recent_failures": ["invalid JSON"],
                }
            ],
        },
        "model_capability_profile",
    )

    result = WeeklyReportCommand(tmp_path, week_id="2026-W20").run()

    report = store.read(result.report_path, "weekly_report")
    markdown = result.report_path.with_suffix(".md").read_text(encoding="utf-8")
    assert result.status == "blocked"
    assert report["long_run"]["cycles"] == 1
    assert report["long_run"]["failed_actions"] == 1
    assert report["acceptance"]["latest_failed"] == 1
    assert report["runtime_os"]["gate"]["status"] == "pass"
    assert report["runtime_os"]["evidence"]["worker_results"] == 1
    assert report["runtime_os"]["evidence"]["task_graph_selections"] == 1
    assert report["model_profile"]["weak_routes"][0]["purpose"] == "task_execution"
    assert any("Acceptance failures remain" in risk for risk in report["risks"])
    assert "agent /acceptance --failed-only --promote-failures" in report["next_actions"][0]
    assert "Weekly Production Report" in markdown
    assert "## Runtime OS" in markdown
    assert "config_driven_report" in markdown


def test_weekly_report_handles_missing_inputs(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = WeeklyReportCommand(tmp_path, week_id="2026-W20").run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "needs_attention"
    assert report["long_run"]["cycles"] == 0
    assert report["runtime_os"]["status"] == "missing_acceptance"
    assert "No long-run cycle reports were found" in report["risks"][0]
    assert "agent /long-run-plan" in report["next_actions"][0]


def runtime_os_report(tmp_path: Path) -> dict:
    scenarios = [
        runtime_scenario("runtime_parallel_readonly"),
        runtime_scenario("runtime_disjoint_writes"),
        runtime_scenario(
            "runtime_worker_failure",
            {"failure_evidence": True, "candidate_isolated": True},
        ),
        runtime_scenario("runtime_merge_gate_block", {"merge_gate_blocked": True}),
        runtime_scenario("runtime_request_resume", {"resume_recovered": True}),
        runtime_scenario("runtime_context_package_slice", {"context_package_sliced": True}),
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
        "created_at": "2026-05-12T10:01:00+08:00",
        "summary_json": str(tmp_path / ".agent" / "acceptance" / "latest_summary.json"),
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
