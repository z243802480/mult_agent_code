from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.real_model_acceptance import (
    SCENARIOS,
    SUITES,
    TimeoutBudget,
    aggregate_results,
    apply_timeout_budget_env,
    classify_acceptance_subprocess_failure,
    gray_ready,
)


def test_real_model_acceptance_core_includes_safe_file_renamer() -> None:
    assert "safe_file_renamer" in SCENARIOS
    assert "safe_file_renamer" in SUITES["core"]
    assert "safe_file_renamer" in SUITES["nightly"]
    assert "multi_file_todo_cli" in SUITES["core"]
    assert "config_driven_report" in SUITES["core"]
    assert SUITES["gray"] == [
        "gray_file_artifact",
        "gray_multi_file_scope",
        "gray_debug_repair",
        "runtime_request_resume",
    ]
    assert SCENARIOS["gray_file_artifact"].tier == "gray"
    assert SCENARIOS["gray_multi_file_scope"].capability == "gray_multi_file_scope"
    assert SCENARIOS["gray_debug_repair"].setup_files
    assert "docs_code_sync" in SUITES["advanced"]
    assert SCENARIOS["multi_file_todo_cli"].capability == "multi_file_change"


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
    assert summary["gray_ready"] is False
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


def test_real_model_acceptance_timeout_budget_flows_to_provider_env() -> None:
    budget = TimeoutBudget(600)
    env = {"AGENT_MODEL_STRONG_TIMEOUT_SECONDS": "180"}

    apply_timeout_budget_env(env, budget)

    assert budget.as_dict() == {
        "scenario_seconds": 600,
        "subprocess_seconds": 600,
        "smoke_command_seconds": 570,
        "review_seconds": 90,
        "provider_call_seconds": 90,
        "cheap_provider_call_seconds": 45,
    }
    assert env["AGENT_MODEL_STRONG_TIMEOUT_SECONDS"] == "180"
    assert env["AGENT_MODEL_MEDIUM_TIMEOUT_SECONDS"] == "90"
    assert env["AGENT_MODEL_CHEAP_TIMEOUT_SECONDS"] == "45"
    assert env["AGENT_MODEL_MAX_RETRIES"] == "1"


def test_gray_ready_requires_passing_results_and_strong_medium_route_evidence() -> None:
    results = [
        {
            "scenario": "gray_file_artifact",
            "capability": "gray_artifact_creation",
            "tier": "gray",
            "ok": True,
            "route_evidence": {
                "available": True,
                "strong_used": True,
                "medium_used": True,
                "providers_by_tier": {"strong": ["zai"], "medium": ["minimax"]},
            },
            "summary": {"diagnostics": {"model_calls": 2, "tool_calls": 1}},
        },
        {
            "scenario": "gray_multi_file_scope",
            "capability": "gray_multi_file_scope",
            "tier": "gray",
            "ok": True,
            "route_evidence": {
                "available": True,
                "strong_used": True,
                "medium_used": True,
                "providers_by_tier": {"strong": ["zai"], "medium": ["minimax"]},
            },
            "summary": {"diagnostics": {"model_calls": 3, "tool_calls": 2}},
        },
    ]

    aggregate = aggregate_results(results)

    assert gray_ready("gray", aggregate) is True
    assert aggregate["route_evidence"]["strong_used"] is True
    assert aggregate["route_evidence"]["medium_used"] is True
    assert aggregate["route_evidence"]["providers_by_tier"]["strong"] == ["zai"]
    assert aggregate["route_evidence"]["providers_by_tier"]["medium"] == ["minimax"]


def test_gray_ready_blocks_missing_medium_route_evidence() -> None:
    aggregate = aggregate_results(
        [
            {
                "scenario": "gray_file_artifact",
                "capability": "gray_artifact_creation",
                "tier": "gray",
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

    assert gray_ready("gray", aggregate) is False
    assert aggregate["route_evidence"]["scenarios_missing_medium"] == ["gray_file_artifact"]
