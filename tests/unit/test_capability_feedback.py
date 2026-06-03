from __future__ import annotations

from pathlib import Path

from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
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
                    "min_success_rate_for_validation": 0.8,
                    "max_timeout_failures_for_validation": 1,
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
    assert guidance["provider_route_strategy"]["decision"] == "block_validation"
    assert (
        guidance["blocking"][0]["recommended_action"]
        == "block_validation_until_strong_goal_spec_stable"
    )
    assert "Do not widen small real-task validation" in guidance["recommended_actions"][0]


def test_provider_route_strategy_reports_fresh_window_with_recent_timeout(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    _write_provider_route_policy(agent_dir, validator)
    _write_goal_spec_profile(
        agent_dir,
        validator,
        total_calls=6,
        success_calls=4,
        success_rate=0.6667,
        failure_types={"timeout": 2},
    )
    calls_path = agent_dir / "runs" / "run-0001" / "model_calls.jsonl"
    store = JsonlStore(validator)
    store.append(
        calls_path,
        _model_call("modelcall-0001", "failure", "2026-06-02T10:00:00+08:00", "request timed out"),
        "model_call",
    )
    store.append(
        calls_path,
        _model_call("modelcall-0002", "success", "2026-06-02T10:01:00+08:00"),
        "model_call",
    )
    store.append(
        calls_path,
        _model_call("modelcall-0003", "success", "2026-06-02T10:02:00+08:00"),
        "model_call",
    )

    guidance = CapabilityFeedbackAdvisor(validator).route_guidance(agent_dir)

    strategy = guidance["provider_route_strategy"]
    fresh = strategy["fresh_evidence_window"]
    assert guidance["status"] == "blocked"
    assert strategy["decision"] == "block_validation"
    assert fresh["status"] == "blocked"
    assert fresh["total_calls"] == 3
    assert fresh["timeout_failures"] == 1
    assert fresh["success_rate"] == 0.6667
    assert "Recent window still contains provider failures" in strategy["reason"]


def test_provider_route_strategy_uses_clean_fresh_window_as_recovery_signal(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    _write_provider_route_policy(agent_dir, validator)
    _write_goal_spec_profile(
        agent_dir,
        validator,
        total_calls=8,
        success_calls=5,
        success_rate=0.625,
        failure_types={"timeout": 3},
    )
    calls_path = agent_dir / "runs" / "run-0001" / "model_calls.jsonl"
    store = JsonlStore(validator)
    for index in range(5):
        store.append(
            calls_path,
            _model_call(
                f"modelcall-000{index + 1}",
                "success",
                f"2026-06-02T10:0{index}:00+08:00",
            ),
            "model_call",
        )

    guidance = CapabilityFeedbackAdvisor(validator).route_guidance(agent_dir)

    strategy = guidance["provider_route_strategy"]
    fresh = strategy["fresh_evidence_window"]
    assert guidance["status"] == "review"
    assert strategy["decision"] == "retry_or_downgrade"
    assert fresh["status"] == "healthy"
    assert fresh["success_calls"] == 5
    assert "recent evidence is clean" in strategy["reason"]


def test_provider_route_strategy_uses_model_route_checks_as_recovery_signal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "glm-4.7")
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    _write_provider_route_policy(agent_dir, validator)
    _write_goal_spec_profile(
        agent_dir,
        validator,
        total_calls=8,
        success_calls=5,
        success_rate=0.625,
        failure_types={"timeout": 3},
    )
    store = JsonlStore(validator)
    for index in range(3):
        store.append(
            agent_dir / "model" / "model_route_checks.jsonl",
            {
                "schema_version": "0.1.0",
                "created_at": f"2026-06-02T10:0{index}:00+08:00",
                "tier": "strong",
                "purpose": "model_check",
                "provider": "zai",
                "model_name": "glm-4.7",
                "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
                "status": "success",
                "summary": "Model returned valid JSON for the health check prompt.",
                "failure_type": None,
                "deadline_ms": 120000,
                "duration_ms": 1000,
                "streaming": {
                    "requested": True,
                    "supported": True,
                    "mode": "streaming",
                    "chunk_count": 1,
                },
                "route_fallback": {},
            },
            "model_route_check",
        )

    guidance = CapabilityFeedbackAdvisor(validator).route_guidance(agent_dir)

    strategy = guidance["provider_route_strategy"]
    fresh = strategy["fresh_evidence_window"]
    assert guidance["status"] == "review"
    assert strategy["decision"] == "retry_or_downgrade"
    assert fresh["status"] == "healthy"
    assert fresh["total_calls"] == 3
    assert fresh["success_rate"] == 1.0
    assert fresh["latest_success_at"] == "2026-06-02T10:02:00+08:00"


def test_provider_route_strategy_does_not_block_on_stale_non_current_model(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "glm-5.1")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
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
                    "min_success_rate_for_validation": 0.8,
                    "max_timeout_failures_for_validation": 1,
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

    assert guidance["status"] == "healthy"
    assert guidance["provider_route_strategy"]["decision"] == "collect_evidence"
    assert guidance["provider_route_strategy"]["current_model"] == "glm-5.1"


def test_provider_route_strategy_matches_glm5_provider_alias_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AGENT_MODEL_STRONG_PROVIDER", "glm")
    monkeypatch.setenv("AGENT_MODEL_STRONG_NAME", "glm-5")
    monkeypatch.setenv("AGENT_MODEL_STRONG_API_KEY", "glm-key")
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    _write_provider_route_policy(agent_dir, validator)
    _write_goal_spec_profile(
        agent_dir,
        validator,
        model="glm-5.1",
        total_calls=3,
        success_calls=3,
        success_rate=1.0,
        failure_types={},
    )
    calls_path = agent_dir / "runs" / "run-0001" / "model_calls.jsonl"
    store = JsonlStore(validator)
    for index in range(3):
        store.append(
            calls_path,
            _model_call(
                f"modelcall-000{index + 1}",
                "success",
                f"2026-06-02T10:0{index}:00+08:00",
                model_name="glm-5.1",
            ),
            "model_call",
        )

    guidance = CapabilityFeedbackAdvisor(validator).route_guidance(agent_dir)

    strategy = guidance["provider_route_strategy"]
    assert strategy["decision"] == "continue_primary"
    assert strategy["current_model"] == "glm-5"
    assert strategy["model"] == "glm-5.1"
    assert strategy["fresh_evidence_window"]["status"] == "healthy"


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
                    "min_success_rate_for_validation": 0.8,
                    "max_timeout_failures_for_validation": 1,
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

    assert plan["decision"] == "block_validation"
    assert plan["selected_model_tier"] == "medium"
    assert plan["fast_path"]["task_kind"] == "doc_update"
    assert "downgrade_low_risk_goal_spec_to_medium" in plan["actions"]


def test_goal_spec_execution_plan_keeps_high_risk_goal_on_strong(tmp_path: Path) -> None:
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    _write_provider_route_policy(agent_dir, validator)
    _write_goal_spec_profile(
        agent_dir,
        validator,
        model="glm-5.1",
        total_calls=3,
        success_calls=3,
        success_rate=1.0,
        failure_types={},
    )

    plan = CapabilityFeedbackAdvisor(validator).goal_spec_execution_plan(
        agent_dir,
        "Fix auth permission handling and deploy to production.",
    )

    assert plan["decision"] == "continue_primary"
    assert plan["selected_model_tier"] == "strong"
    assert plan["fast_path"]["task_kind"] == "high_risk"
    assert "continue_primary_strong_goal_spec" in plan["actions"]


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


def _write_provider_route_policy(agent_dir: Path, validator: SchemaValidator) -> None:
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
                    "min_success_rate_for_validation": 0.8,
                    "max_timeout_failures_for_validation": 1,
                }
            },
            "commands": {},
        },
        "policy_config",
    )


def _write_goal_spec_profile(
    agent_dir: Path,
    validator: SchemaValidator,
    *,
    model: str = "glm-4.7",
    total_calls: int,
    success_calls: int,
    success_rate: float,
    failure_types: dict[str, int],
) -> None:
    JsonStore(validator).write(
        agent_dir / "model" / "capability_profile.json",
        {
            "schema_version": "0.1.0",
            "root": str(agent_dir.parent),
            "profile_count": 1,
            "profiles": [
                {
                    "provider": "zai",
                    "model": model,
                    "purpose": "goal_spec",
                    "model_tier": "strong",
                    "total_calls": total_calls,
                    "success_calls": success_calls,
                    "failure_calls": total_calls - success_calls,
                    "success_rate": success_rate,
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
                    "failure_types": failure_types,
                    "recent_failures": [],
                    "recommended_action": "keep_route",
                }
            ],
        },
        "model_capability_profile",
    )


def _model_call(
    model_call_id: str,
    status: str,
    created_at: str,
    summary: str = "model call succeeded",
    model_name: str = "glm-4.7",
) -> dict:
    return {
        "schema_version": "0.1.0",
        "model_call_id": model_call_id,
        "run_id": "run-0001",
        "purpose": "goal_spec",
        "model_provider": "zai",
        "model_name": model_name,
        "model_tier": "strong",
        "status": status,
        "created_at": created_at,
        "summary": summary,
        "deadline_ms": 120000,
        "duration_ms": 120000 if status == "failure" else 1000,
        "streaming": {
            "requested": True,
            "supported": status == "success",
            "mode": "streaming" if status == "success" else "streaming_failed",
            "chunk_count": 1 if status == "success" else 0,
            "error_type": None if status == "success" else "provider_error",
        },
    }
