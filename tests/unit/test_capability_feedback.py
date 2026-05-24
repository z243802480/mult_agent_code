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
    guidance = CapabilityFeedbackAdvisor(validator).route_guidance(agent_dir)

    assert len(hints) == 1
    assert hints[0]["purpose"] == "coding"
    assert "narrower read/write scope" in hints[0]["message"]
    assert guidance["status"] == "review"
    assert guidance["review"][0]["purpose"] == "coding"
    assert "smaller scoped tasks" in guidance["recommended_actions"][1]


def test_provider_route_strategy_blocks_unstable_strong_goal_spec(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    JsonStore(validator).write(
        agent_dir / "policies.json",
        {
            "schema_version": "0.3.0",
            "decision_granularity": "balanced",
            "budgets": {
                "max_model_calls_per_goal": 60,
                "max_tool_calls_per_goal": 120,
                "max_total_minutes_per_goal": 30,
                "max_iterations_per_goal": 8,
                "max_repair_attempts_total": 5,
                "max_repair_attempts_per_task": 2,
                "max_replans_per_task": 2,
                "max_research_calls": 5,
                "max_user_decisions": 5,
            },
            "context": {
                "compaction_threshold": 0.75,
                "hard_stop_threshold": 0.9,
                "phase_boundary_compaction": True,
                "handoff_compaction": True,
            },
            "permissions": {
                "allow_network": False,
                "allow_shell": True,
                "allow_destructive_shell": False,
                "allow_global_package_install": False,
                "allow_secret_file_read": False,
                "allow_remote_push": False,
                "allow_deploy": False,
                "allow_restore_delete_created_files": True,
            },
            "protected_paths": [".env", "secrets/"],
            "hooks": {
                "enabled": True,
                "plugins_enabled": False,
                "allowed_hook_names": ["before_worker", "after_worker"],
                "redacted_data_keys": ["api_key"],
                "handler_timeout_ms": 1000,
            },
            "promotion": {
                "manual_approval_default": False,
                "release_blocking_statuses": ["pending_manual_approval"],
                "max_pending_release_promotions": 0,
                "max_blocked_release_promotions": 0,
            },
            "feature_flags": {},
            "capability_flags": {},
            "model_routing": {"goal_spec": "strong"},
            "provider_route_strategy": {
                "strong_goal_spec": {
                    "primary_model": "glm-5",
                    "cost_saver_model": "glm-4.7",
                    "min_calls_before_enforcement": 3,
                    "min_success_rate_for_gray": 0.8,
                    "max_timeout_failures_for_gray": 1,
                }
            },
            "commands": {},
        },
        "policy_config",
    )
    JsonStore(validator).write(
        agent_dir / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "zai",
                    "model": "glm-4.7",
                    "purpose": "goal_spec",
                    "model_tier": "strong",
                    "total_calls": 5,
                    "success_calls": 3,
                    "failure_calls": 2,
                    "success_rate": 0.6,
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
                    "failure_types": {"timeout": 2},
                    "recent_failures": ["stream deadline exceeded"],
                    "recommended_action": "keep_route",
                }
            ],
        },
        "model_capability_profile",
    )

    guidance = CapabilityFeedbackAdvisor(validator).route_guidance(agent_dir)

    assert guidance["status"] == "blocked"
    assert guidance["provider_route_strategy"]["decision"] == "block_gray"
    assert guidance["blocking"][0]["recommended_action"] == "block_gray_until_strong_goal_spec_stable"
    assert "Do not widen small real-task gray" in guidance["recommended_actions"][0]


def test_goal_spec_execution_plan_downgrades_low_risk_docs_when_route_blocked(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    JsonStore(validator).write(
        agent_dir / "policies.json",
        {
            "schema_version": "0.3.0",
            "decision_granularity": "balanced",
            "budgets": {
                "max_model_calls_per_goal": 60,
                "max_tool_calls_per_goal": 120,
                "max_total_minutes_per_goal": 30,
                "max_iterations_per_goal": 8,
                "max_repair_attempts_total": 5,
                "max_repair_attempts_per_task": 2,
                "max_replans_per_task": 2,
                "max_research_calls": 5,
                "max_user_decisions": 5,
            },
            "context": {
                "compaction_threshold": 0.75,
                "hard_stop_threshold": 0.9,
                "phase_boundary_compaction": True,
                "handoff_compaction": True,
            },
            "permissions": {
                "allow_network": False,
                "allow_shell": True,
                "allow_destructive_shell": False,
                "allow_global_package_install": False,
                "allow_secret_file_read": False,
                "allow_remote_push": False,
                "allow_deploy": False,
                "allow_restore_delete_created_files": True,
            },
            "protected_paths": [],
            "hooks": {
                "enabled": True,
                "plugins_enabled": False,
                "allowed_hook_names": ["before_worker", "after_worker"],
                "redacted_data_keys": ["api_key"],
                "handler_timeout_ms": 1000,
            },
            "promotion": {
                "manual_approval_default": False,
                "release_blocking_statuses": ["pending_manual_approval"],
                "max_pending_release_promotions": 0,
                "max_blocked_release_promotions": 0,
            },
            "feature_flags": {},
            "capability_flags": {},
            "model_routing": {"goal_spec": "strong"},
            "provider_route_strategy": {
                "strong_goal_spec": {
                    "primary_model": "glm-5",
                    "cost_saver_model": "glm-4.7",
                    "min_calls_before_enforcement": 3,
                    "min_success_rate_for_gray": 0.8,
                    "max_timeout_failures_for_gray": 1,
                }
            },
            "commands": {},
        },
        "policy_config",
    )
    JsonStore(validator).write(
        agent_dir / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "zai",
                    "model": "glm-4.7",
                    "purpose": "goal_spec",
                    "model_tier": "strong",
                    "total_calls": 5,
                    "success_calls": 3,
                    "failure_calls": 2,
                    "success_rate": 0.6,
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
                    "failure_types": {"timeout": 1},
                    "recent_failures": ["stream deadline exceeded"],
                    "recommended_action": "keep_route",
                }
            ],
        },
        "model_capability_profile",
    )

    plan = CapabilityFeedbackAdvisor(validator).goal_spec_execution_plan(
        agent_dir,
        "Update README documentation for local setup.",
    )

    assert plan["decision"] == "block_gray"
    assert plan["selected_model_tier"] == "medium"
    assert "downgrade_low_risk_goal_spec_to_medium" in plan["actions"]


def test_capability_feedback_uses_real_provider_matrix_signals(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    JsonStore(validator).write(
        agent_dir / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(tmp_path),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "openai-compatible",
                    "model": "matrix-model",
                    "purpose": "task_execution",
                    "model_tier": "medium",
                    "total_calls": 4,
                    "success_calls": 4,
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
                    "route_signal_total": 0,
                    "route_signal_success": 0,
                    "route_signal_failure": 0,
                    "route_signal_success_rate": 0.0,
                    "route_task_kinds": {},
                    "route_decisions": {},
                    "recent_route_signals": [],
                    "matrix_signal_total": 3,
                    "matrix_signal_success": 1,
                    "matrix_signal_failure": 2,
                    "matrix_signal_success_rate": 0.3333,
                    "matrix_task_kinds": {"bug_fix": 2, "doc_update": 1},
                    "matrix_routes": {"repair": 2, "artifact_creation": 1},
                    "recent_matrix_signals": ["bug_fix:repair:failure"],
                    "merge_gate_blocks": 0,
                    "failure_types": {},
                    "recent_failures": [],
                    "recommended_action": "keep_route",
                }
            ],
        },
        "model_capability_profile",
    )

    guidance = CapabilityFeedbackAdvisor(validator).route_guidance(agent_dir)

    assert guidance["status"] == "blocked"
    assert guidance["blocking"][0]["recommended_action"] == (
        "review_real_provider_matrix_before_scaling"
    )
    assert guidance["blocking"][0]["matrix_signal_success_rate"] == 0.3333
    assert "bug_fix/repair" in guidance["blocking"][0]["message"]
    assert "Do not widen real-provider matrix routes" in guidance["recommended_actions"][0]
