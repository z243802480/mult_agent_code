from __future__ import annotations

import json
import sys
from pathlib import Path

from asteria_runtime.cli import build_parser, main


def test_slash_command_aliases_parse_like_regular_commands() -> None:
    parser = build_parser()

    plan_args = parser.parse_args(["/plan", "build a tool", "--root", "."])
    new_args = parser.parse_args(["/new", "build a tool", "--root", "."])
    sessions_args = parser.parse_args(["/sessions", "--root", ".", "--limit", "3", "--context"])
    status_args = parser.parse_args(["/status", "--root", ".", "--json"])
    doctor_args = parser.parse_args(["/doctor", "--root", ".", "--json"])
    gate_status_args = parser.parse_args(["/gate-status", "--root", ".", "--json"])
    gate_args = parser.parse_args(["/gate", "--root", ".", "--json"])
    release_gate_args = parser.parse_args(
        [
            "/gate",
            "--root",
            ".",
            "--stage",
            "release",
            "--report",
            "acceptance_report.json",
            "--suite",
            "core",
            "--skip-lint",
            "--skip-typecheck",
            "--skip-tests",
            "--json",
        ]
    )
    real_model_gate_args = parser.parse_args(
        ["/real-model-gate", "--root", ".", "--summary-json", "gate.json", "--allow-fake"]
    )
    real_model_acceptance_args = parser.parse_args(
        [
            "/real-model-acceptance",
            "--suite",
            "offline",
            "--root",
            ".",
            "--summary-json",
            "acceptance.json",
            "--allow-fake",
        ]
    )
    gray_run_args = parser.parse_args(
        [
            "/gray-run",
            "Create a small probe",
            "--root",
            ".",
            "--dry-run",
            "--max-iterations",
            "2",
            "--summary-json",
            "gray.json",
            "--json",
        ]
    )
    verification_args = parser.parse_args(["/verification", "--root", "."])
    package_check_args = parser.parse_args(["/package-check", "--root", ".", "--json"])
    plugins_args = parser.parse_args(
        ["/plugins", "--root", ".", "enable", "--plugin-id", "example.audit", "--json"]
    )
    model_check_args = parser.parse_args(
        ["/model-check", "--root", ".", "--tier", "strong", "--json"]
    )
    gray_args = parser.parse_args(
        [
            "/gray",
            "Create a small probe",
            "--root",
            ".",
            "--summary-json",
            "gray-plan.json",
            "--json",
        ]
    )
    runs_args = parser.parse_args(["/runs", "--root", ".", "--run-id", "run-1"])
    execute_args = parser.parse_args(
        [
            "/execute",
            "--root",
            ".",
            "--session-id",
            "run-1",
            "--parallel-readonly",
            "--parallel-disjoint-writes",
        ]
    )
    promotions_args = parser.parse_args(
        [
            "/promotions",
            "--root",
            ".",
            "--session-id",
            "run-1",
            "approve",
            "--promotion-id",
            "promotion-0001",
            "--json",
        ]
    )
    replan_args = parser.parse_args(
        ["/replan", "--root", ".", "--session-id", "run-1", "--max-items", "3"]
    )
    brainstorm_args = parser.parse_args(["/brainstorm", "build a tool", "--root", ".", "--apply"])
    acceptance_args = parser.parse_args(
        [
            "/acceptance",
            "--root",
            ".",
            "--suite",
            "nightly",
            "--allow-fake",
            "--fail-on-trend-warning",
            "--warn-model-call-delta",
            "8",
        ]
    )
    acceptance_history_args = parser.parse_args(
        [
            "/acceptance-history",
            "--root",
            ".",
            "--suite",
            "smoke",
            "--limit",
            "2",
            "--warn-model-call-delta",
            "7",
            "--warn-duration-delta",
            "30",
            "--fail-on-warning",
        ]
    )
    acceptance_gate_args = parser.parse_args(
        [
            "/acceptance-gate",
            "--root",
            ".",
            "--suite",
            "core",
            "--min-scenarios",
            "4",
            "--min-capabilities",
            "3",
            "--require-tier",
            "core",
            "--allow-trend-warnings",
            "--no-require-runtime-os",
        ]
    )
    capability_report_args = parser.parse_args(
        ["/capability-report", "--root", ".", "--limit", "5"]
    )
    evidence_bundle_args = parser.parse_args(
        ["/evidence-bundle", "--root", ".", "--max-runs", "3", "--json"]
    )
    weekly_report_args = parser.parse_args(
        ["/weekly-report", "--root", ".", "--week-id", "2026-W20", "--limit", "4"]
    )
    roadmap_args = parser.parse_args(
        ["/roadmap-update", "--root", ".", "--output", "docs/zh/自动路线图.md"]
    )
    daily_plan_args = parser.parse_args(["/daily-plan", "--root", ".", "--max-model-calls", "10"])
    daily_run_args = parser.parse_args(
        [
            "/daily-run",
            "--root",
            ".",
            "--execute",
            "--max-model-calls",
            "9",
            "--max-tool-calls",
            "11",
            "--max-runtime-minutes",
            "3",
            "--max-repair-attempts",
            "1",
        ]
    )
    daily_report_args = parser.parse_args(["/daily-report", "--root", "."])
    long_run_args = parser.parse_args(
        [
            "/long-run",
            "--root",
            ".",
            "--cycle-id",
            "release-hardening",
            "--objective",
            "run a long autonomous task safely",
            "--execute",
        ]
    )
    run_parallel_args = parser.parse_args(["/run", "build", "--parallel-disjoint-writes"])
    resume_parallel_args = parser.parse_args(["/resume", "--parallel-disjoint-writes"])

    assert plan_args.command == "/plan"
    assert plan_args.goal == "build a tool"
    assert new_args.command == "/new"
    assert new_args.goal == "build a tool"
    assert sessions_args.command == "/sessions"
    assert sessions_args.limit == 3
    assert sessions_args.context
    assert status_args.command == "/status"
    assert status_args.json
    assert doctor_args.command == "/doctor"
    assert doctor_args.json
    assert gate_status_args.command == "/gate-status"
    assert gate_status_args.json
    assert gate_args.command == "/gate"
    assert gate_args.json
    assert gate_args.stage == "read-only"
    assert release_gate_args.command == "/gate"
    assert release_gate_args.stage == "release"
    assert release_gate_args.report.as_posix() == "acceptance_report.json"
    assert release_gate_args.suite == "core"
    assert release_gate_args.skip_lint
    assert release_gate_args.skip_typecheck
    assert release_gate_args.skip_tests
    assert real_model_gate_args.command == "/real-model-gate"
    assert real_model_gate_args.allow_fake
    assert real_model_acceptance_args.command == "/real-model-acceptance"
    assert real_model_acceptance_args.suite == "offline"
    assert real_model_acceptance_args.allow_fake
    assert gray_run_args.command == "/gray-run"
    assert gray_run_args.goal == "Create a small probe"
    assert gray_run_args.dry_run
    assert gray_run_args.max_iterations == 2
    assert gray_run_args.summary_json.as_posix() == "gray.json"
    assert gray_run_args.json
    assert gray_args.command == "/gray"
    assert gray_args.goal == "Create a small probe"
    assert gray_args.summary_json.as_posix() == "gray-plan.json"
    assert gray_args.json
    assert verification_args.command == "/verification"
    assert package_check_args.command == "/package-check"
    assert package_check_args.json
    assert plugins_args.command == "/plugins"
    assert plugins_args.plugin_action == "enable"
    assert plugins_args.plugin_id == "example.audit"
    assert plugins_args.json
    assert model_check_args.command == "/model-check"
    assert model_check_args.json
    assert model_check_args.tier == "strong"
    assert runs_args.command == "/runs"
    assert runs_args.session_id == "run-1"
    assert execute_args.session_id == "run-1"
    assert execute_args.parallel_readonly
    assert execute_args.parallel_disjoint_writes
    assert promotions_args.command == "/promotions"
    assert promotions_args.promotion_action == "approve"
    assert promotions_args.promotion_id == "promotion-0001"
    assert promotions_args.json
    assert replan_args.command == "/replan"
    assert replan_args.max_items == 3
    assert brainstorm_args.command == "/brainstorm"
    assert brainstorm_args.goal == "build a tool"
    assert brainstorm_args.apply
    assert acceptance_args.command == "/acceptance"
    assert acceptance_args.suite == "nightly"
    assert acceptance_args.allow_fake
    assert acceptance_args.fail_on_trend_warning
    assert acceptance_args.warn_model_call_delta == 8
    assert acceptance_history_args.command == "/acceptance-history"
    assert acceptance_history_args.suite == "smoke"
    assert acceptance_history_args.limit == 2
    assert acceptance_history_args.warn_model_call_delta == 7
    assert acceptance_history_args.warn_duration_delta == 30
    assert acceptance_history_args.fail_on_warning
    assert acceptance_gate_args.command == "/acceptance-gate"
    assert acceptance_gate_args.suite == "core"
    assert acceptance_gate_args.min_scenarios == 4
    assert acceptance_gate_args.min_capabilities == 3
    assert acceptance_gate_args.require_tier == ["core"]
    assert acceptance_gate_args.allow_trend_warnings
    assert acceptance_gate_args.no_require_runtime_os
    assert capability_report_args.command == "/capability-report"
    assert capability_report_args.limit == 5
    assert evidence_bundle_args.command == "/evidence-bundle"
    assert evidence_bundle_args.max_runs == 3
    assert evidence_bundle_args.json
    assert weekly_report_args.command == "/weekly-report"
    assert weekly_report_args.week_id == "2026-W20"
    assert weekly_report_args.limit == 4
    assert roadmap_args.command == "/roadmap-update"
    assert roadmap_args.output.as_posix() == "docs/zh/自动路线图.md"
    assert daily_plan_args.command == "/daily-plan"
    assert daily_plan_args.max_model_calls == 10
    assert daily_run_args.command == "/daily-run"
    assert daily_run_args.execute
    assert daily_run_args.max_model_calls == 9
    assert daily_run_args.max_tool_calls == 11
    assert daily_run_args.max_runtime_minutes == 3
    assert daily_run_args.max_repair_attempts == 1
    assert daily_report_args.command == "/daily-report"
    assert long_run_args.command == "/long-run"
    assert long_run_args.cycle_id == "release-hardening"
    assert long_run_args.objective == "run a long autonomous task safely"
    assert long_run_args.execute
    assert run_parallel_args.parallel_disjoint_writes
    assert resume_parallel_args.parallel_disjoint_writes


def test_status_json_output_is_machine_readable(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["asteria", "status", "--root", str(tmp_path), "--json"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["root"] == str(tmp_path.resolve())
    assert payload["initialized"] is False


def test_gate_status_json_output_is_machine_readable(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["asteria", "gate-status", "--root", str(tmp_path), "--json"],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "missing_real_model_gate"
    assert payload["rollout_state"] == "blocked"
    assert payload["next_actions"]


def test_package_check_json_output_is_machine_readable(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(sys, "argv", ["asteria", "package-check", "--root", ".", "--json"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "0.1.0"
    assert payload["status"] == "pass"
    assert any(check["name"] == "console_script" for check in payload["checks"])
    assert any(check["name"] == "gray_command_modules" for check in payload["checks"])


def test_plugins_json_output_is_machine_readable(tmp_path: Path, monkeypatch, capsys) -> None:
    from asteria_runtime.commands.init_command import InitCommand

    InitCommand(tmp_path).run()
    monkeypatch.setattr(sys, "argv", ["asteria", "plugins", "--root", str(tmp_path), "--json"])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "0.1.0"
    assert payload["hook_policy"]["plugins_enabled"] is False
    assert payload["plugins"] == []


def test_acceptance_repair_options_parse() -> None:
    parser = build_parser()

    promote_args = parser.parse_args(["/acceptance", "--root", ".", "--promote-failures"])
    assert promote_args.promote_failures
    failed_only_args = parser.parse_args(["/acceptance", "--root", ".", "--failed-only"])
    assert failed_only_args.failed_only

    run_promoted_args = parser.parse_args(
        [
            "/acceptance",
            "--root",
            ".",
            "--promote-failures",
            "--run-promoted",
            "--rerun-promoted",
            "--promoted-run-max-iterations",
            "2",
            "--promoted-run-max-tasks-per-iteration",
            "3",
        ]
    )
    assert run_promoted_args.run_promoted
    assert run_promoted_args.rerun_promoted
    assert run_promoted_args.promoted_run_max_iterations == 2
    assert run_promoted_args.promoted_run_max_tasks_per_iteration == 3
