from pathlib import Path

from agent_runtime.core.runtime_profile import (
    AccountProfile,
    BudgetProfile,
    ContextMount,
    ModelProfile,
    RuntimeProfile,
    SandboxProfile,
    ToolPermissionProfile,
)
from agent_runtime.core.worker import WorkerCost, WorkerInvocation, WorkerResult
from agent_runtime.storage.schema_validator import SchemaValidator


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
            write_scope=["src/agent_runtime/", "tests/"],
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
