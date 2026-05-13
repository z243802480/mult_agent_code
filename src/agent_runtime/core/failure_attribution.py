from __future__ import annotations

import json
from typing import Any


TRANSIENT_FAILURES = {"rate_limited", "server_error", "timeout", "network"}


def classify_failure_attribution(scenario: dict[str, Any]) -> dict[str, Any]:
    if scenario.get("ok"):
        return {"category": "none", "retryable": False, "confidence": 1.0, "signals": []}
    for attempt in scenario.get("attempts", []) if isinstance(scenario.get("attempts"), list) else []:
        if not isinstance(attempt, dict):
            continue
        failure_type = attempt.get("failure_type")
        if failure_type in TRANSIENT_FAILURES:
            return {
                "category": "provider_transient",
                "retryable": True,
                "confidence": 0.9,
                "signals": [str(failure_type)],
            }

    text = "\n".join(
        [
            str(scenario.get("failure_summary") or ""),
            str(scenario.get("stderr") or ""),
            str(scenario.get("stdout") or ""),
            str(scenario.get("stderr_tail") or ""),
            str(scenario.get("stdout_tail") or ""),
            json.dumps(scenario.get("summary") or {}, ensure_ascii=False),
            json.dumps(scenario.get("attempts") or [], ensure_ascii=False),
        ]
    ).lower()
    rules = [
        (
            "pending_decision",
            ["pending decisions", "decision-", "current phase: decision"],
            False,
            0.9,
        ),
        (
            "model_output_invalid_json",
            ["invalid json", "not json", "jsondecode", "schema validation", "malformed json"],
            False,
            0.75,
        ),
        (
            "tool_call_invalid",
            [
                "tool is not allowed",
                "unknown_tool",
                "policy blocked",
                "shell policy",
                "command rejected",
            ],
            False,
            0.8,
        ),
        (
            "verification_missing",
            ["required verification was not provided", "no verification", "verification missing"],
            False,
            0.8,
        ),
        (
            "plan_quality_failed",
            ["task plan quality failed", "task_plan_quality_gate", "low-quality plan"],
            False,
            0.85,
        ),
        (
            "runtime_recovery_failed",
            ["recovery-resume failed", "resume failed", "run did not recover"],
            False,
            0.75,
        ),
        (
            "code_bug",
            [
                "assertionerror",
                "nonzero_exit",
                "expected output file",
                "tests failed",
                "traceback",
            ],
            False,
            0.65,
        ),
    ]
    for category, markers, retryable, confidence in rules:
        matched = [marker for marker in markers if marker in text]
        if matched:
            return {
                "category": category,
                "retryable": retryable,
                "confidence": confidence,
                "signals": matched[:5],
            }
    return {
        "category": "scenario_validation_failure",
        "retryable": False,
        "confidence": 0.5,
        "signals": ["no specific classifier matched"],
    }
