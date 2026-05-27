from pathlib import Path

import pytest

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_profile import (
    AccountProfile,
    BudgetProfile,
    ContextMount,
    ModelProfile,
    RuntimeProfile,
    SandboxProfile,
    ToolPermissionProfile,
)
from asteria_runtime.core.runtime_profile_builder import RuntimeProfileBuilder
from asteria_runtime.core.runtime_request import RuntimeRequest
from asteria_runtime.core.validation_result import ValidationResult
from asteria_runtime.core.worker import WorkerCost, WorkerInvocation, WorkerResult
from asteria_runtime.storage.schema_validator import SchemaValidator


SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_runtime_profiles_validate_against_schemas() -> None:
    validator = SchemaValidator(SCHEMA_DIR)

    validator.validate(
        "model_profile",
        ModelProfile(
            model_profile_id="model-profile-0001",
            purpose="coding",
            provider="openai_compatible",
            model_name="example-coder-model",
            model_tier="medium",
        ).to_dict(),
    )
    validator.validate(
        "tool_permission_profile",
        ToolPermissionProfile(
            tool_permission_profile_id="tool-profile-0001",
            allowed_tools=["read_file", "apply_patch", "run_tests"],
            read_scope=["src/", "tests/"],
            write_scope=["src/asteria_runtime/", "tests/"],
        ).to_dict(),
    )
    validator.validate(
        "account_profile",
        AccountProfile(
            account_profile_id="account-profile-0001",
            provider="openai_compatible",
            credential_ref="AGENT_MODEL_API_KEY",
        ).to_dict(),
    )
    validator.validate(
        "sandbox_profile",
        SandboxProfile(
            sandbox_profile_id="sandbox-profile-0001",
            backend="single_workspace",
            workspace_policy="controlled_patch",
        ).to_dict(),
    )
    validator.validate(
        "context_mount",
        ContextMount(
            context_mount_id="context-mount-0001",
            run_id="run-0001",
            task_id="task-0001",
            mount_type="coding_context",
            includes={
                "root_guidance": True,
                "goal_brief": True,
                "task_brief": True,
                "artifact_refs": [],
                "failure_evidence_refs": [],
                "decision_refs": [],
                "recent_event_count": 20,
            },
        ).to_dict(),
    )
    validator.validate(
        "runtime_profile",
        RuntimeProfile(
            runtime_profile_id="runtime-profile-0001",
            agent_id="agent-0001",
            model_profile_id="model-profile-0001",
            tool_permission_profile_id="tool-profile-0001",
            account_profile_id="account-profile-0001",
            sandbox_profile_id="sandbox-profile-0001",
            context_mount_id="context-mount-0001",
            budget=BudgetProfile(max_model_calls=3, max_tool_calls=20),
        ).to_dict(),
    )


def test_worker_invocation_and_result_validate_against_schemas() -> None:
    validator = SchemaValidator(SCHEMA_DIR)

    validator.validate(
        "worker_invocation",
        WorkerInvocation(
            worker_invocation_id="worker-0001",
            run_id="run-0001",
            task_id="task-0001",
            agent_id="agent-0001",
            runtime_profile_id="runtime-profile-0001",
            status="running",
            started_at="2026-04-27T14:30:00+08:00",
            summary="Run CoderAgent with controlled patch workspace.",
        ).to_dict(),
    )
    validator.validate(
        "worker_result",
        WorkerResult(
            worker_result_id="worker-result-0001",
            worker_invocation_id="worker-0001",
            run_id="run-0001",
            task_id="task-0001",
            status="succeeded",
            artifact_refs=["artifact-0001"],
            validation_refs=["validation-0001"],
            failure_evidence_refs=[],
            cost=WorkerCost(model_calls=1, tool_calls=8),
            summary="Implemented task and passed targeted validation.",
        ).to_dict(),
    )


def test_runtime_request_validates_against_schema() -> None:
    validator = SchemaValidator(SCHEMA_DIR)

    validator.validate(
        "runtime_request",
        RuntimeRequest(
            runtime_request_id="runtime-request-0001",
            run_id="run-0001",
            task_id="task-0001",
            request_type="scope_expansion",
            risk="medium",
            reason="Need to write generated/report.md.",
            details={"write_scope": ["generated/report.md"]},
            status="decision_created",
            decision_id="decision-0001",
            created_at="2026-05-13T10:00:00+08:00",
        ).to_dict(),
    )


def test_validation_result_validates_against_schema() -> None:
    validator = SchemaValidator(SCHEMA_DIR)

    validator.validate(
        "validation_result",
        ValidationResult(
            validation_result_id="validation-0001",
            run_id="run-0001",
            task_id="task-0001",
            tool_name="run_command",
            command="pytest tests/unit/test_notes_tool.py",
            status="passed",
            summary="Command succeeded.",
            data={"exit_code": 0},
            created_at="2026-05-13T10:00:00+08:00",
        ).to_dict(),
    )


def test_runtime_profile_builder_upgrades_weak_capability_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "minimax")
    validator = SchemaValidator(SCHEMA_DIR)
    model_dir = tmp_path / ".asteria" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "capability_profile.json").write_text(
        """
{
  "schema_version": "0.1.0",
  "root": ".",
  "profile_count": 1,
  "profiles": [
    {
      "provider": "runtime",
      "model": "medium-route",
      "purpose": "coding",
      "model_tier": "medium",
      "total_calls": 0,
      "success_calls": 0,
      "failure_calls": 0,
      "success_rate": 0.0,
      "input_tokens": 0,
      "output_tokens": 0,
      "failure_types": {},
      "recommended_action": "review_worker_route_before_scaling",
      "recent_failures": [],
      "total_workers": 3,
      "successful_workers": 1,
      "failed_workers": 2,
      "worker_success_rate": 0.3333,
      "validation_total": 3,
      "validation_passed": 1,
      "validation_pass_rate": 0.3333
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-0001",
        policy={"permissions": {}, "protected_paths": []},
        validator=validator,
    )
    task = {
        "task_id": "task-0001",
        "role": "CoderAgent",
        "allowed_tools": ["read_file"],
        "task_kind": "implementation",
        "read_scope": ["src/"],
        "write_scope": ["src/output.py"],
    }

    mount = RuntimeProfileBuilder(validator).build_and_record(
        context=context,
        task=task,
        worker_id="worker-0001",
        runtime_context={},
    )

    assert mount.runtime_context["model_profile_id"] == "model-profile-worker-0001"
    assert mount.runtime_context["runtime_profile_id"] == "runtime-profile-worker-0001"
    assert mount.runtime_context["route_guidance"]["status"] == "blocked"
    assert mount.runtime_context["route_guidance"]["purpose"] == "coding"
    assert mount.runtime_context["route_guidance"]["relevant"][0]["model_tier"] == "medium"
    run_dir = tmp_path / ".asteria" / "runs" / "run-0001"
    model_profiles = (run_dir / "model_profiles.jsonl").read_text(encoding="utf-8")
    assert '"model_tier": "strong"' in model_profiles
    assert '"provider": "minimax"' in model_profiles
    assert mount.runtime_context["model_route_resolution"]["tier"] == "strong"
    assert mount.runtime_context["agent_role_contract"]["role"] == "CoderAgent"
    assert mount.runtime_context["agent_role_contract"]["purpose"] == "coding"
    assert mount.runtime_context["agent_role_contract"]["deadline_profile"] == "worker"
    selection = mount.runtime_context["model_selection"]
    assert selection["role_contract"]["role"] == "CoderAgent"
    assert selection["role_contract"]["provider_call_seconds"] == 90
    assert selection["reason"] == "capability_feedback_escalated_from_medium"
    assert selection["tier_pressure"] == {
        "default_tier": "medium",
        "strategy_tier": "medium",
        "selected_tier": "strong",
        "direction": "up",
        "delta": 1,
        "uses_stronger_than_default": True,
        "uses_cheaper_than_default": False,
    }
    assert selection["capability_feedback"]["status"] == "blocked"
    assert selection["capability_feedback"]["decision"] == "escalated_to_strong"
    assert selection["capability_feedback"]["matched_route"]["recommended_action"] == (
        "review_worker_route_before_scaling"
    )
    sandbox_profile = (run_dir / "sandbox_profiles.jsonl").read_text(encoding="utf-8")
    assert "temp_workspace" in sandbox_profile
    assert "use copied temp workspace" in sandbox_profile


def test_runtime_profile_builder_ignores_stale_capability_profile_when_route_missing(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(SCHEMA_DIR)
    model_dir = tmp_path / ".asteria" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "capability_profile.json").write_text(
        """
{
  "schema_version": "0.1.0",
  "root": ".",
  "profile_count": 1,
  "profiles": [
    {
      "provider": "runtime",
      "model": "old-medium-route",
      "purpose": "coding",
      "model_tier": "medium",
      "total_calls": 3,
      "success_calls": 1,
      "failure_calls": 2,
      "success_rate": 0.3333,
      "input_tokens": 0,
      "output_tokens": 0,
      "failure_types": {},
      "recommended_action": "review_worker_route_before_scaling"
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-stale",
        policy={"permissions": {}, "protected_paths": []},
        validator=validator,
    )
    task = {
        "task_id": "task-stale",
        "role": "CoderAgent",
        "allowed_tools": ["read_file"],
        "task_kind": "implementation",
        "read_scope": ["src/"],
        "write_scope": ["src/output.py"],
    }

    mount = RuntimeProfileBuilder(validator).build_and_record(
        context=context,
        task=task,
        worker_id="worker-stale",
        runtime_context={},
    )

    selection = mount.runtime_context["model_selection"]
    route = mount.runtime_context["model_route_resolution"]
    assert selection["selected_tier"] == "medium"
    assert selection["reason"] == "task_default"
    assert selection["capability_feedback"]["decision"] == (
        "default_route_fallback_due_stale_capability_profile"
    )
    assert route["source"] == "default_route_policy"
    assert route["fallback"]["used"] is True
    assert route["fallback"]["source"] == "default_route_policy"


def test_runtime_profile_builder_uses_strategy_bias_without_clobbering_routes(
    tmp_path: Path,
) -> None:
    validator = SchemaValidator(SCHEMA_DIR)
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-0002",
        policy={
            "permissions": {},
            "protected_paths": [],
            "model_strategy_profile": {
                "strategy": "quality",
                "selection_policy": "prefer_capability_fit_with_budget",
            },
        },
        validator=validator,
    )
    task = {
        "task_id": "task-0002",
        "role": "CoderAgent",
        "allowed_tools": ["read_file"],
        "task_kind": "implementation",
        "priority": "high",
        "read_scope": ["src/"],
        "write_scope": ["src/output.py"],
    }

    mount = RuntimeProfileBuilder(validator).build_and_record(
        context=context,
        task=task,
        worker_id="worker-0002",
        runtime_context={},
    )

    selection = mount.runtime_context["model_selection"]
    assert selection["role_contract"] == {
        "role": "CoderAgent",
        "purpose": "coding",
        "default_model_tier": "medium",
        "deadline_profile": "worker",
        "provider_call_seconds": 90,
        "stream_idle_timeout_seconds": 30,
        "max_model_calls": 1,
        "responsibilities": [
            "produce scoped candidate changes",
            "keep edits inside write scope",
            "return artifacts and verification commands",
        ],
        "escalation_policy": (
            "start medium; escalate to strong on capability feedback, high risk, or complex scope"
        ),
    }
    assert {key: value for key, value in selection.items() if key != "role_contract"} == {
        "purpose": "coding",
        "task_kind": "implementation",
        "default_tier": "medium",
        "strategy_tier": "strong",
        "selected_tier": "strong",
        "strategy": "quality",
        "reason": "quality_strategy_escalated_high_risk_or_complex_task",
        "tier_pressure": {
            "default_tier": "medium",
            "strategy_tier": "strong",
            "selected_tier": "strong",
            "direction": "up",
            "delta": 1,
            "uses_stronger_than_default": True,
            "uses_cheaper_than_default": False,
        },
        "capability_feedback": {
            "status": "healthy",
            "decision": "no_escalation",
            "matched_route": None,
            "blocking_count": 0,
            "review_count": 0,
            "recommended_actions": [
                "Keep current model routes and continue collecting capability evidence."
            ],
            "provider_route_strategy": {"decision": "not_configured"},
        },
    }


def test_runtime_profile_builder_honors_explicit_task_model_tier(tmp_path: Path) -> None:
    validator = SchemaValidator(SCHEMA_DIR)
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-0003",
        policy={
            "permissions": {},
            "protected_paths": [],
            "model_strategy_profile": {
                "strategy": "economy",
                "selection_policy": "prefer_low_cost_with_safety_escalation",
            },
        },
        validator=validator,
    )
    task = {
        "task_id": "task-0003",
        "role": "CoderAgent",
        "allowed_tools": ["read_file"],
        "task_kind": "implementation",
        "runtime_profile_hints": {"model_tier": "strong"},
        "read_scope": ["src/"],
        "write_scope": ["src/output.py"],
    }

    mount = RuntimeProfileBuilder(validator).build_and_record(
        context=context,
        task=task,
        worker_id="worker-0003",
        runtime_context={},
    )

    assert mount.runtime_context["model_selection"]["selected_tier"] == "strong"
    assert mount.runtime_context["model_selection"]["reason"] == "explicit_task_model_tier"


def test_runtime_profile_builder_records_resolved_model_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "fake")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_API_KEY", "medium-key")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("AGENT_MODEL_MEDIUM_NAME", "medium-model")
    validator = SchemaValidator(SCHEMA_DIR)
    context = RuntimeContext(
        root=tmp_path,
        run_id="run-0004",
        policy={"permissions": {}, "protected_paths": []},
        validator=validator,
    )
    task = {
        "task_id": "task-0004",
        "role": "CoderAgent",
        "allowed_tools": ["read_file"],
        "task_kind": "implementation",
        "read_scope": ["src/"],
        "write_scope": ["src/output.py"],
    }

    mount = RuntimeProfileBuilder(validator).build_and_record(
        context=context,
        task=task,
        worker_id="worker-0004",
        runtime_context={},
    )

    route = mount.runtime_context["model_route_resolution"]
    assert route["configured"] is True
    assert route["tier"] == "medium"
    assert route["provider"] == "openai-compatible"
    assert route["model_name"] == "medium-model"
    assert route["next_action"] == "Model route is configured."
    model_profiles = (tmp_path / ".asteria" / "runs" / "run-0004" / "model_profiles.jsonl")
    model_profile_text = model_profiles.read_text(encoding="utf-8")
    assert '"provider": "openai-compatible"' in model_profile_text
    assert '"model_name": "medium-model"' in model_profile_text
    assert '"deadline_profile": "worker"' in model_profile_text
    runtime_profiles = (
        tmp_path / ".asteria" / "runs" / "run-0004" / "runtime_profiles.jsonl"
    ).read_text(encoding="utf-8")
    assert '"max_runtime_minutes": 2' in runtime_profiles
