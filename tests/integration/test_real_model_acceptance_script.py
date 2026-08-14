from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from asteria_runtime import real_model_acceptance as acceptance

from scripts.real_model_acceptance import (
    SCENARIOS,
    SUITES,
    TimeoutBudget,
    aggregate_results,
    apply_timeout_budget_env,
    classify_acceptance_subprocess_failure,
    validation_ready,
)

pytestmark = [
    pytest.mark.real_provider,
    pytest.mark.real_provider_validation,
    pytest.mark.real_provider_core,
]


def test_real_model_acceptance_detects_current_source_checkout() -> None:
    source_root = acceptance._source_checkout_root()

    assert source_root == Path.cwd() / "src"
    assert acceptance._merge_pythonpath(str(source_root), "existing") == (
        f"{source_root}{os.pathsep}existing"
    )


def test_real_model_acceptance_core_includes_safe_file_renamer() -> None:
    assert "safe_file_renamer" in SCENARIOS
    assert "safe_file_renamer" in SUITES["core"]
    assert "safe_file_renamer" in SUITES["nightly"]
    assert "multi_file_todo_cli" in SUITES["core"]
    assert "config_driven_report" in SUITES["core"]
    assert SUITES["validation"] == [
        "validation_file_artifact",
        "validation_multi_file_scope",
        "validation_debug_repair",
        "validation_doc_update",
        "validation_small_cli",
        "validation_subagent_delegation",
        "validation_refactor",
        "runtime_independent_verification",
    ]


def test_real_model_acceptance_suites_only_reference_known_scenarios() -> None:
    for suite_name, names in SUITES.items():
        for name in names:
            assert name in SCENARIOS, f"{suite_name!r} suite references unknown scenario {name!r}"
    assert SCENARIOS["validation_doc_update"].tier == "validation"
    assert SCENARIOS["validation_doc_update"].expected_file == "docs/README.md"
    assert SCENARIOS["validation_small_cli"].tier == "validation"
    assert SCENARIOS["validation_small_cli"].expected_file == "greet.py"
    assert SCENARIOS["validation_refactor"].tier == "validation"
    assert SCENARIOS["validation_refactor"].setup_files
    assert "shapes.py" in SCENARIOS["validation_refactor"].setup_files
    assert SCENARIOS["validation_file_artifact"].tier == "validation"
    assert SCENARIOS["validation_multi_file_scope"].capability == "validation_multi_file_scope"
    multi_file_goal = SCENARIOS["validation_multi_file_scope"].goal.lower()
    assert "do not delete files" in multi_file_goal
    assert "destructive shell" in multi_file_goal
    assert SCENARIOS["validation_debug_repair"].setup_files
    assert "docs_code_sync" in SUITES["advanced"]
    assert SCENARIOS["multi_file_todo_cli"].capability == "multi_file_change"
    password_goal = SCENARIOS["password_cli"].goal.lower()
    assert "ampersands" in password_goal
    assert "success-path" in password_goal
    assert "&" not in password_goal
    markdown = SCENARIOS["markdown_kb"]
    assert markdown.setup_files
    assert "sample_docs/intro.md" in markdown.setup_files
    assert "sample_docs/nested/usage.md" in markdown.setup_files
    assert "sample_docs" in markdown.goal
    assert "do not run negative-case" in markdown.goal.lower()
    assert "unix-only" in markdown.goal.lower()
    safe_renamer = SCENARIOS["safe_file_renamer"]
    assert safe_renamer.setup_files
    assert "rename_plan.json" in safe_renamer.setup_files
    safe_goal = safe_renamer.goal.lower()
    assert "do not create extra json test files" in safe_goal
    assert "do not run negative-case" in safe_goal
    assert "unix-only" in safe_goal
    report_goal = SCENARIOS["config_driven_report"].goal.lower()
    assert "do not create extra fixture files" in report_goal
    assert "do not run negative-case" in report_goal
    assert "unix-only" in report_goal


def test_real_model_acceptance_runs_offline_suite_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "summary.json"
    history_path = tmp_path / "history.jsonl"
    env = os.environ.copy()
    env.pop("AGENT_MODEL_PROVIDER", None)
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    command = [
        sys.executable,
        "scripts/real_model_acceptance.py",
        "--suite",
        "offline",
        "--root",
        str(tmp_path / "acceptance"),
        "--summary-json",
        str(summary_path),
        "--history-jsonl",
        str(history_path),
        "--allow-fake",
    ]
    completed = subprocess.run(
        command,
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        command,
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Real model acceptance passed" in completed.stdout
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["suite"] == "offline"
    assert summary["created_at"]
    assert summary["aggregate"]["total"] == 1
    assert summary["aggregate"]["passed"] == 1
    assert summary["aggregate"]["failed"] == 0
    assert summary["aggregate"]["model_calls"] > 0
    assert summary["aggregate"]["tool_calls"] > 0
    assert summary["scenario_metadata"][0]["capability"] == "offline_artifact"
    assert summary["aggregate"]["capabilities"]["offline_artifact"]["passed"] == 1
    assert summary["validation_ready"] is False
    assert [scenario["scenario"] for scenario in summary["scenarios"]] == ["offline_artifact"]
    assert summary["scenarios"][0]["duration_seconds"] >= 0
    assert summary["scenarios"][0]["attempts"][0]["attempt"] == 1
    assert summary["scenarios"][0]["attempts"][0]["returncode"] == 0
    assert summary["scenarios"][0]["summary"]["run_id"].startswith("run-")
    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(history) == 2
    assert history[0]["trend"]["previous"] is None
    assert history[1]["trend"]["previous"]["aggregate"]["total"] == 1
    assert "model_calls" in history[1]["trend"]["deltas"]


def test_real_model_acceptance_rejects_fake_for_real_scenarios(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_acceptance.py",
            "--scenario",
            "file_smoke",
            "--root",
            str(tmp_path / "acceptance"),
            "--allow-fake",
        ],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Fake/offline acceptance only supports offline_artifact, decision_point" in completed.stderr


def test_real_model_acceptance_runs_decision_point_without_model(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_acceptance.py",
            "--scenario",
            "decision_point",
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

    assert "Real model acceptance passed" in completed.stdout
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    scenario = summary["scenarios"][0]
    assert summary["aggregate"]["passed"] == 1
    assert summary["aggregate"]["model_calls"] == 0
    assert summary["aggregate"]["capabilities"]["decision_memory"]["passed"] == 1
    assert scenario["scenario"] == "decision_point"
    assert scenario["ok"] is True
    assert scenario["summary"]["resolved_decision_id"] == "decision-0001"
    assert scenario["summary"]["resolved_status"] == "resolved"
    assert scenario["summary"]["selected_option_id"] == "cli"


def test_real_model_acceptance_runs_memory_lesson_reuse_without_model(
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "summary.json"
    env = os.environ.copy()
    env["AGENT_MODEL_PROVIDER"] = "fake"
    env["PYTHONPATH"] = str(Path.cwd() / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/real_model_acceptance.py",
            "--scenario",
            "memory_lesson_reuse",
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

    assert "Real model acceptance passed" in completed.stdout
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    scenario = summary["scenarios"][0]
    assert scenario["scenario"] == "memory_lesson_reuse"
    assert scenario["summary"]["lesson_reused"] is True
    assert summary["aggregate"]["capabilities"]["memory_effectiveness"]["passed"] == 1


def test_real_model_acceptance_writes_incremental_summary_on_partial_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "summary.json"
    args = Namespace(
        suite="offline",
        scenario=["offline_artifact", "decision_point"],
        root=tmp_path / "acceptance",
        summary_json=summary_path,
        history_jsonl=None,
        python=sys.executable,
        allow_fake=True,
        run_attempts=1,
        model_max_retries=1,
        scenario_timeout_seconds=600,
        cleanup=False,
        reuse_workspace=False,
    )

    def fake_run_scenario(
        _args: Namespace,
        workspace_root: Path,
        scenario: acceptance.AcceptanceScenario,
    ) -> dict[str, object]:
        if scenario.name == "decision_point":
            raise RuntimeError("simulated interruption")
        return {
            "scenario": scenario.name,
            "capability": scenario.capability,
            "tier": scenario.tier,
            "ok": True,
            "workspace": str(workspace_root / scenario.name),
            "duration_seconds": 0.1,
            "summary": {"diagnostics": {"model_calls": 0, "tool_calls": 0}},
        }

    monkeypatch.setattr(acceptance, "run_scenario", fake_run_scenario)

    with pytest.raises(SystemExit):
        acceptance.run_from_args(args)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert summary["complete"] is False
    assert summary["error"] == "simulated interruption"
    assert [item["scenario"] for item in summary["scenarios"]] == ["offline_artifact"]
    assert [item["scenario"] for item in summary["scenario_metadata"]] == [
        "offline_artifact",
        "decision_point",
    ]


def test_real_model_acceptance_cleans_workspace_before_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = Namespace(
        suite="validation",
        scenario=["validation_file_artifact"],
        root=tmp_path / "acceptance",
        summary_json=None,
        history_jsonl=None,
        python=sys.executable,
        allow_fake=False,
        run_attempts=2,
        model_max_retries=1,
        scenario_timeout_seconds=600,
        cleanup=False,
        reuse_workspace=False,
    )
    calls = 0

    def fake_run_with_heartbeat(
        command: list[str],
        *,
        cwd: Path,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del command, kwargs
        nonlocal calls
        calls += 1
        artifact = cwd / "validation_runtime.txt"
        summary_path = cwd / "acceptance_summary.json"
        if calls == 1:
            artifact.write_text("stale artifact from failed attempt\n", encoding="utf-8")
            summary_path.write_text(
                json.dumps(
                    {
                        "workspace": str(cwd),
                        "run_id": "run-1",
                        "outcome": "failed",
                        "diagnostics": {"failure_type": "SmokeFailure"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess([], 1, "", "temporarily unavailable")

        assert not artifact.exists()
        artifact.write_text("validation route artifact ok\n", encoding="utf-8")
        summary_path.write_text(
            json.dumps(
                {
                    "workspace": str(cwd),
                    "run_id": "run-2",
                    "outcome": "passed",
                    "diagnostics": {"model_calls": 1, "tool_calls": 1},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess([], 0, "ok", "")

    monkeypatch.setattr(acceptance, "run_with_heartbeat", fake_run_with_heartbeat)

    result = acceptance.run_scenario(
        args,
        args.root,
        acceptance.SCENARIOS["validation_file_artifact"],
    )

    assert calls == 2
    assert result["ok"] is True
    assert result["summary"]["run_id"] == "run-2"
    assert result["attempts"][0]["retryable"] is True


def test_acceptance_timeout_records_spine_native_evidence(tmp_path: Path) -> None:
    # RA7b: a scenario timeout is captured as a spine-native user_progress validation event
    # (the FSM agent_loop_decision writer was retired with the round loop), carrying the
    # recommended recovery command so an operator can continue from it.
    workspace = tmp_path / "validation_small_cli"
    run_dir = workspace / ".asteria" / "runs" / "run-0001"
    run_dir.mkdir(parents=True)
    (workspace / ".asteria" / "current_session.json").write_text(
        json.dumps({"session_id": "run-0001"}),
        encoding="utf-8",
    )
    (run_dir / "task_plan.json").write_text(
        json.dumps({"tasks": [{"task_id": "task-0001"}]}),
        encoding="utf-8",
    )

    acceptance.record_acceptance_timeout_evidence(
        workspace=workspace,
        scenario=acceptance.SCENARIOS["validation_small_cli"],
        reason="Scenario timed out after 360s.",
        stderr="recovery-review timed out",
    )

    events = [
        json.loads(line)
        for line in (run_dir / "user_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    timeout_events = [
        event
        for event in events
        if ((event.get("data") or {}).get("validation") or {}).get("kind") == "acceptance_timeout"
    ]
    assert timeout_events, "expected an acceptance_timeout validation event"
    validation = timeout_events[-1]["data"]["validation"]
    assert validation["scenario"] == "validation_small_cli"
    assert validation["task_id"] == "task-0001"
    assert validation["recommended_action"] == "repair"
    assert validation["recommended_command"] == "debug"


def test_real_model_acceptance_classifies_retryable_subprocess_failures() -> None:
    completed = subprocess.CompletedProcess(
        ["asteria"],
        1,
        stdout="",
        stderr="provider returned 429 too many requests",
    )

    retryable, failure_type = classify_acceptance_subprocess_failure(completed)

    assert retryable is True
    assert failure_type == "rate_limited"


def test_real_model_acceptance_classifies_remote_close_as_retryable() -> None:
    completed = subprocess.CompletedProcess(
        ["asteria"],
        1,
        stdout="",
        stderr="Remote end closed connection without response",
    )

    retryable, failure_type = classify_acceptance_subprocess_failure(completed)

    assert retryable is True
    assert failure_type == "network"


def test_real_model_acceptance_classifies_empty_response_as_retryable() -> None:
    completed = subprocess.CompletedProcess(
        ["asteria"],
        1,
        stdout="",
        stderr="Real model smoke failed: provider returned empty response content",
    )

    retryable, failure_type = classify_acceptance_subprocess_failure(completed)

    assert retryable is True
    assert failure_type == "empty_response"


def test_real_model_acceptance_timeout_budget_flows_to_provider_env() -> None:
    budget = TimeoutBudget(600)
    env = {"AGENT_MODEL_STRONG_TIMEOUT_SECONDS": "180"}

    apply_timeout_budget_env(env, budget)

    budget_dict = budget.as_dict()
    assert {
        key: budget_dict[key]
        for key in [
            "scenario_seconds",
            "subprocess_seconds",
            "smoke_command_seconds",
            "review_seconds",
            "provider_call_seconds",
            "cheap_provider_call_seconds",
        ]
    } == {
        "scenario_seconds": 600,
        "subprocess_seconds": 600,
        "smoke_command_seconds": 570,
        "review_seconds": 90,
        "provider_call_seconds": 90,
        "cheap_provider_call_seconds": 45,
    }
    assert budget_dict["run_seconds"] == 570
    assert budget_dict["recovery_seconds"] == 200
    assert budget_dict["stream_idle_timeout_seconds"] == 30
    assert env["AGENT_MODEL_STRONG_TIMEOUT_SECONDS"] == "180"
    assert env["AGENT_MODEL_MEDIUM_TIMEOUT_SECONDS"] == "90"
    assert env["AGENT_MODEL_CHEAP_TIMEOUT_SECONDS"] == "45"
    assert env["AGENT_MODEL_MAX_RETRIES"] == "1"
    assert env["AGENT_MODEL_SMOKE_RECOVERY_TIMEOUT_SECONDS"] == "200"


def test_timed_out_scenario_returns_route_evidence_from_partial_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = acceptance.AcceptanceScenario(
        name="validation_multi_file_scope",
        capability="validation_multi_file_scope",
        tier="validation",
        goal="Create a small multi-file artifact.",
        expected_file="notes.py",
        expected_text="notes",
        max_iterations=3,
    )

    def fake_run_with_heartbeat(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        workspace = Path(str(kwargs["cwd"]))
        run_id = "run-timeout-0001"
        run_dir = workspace / ".asteria" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (workspace / ".asteria" / "current_session.json").write_text(
            json.dumps({"session_id": run_id}),
            encoding="utf-8",
        )
        (run_dir / "model_calls.jsonl").write_text(
            json.dumps(
                {
                    "schema_version": "0.1.0",
                    "model_call_id": "call-0001",
                    "run_id": run_id,
                    "model_name": "glm-4.7",
                    "model_provider": "zai",
                    "model_tier": "strong",
                    "purpose": "goal_spec",
                    "status": "success",
                    "created_at": "2026-08-03T10:00:00+08:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        raise subprocess.TimeoutExpired(
            cmd=["asteria"],
            timeout=30,
            output="",
            stderr="[asteria-heartbeat] last_event=model_route_selected route=strong",
        )

    monkeypatch.setattr(acceptance, "run_with_heartbeat", fake_run_with_heartbeat)

    result = acceptance.run_scenario(
        Namespace(
            python=sys.executable,
            allow_fake=False,
            run_attempts=1,
            model_max_retries=1,
            scenario_timeout_seconds=30,
            reuse_workspace=False,
        ),
        tmp_path,
        scenario,
    )

    assert result["ok"] is False
    assert result["route_evidence"]["available"] is True
    assert result["route_evidence"]["run_id"] == "run-timeout-0001"
    assert result["route_evidence"]["strong_used"] is True
    assert result["route_evidence"]["medium_used"] is False


def test_aggregate_route_evidence_includes_failed_scenarios() -> None:
    aggregate = aggregate_results(
        [
            {
                "scenario": "gray_multi_file_scope",
                "capability": "gray_multi_file_scope",
                "tier": "gray",
                "ok": False,
                "route_evidence": {
                    "available": True,
                    "strong_used": True,
                    "medium_used": False,
                    "providers_by_tier": {"strong": ["zai"]},
                },
                "summary": {"diagnostics": {}},
            }
        ]
    )

    route = aggregate["route_evidence"]
    assert route["scenarios_with_route_evidence"] == ["gray_multi_file_scope"]
    assert route["scenarios_missing_medium"] == ["gray_multi_file_scope"]
    assert route["providers_by_tier"]["strong"] == ["zai"]


def test_validation_ready_requires_passing_results_and_strong_medium_route_evidence() -> None:
    results = [
        {
            "scenario": scenario,
            "capability": SCENARIOS[scenario].capability,
            "tier": SCENARIOS[scenario].tier,
            "ok": True,
            "route_evidence": {
                "available": True,
                "strong_used": True,
                "medium_used": True,
                "providers_by_tier": {"strong": ["zai"], "medium": ["minimax"]},
            },
            "summary": {"diagnostics": {"model_calls": 2, "tool_calls": 1}},
        }
        for scenario in SUITES["validation"]
    ]

    aggregate = aggregate_results(results, scenario_metadata_for_names(SUITES["validation"]))

    assert (
        validation_ready(
            "validation",
            aggregate,
            scenario_metadata=scenario_metadata_for_names(SUITES["validation"]),
        )
        is True
    )
    assert aggregate["route_evidence"]["strong_used"] is True
    assert aggregate["route_evidence"]["medium_used"] is True
    assert aggregate["route_evidence"]["providers_by_tier"]["strong"] == ["zai"]
    assert aggregate["route_evidence"]["providers_by_tier"]["medium"] == ["minimax"]


def test_validation_ready_blocks_partial_validation_subset() -> None:
    subset = ["validation_file_artifact", "validation_multi_file_scope"]
    results = [
        {
            "scenario": scenario,
            "capability": SCENARIOS[scenario].capability,
            "tier": SCENARIOS[scenario].tier,
            "ok": True,
            "route_evidence": {
                "available": True,
                "strong_used": True,
                "medium_used": True,
                "providers_by_tier": {"strong": ["zai"], "medium": ["minimax"]},
            },
            "summary": {"diagnostics": {"model_calls": 3, "tool_calls": 2}},
        }
        for scenario in subset
    ]

    aggregate = aggregate_results(results, scenario_metadata_for_names(subset))

    assert (
        validation_ready(
            "validation",
            aggregate,
            scenario_metadata=scenario_metadata_for_names(subset),
            requested_scenarios=subset,
        )
        is False
    )


def test_validation_ready_blocks_missing_medium_route_evidence() -> None:
    aggregate = aggregate_results(
        [
            {
                "scenario": "validation_file_artifact",
                "capability": "validation_artifact_creation",
                "tier": "validation",
                "ok": True,
                "route_evidence": {
                    "available": True,
                    "strong_used": True,
                    "medium_used": False,
                    "providers_by_tier": {"strong": ["zai"]},
                },
                "summary": {"diagnostics": {}},
            }
        ]
    )

    assert validation_ready("validation", aggregate) is False
    assert aggregate["route_evidence"]["scenarios_missing_medium"] == ["validation_file_artifact"]


def scenario_metadata_for_names(names: list[str]) -> list[dict[str, str]]:
    return [
        {
            "scenario": name,
            "capability": SCENARIOS[name].capability,
            "tier": SCENARIOS[name].tier,
            "kind": SCENARIOS[name].kind,
        }
        for name in names
    ]
