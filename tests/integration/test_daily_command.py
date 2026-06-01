from __future__ import annotations

import json
import subprocess
from pathlib import Path

from asteria_runtime.commands.daily_command import (
    DailyPlanCommand,
    DailyReportCommand,
    DailyRunCommand,
)
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.ops_signal_command import OpsSignalCommand
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


def _cost_report(model_calls: int = 0, tool_calls: int = 0, repair_attempts: int = 0) -> dict:
    return {
        "schema_version": "0.1.0",
        "run_id": "run-20260512-0001",
        "status": "within_budget",
        "model_calls": model_calls,
        "tool_calls": tool_calls,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "strong_model_calls": model_calls,
        "cheap_model_calls": 0,
        "repair_attempts": repair_attempts,
        "context_compactions": 0,
        "user_decisions": 0,
        "warnings": [],
    }


def test_daily_plan_selects_failed_only_acceptance_action(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    report = {
        "schema_version": "0.1.0",
        "suite": "core",
        "requested_scenarios": [],
        "root": str(tmp_path),
        "ok": False,
        "returncode": 1,
        "created_at": "2026-05-12T00:00:00+08:00",
        "summary_json": str(tmp_path / ".asteria" / "acceptance" / "latest_summary.json"),
        "scenarios": [
            {
                "scenario": "config_driven_report",
                "ok": False,
                "workspace": None,
                "failure_summary": "failed",
            }
        ],
    }
    JsonStore(validator).write(
        tmp_path / ".asteria" / "acceptance" / "acceptance_report.json",
        report,
        "acceptance_report",
    )

    result = DailyPlanCommand(tmp_path, date="2026-05-12").run()

    plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
    assert result.action_count == 1
    assert plan["cycle_id"] == "2026-05-12"
    assert plan["schedule_type"] == "long_running_cycle"
    assert plan["automation_manifest"]["execution_policy"]["requires_explicit_execute"] is True
    assert "action_failure" in plan["automation_manifest"]["stop_conditions"]
    assert ".asteria/daily/2026-05-12/daily_report.json" in plan["automation_manifest"][
        "evidence_outputs"
    ]
    assert plan["actions"][0]["kind"] == "acceptance_failed_only"
    assert plan["actions"][0]["responsible_role"] == "Evaluator"
    assert "--failed-only" in plan["actions"][0]["command"]
    validator.validate("daily_plan", plan)


def test_daily_run_plan_only_writes_report_and_markdown(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = DailyRunCommand(
        tmp_path,
        date="release-hardening",
        objective="Advance the autonomous runtime until release gate validation.",
    ).run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.executed is False
    assert report["executed"] is False
    assert report["cycle_id"] == "release-hardening"
    assert report["schedule_type"] == "long_running_cycle"
    assert report["objective"] == "Advance the autonomous runtime until release gate validation."
    assert report["goal"]
    assert report["progress"]["planned_actions"] == 1
    assert report["stop_reason"] == "plan_only"
    assert report["automation_manifest"]["execution_policy"]["default_mode"] == "plan_only"
    assert "budget_exhausted" in report["stop_conditions"]
    assert any(item.endswith("daily_report.json") for item in report["evidence_outputs"])
    assert report["model_profile"]["status"] == "missing"
    assert report["risks"]
    assert any("Model capability profile is missing" in risk for risk in report["risks"])
    assert report["results"][0]["status"] == "planned"
    assert (result.report_path.with_suffix(".md")).exists()
    markdown = result.report_path.with_suffix(".md").read_text(encoding="utf-8")
    assert "## Budget" in markdown
    assert "## Automation Manifest" in markdown
    assert "## Evidence Outputs" in markdown
    assert "## Risks" in markdown
    assert "## Model Profile" in markdown
    assert "release-hardening" in markdown
    SchemaValidator(Path.cwd() / "schemas").validate("daily_report", report)


def test_daily_plan_reads_model_profile_weak_routes(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    profile_path = tmp_path / ".asteria" / "model" / "capability_profile.json"
    store.write(
        profile_path,
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

    result = DailyPlanCommand(tmp_path, date="release-hardening").run()

    plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
    model_profile = plan["signals"]["model_profile"]
    assert model_profile["status"] == "ready"
    assert model_profile["profile_count"] == 1
    assert model_profile["weak_routes"][0]["purpose"] == "task_execution"
    assert model_profile["weak_routes"][0]["recommended_action"] == (
        "use_json_stricter_or_switch_model"
    )
    assert plan["actions"][0]["kind"] == "model_route_review"
    assert plan["actions"][0]["risk"] == "model_route_risk"
    assert plan["actions"][0]["responsible_role"] == "Product"


def test_daily_plan_prioritizes_unresolved_candidate_promotions(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run_store.set_current_session(run["run_id"], "test")
    _append_candidate_promotion(run_store.run_dir(run["run_id"]), run["run_id"])

    result = DailyPlanCommand(tmp_path, date="release-hardening").run()

    plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
    assert plan["signals"]["candidate_promotions"]["pending"] == 1
    assert plan["actions"][0]["kind"] == "promotion_review"
    assert plan["actions"][0]["risk"] == "promotion_release_risk"
    assert plan["actions"][0]["responsible_role"] == "Release"


def test_daily_plan_prioritizes_blocked_route_guidance(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    JsonStore(validator).write(
        tmp_path / ".asteria" / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "runtime",
                    "model": "medium-route",
                    "purpose": "coding",
                    "model_tier": "medium",
                    "total_calls": 2,
                    "success_calls": 0,
                    "failure_calls": 2,
                    "success_rate": 0.0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_workers": 2,
                    "successful_workers": 0,
                    "failed_workers": 2,
                    "worker_success_rate": 0.0,
                    "validation_total": 0,
                    "validation_passed": 0,
                    "validation_pass_rate": 0.0,
                    "runtime_request_total": 0,
                    "runtime_request_rate": 0.0,
                    "runtime_request_types": {},
                    "merge_gate_blocks": 0,
                    "failure_types": {},
                    "recent_failures": [],
                    "recommended_action": "review_worker_route_before_scaling",
                }
            ],
        },
        "model_capability_profile",
    )

    result = DailyPlanCommand(tmp_path, date="release-hardening").run()

    plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
    assert plan["signals"]["route_guidance"]["status"] == "blocked"
    assert plan["actions"][0]["kind"] == "route_guidance_review"
    assert plan["actions"][0]["risk"] == "model_route_blocked"


def test_daily_plan_consumes_background_usage_signals(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    OpsSignalCommand(
        tmp_path,
        run_id="run-1",
        artifact_outcome="partial",
        blocker_category="report_confusing",
        trust_risk="unclear_validation",
        summary="Maintainer diagnostic signal.",
    ).run()

    result = DailyPlanCommand(tmp_path, date="release-hardening").run()

    plan = json.loads(result.plan_path.read_text(encoding="utf-8"))
    assert plan["signals"]["usage_signals"]["status"] == "needs_attention"
    assert plan["signals"]["usage_signals"]["unresolved"] == 1
    assert plan["actions"][0]["kind"] == "ops_signal_review"
    assert plan["actions"][0]["responsible_role"] == "Maintainer"


def test_daily_report_creates_plan_only_report_when_missing(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = DailyReportCommand(tmp_path, date="2026-05-12").run()

    assert result.report_path.exists()
    assert result.status == "planned"
    assert "planned but not executed" in result.summary


def _append_candidate_promotion(run_dir: Path, run_id: str) -> None:
    JsonlStore(SchemaValidator(Path.cwd() / "schemas")).append(
        run_dir / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": run_id,
            "task_id": "task-0001",
            "candidate_id": "candidate-0001",
            "workspace": str(run_dir / "cw" / "0001"),
            "strategy": "temp_workspace",
            "workspace_policy": "isolated_copy",
            "backend_reason": "test",
            "branch_name": None,
            "promotable_files": ["tool.py"],
            "promoted_files": [],
            "status": "pending_manual_approval",
            "approval_mode": "manual",
            "merge_gate": {"ok": True},
            "failure": None,
            "decision": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        },
        "candidate_promotion",
    )


def test_daily_run_execute_records_evidence_and_budget_delta(
    tmp_path: Path,
    monkeypatch,
) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    store = JsonStore(validator)
    run_store = RunStore(tmp_path / ".asteria", validator)
    run = run_store.create_run("test")
    run_store.set_current_run(run["run_id"], "daily test")
    run_dir = tmp_path / ".asteria" / "runs" / run["run_id"]
    store.write(run_dir / "cost_report.json", _cost_report(), "cost_report")

    def fake_run(*args, **kwargs):
        store.write(run_dir / "cost_report.json", _cost_report(2, 3, 1), "cost_report")
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = DailyRunCommand(tmp_path, date="2026-05-12", execute=True).run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "completed"
    assert report["budget"]["model_calls"] == 2
    assert report["budget"]["tool_calls"] == 3
    assert report["budget"]["repair_attempts"] == 1
    assert report["results"][0]["evidence_path"]
    assert report["results"][0]["evidence_path"] in report["evidence_outputs"]
    assert report["results"][0]["run_evidence_path"] in report["evidence_outputs"]
    assert report["results"][0]["responsible_role"] == "Evaluator"
    daily_evidence = (
        tmp_path / ".asteria" / "daily" / "2026-05-12" / "task_execution_evidence.jsonl"
    )
    run_evidence = run_dir / "task_execution_evidence.jsonl"
    assert daily_evidence.exists()
    assert run_evidence.exists()
    evidence = json.loads(daily_evidence.read_text(encoding="utf-8").splitlines()[0])
    assert evidence["task"]["task_kind"] == "daily_action"
    assert evidence["status"] == "done"
    validator.validate("daily_report", report)


def test_daily_run_execute_stops_on_failure_and_reports_reason(
    tmp_path: Path,
    monkeypatch,
) -> None:
    InitCommand(tmp_path).run()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="pending decision")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = DailyRunCommand(tmp_path, date="2026-05-12", execute=True).run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "blocked"
    assert report["stop_reason"] == "failure limit reached (1/1)"
    assert report["results"][0]["status"] == "fail"
    assert report["results"][0]["failure_type"] == "pending_decision"
    assert any("pending_decision" in risk for risk in report["risks"])


def test_daily_run_hard_stops_before_action_when_budget_is_exhausted(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()

    result = DailyRunCommand(
        tmp_path,
        date="2026-05-12",
        execute=True,
        max_runtime_minutes=0,
    ).run()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "idle"
    assert report["results"] == []
    assert report["stop_reason"].startswith("runtime budget reached")
