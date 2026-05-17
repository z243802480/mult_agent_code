from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_capability_feedback_advisor_returns_actionable_planner_hints(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    JsonStore(validator).write(
        agent_dir / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 2,
            "profiles": [
                {
                    "provider": "runtime",
                    "model": "medium-route",
                    "purpose": "coding",
                    "model_tier": "medium",
                    "total_calls": 2,
                    "success_calls": 1,
                    "failure_calls": 1,
                    "success_rate": 0.5,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_workers": 2,
                    "successful_workers": 2,
                    "failed_workers": 0,
                    "worker_success_rate": 1.0,
                    "validation_total": 2,
                    "validation_passed": 2,
                    "validation_pass_rate": 1.0,
                    "runtime_request_total": 2,
                    "runtime_request_rate": 1.0,
                    "runtime_request_types": {"scope_expansion": 2},
                    "merge_gate_blocks": 0,
                    "failure_types": {},
                    "recent_failures": [],
                    "recommended_action": "improve_planner_scope_before_scaling",
                },
                {
                    "provider": "runtime",
                    "model": "strong-route",
                    "purpose": "planning",
                    "model_tier": "strong",
                    "total_calls": 2,
                    "success_calls": 2,
                    "failure_calls": 0,
                    "success_rate": 1.0,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_workers": 0,
                    "successful_workers": 0,
                    "failed_workers": 0,
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
                    "recommended_action": "keep_route",
                },
            ],
        },
        "model_capability_profile",
    )

    hints = CapabilityFeedbackAdvisor(validator).planner_hints(agent_dir)

    assert len(hints) == 1
    assert hints[0]["purpose"] == "coding"
    assert "narrower read/write scope" in hints[0]["message"]
