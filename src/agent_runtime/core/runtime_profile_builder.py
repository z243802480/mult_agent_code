from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.core.context_mount_builder import ContextMountBuilder
from agent_runtime.core.context_package_builder import ContextPackageBuilder
from agent_runtime.core.runtime_context import RuntimeContext
from agent_runtime.core.runtime_profile import (
    AccountProfile,
    BudgetProfile,
    ModelProfile,
    RuntimeProfile,
    SandboxProfile,
    ToolPermissionProfile,
)
from agent_runtime.core.task_contract import (
    context_requirements,
    failure_policy,
    parallel_safety,
    read_scope,
    task_kind,
    validation_commands,
    write_scope,
)
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class RuntimeProfileMount:
    runtime_profile_id: str
    runtime_context: dict


@dataclass(frozen=True)
class RuntimeProfileBuilder:
    validator: SchemaValidator

    def build_and_record(
        self,
        *,
        context: RuntimeContext,
        task: dict,
        worker_id: str,
        runtime_context: dict,
        artifact_refs: list[str] | None = None,
        failure_evidence_refs: list[str] | None = None,
        decision_refs: list[str] | None = None,
    ) -> RuntimeProfileMount:
        scoped = self._runtime_context_for_task(
            context=context,
            task=task,
            runtime_context=runtime_context,
            artifact_refs=artifact_refs or [],
            failure_evidence_refs=failure_evidence_refs or [],
            decision_refs=decision_refs or [],
        )
        if context.run_dir is None:
            return RuntimeProfileMount(
                runtime_profile_id=self._default_runtime_profile_id(task),
                runtime_context=scoped,
            )

        profile_base_id = f"profile-{worker_id}"
        model_tier = self._model_tier(task)
        model_profile = ModelProfile(
            model_profile_id=f"model-{profile_base_id}",
            purpose=self._model_purpose(task),
            provider="runtime",
            model_name=f"{model_tier}-route",
            model_tier=model_tier,
        )
        tool_profile = ToolPermissionProfile(
            tool_permission_profile_id=f"tools-{profile_base_id}",
            allowed_tools=[str(tool) for tool in task.get("allowed_tools", [])],
            read_scope=read_scope(task),
            write_scope=write_scope(task),
            allow_network=bool(context.policy.get("permissions", {}).get("allow_network", False)),
            allow_shell=bool(context.policy.get("permissions", {}).get("allow_shell", True)),
            allow_destructive_shell=bool(
                context.policy.get("permissions", {}).get("allow_destructive_shell", False)
            ),
        )
        account_profile = AccountProfile(
            account_profile_id=f"account-{profile_base_id}",
            provider="runtime",
            credential_ref="AGENT_MODEL_API_KEY",
            permission_tier="standard",
        )
        sandbox_profile = SandboxProfile(
            sandbox_profile_id=f"sandbox-{profile_base_id}",
            backend="single_workspace",
            workspace_policy="controlled_patch",
            cleanup_policy="keep_evidence",
            export_required=["artifact_index", "diff", "failure_evidence"],
        )
        context_mount = scoped.get("context_mount") or {}
        runtime_profile = RuntimeProfile(
            runtime_profile_id=f"runtime-{profile_base_id}",
            agent_id=str(task.get("assigned_agent_id") or task.get("role") or "CoderAgent"),
            model_profile_id=model_profile.model_profile_id,
            tool_permission_profile_id=tool_profile.tool_permission_profile_id,
            account_profile_id=account_profile.account_profile_id,
            sandbox_profile_id=sandbox_profile.sandbox_profile_id,
            context_mount_id=str(context_mount.get("context_mount_id") or f"context-{profile_base_id}"),
            budget=BudgetProfile(
                max_model_calls=1,
                max_tool_calls=max(1, len(task.get("allowed_tools", []))),
            ),
        )
        scoped["runtime_profile_id"] = runtime_profile.runtime_profile_id
        scoped["model_profile_id"] = model_profile.model_profile_id
        scoped["tool_permission_profile_id"] = tool_profile.tool_permission_profile_id
        scoped["sandbox_profile_id"] = sandbox_profile.sandbox_profile_id
        scoped["account_profile_id"] = account_profile.account_profile_id

        self._record_profiles(
            context=context,
            task=task,
            worker_id=worker_id,
            model_profile=model_profile,
            tool_profile=tool_profile,
            account_profile=account_profile,
            sandbox_profile=sandbox_profile,
            runtime_profile=runtime_profile,
            context_mount=context_mount,
        )
        return RuntimeProfileMount(
            runtime_profile_id=runtime_profile.runtime_profile_id,
            runtime_context=scoped,
        )

    def _runtime_context_for_task(
        self,
        *,
        context: RuntimeContext,
        task: dict,
        runtime_context: dict,
        artifact_refs: list[str],
        failure_evidence_refs: list[str],
        decision_refs: list[str],
    ) -> dict:
        scoped = dict(runtime_context)
        if context.run_id:
            scoped["context_mount"] = ContextMountBuilder(context.run_id).build(
                task,
                artifact_refs=artifact_refs,
                failure_evidence_refs=failure_evidence_refs,
                decision_refs=decision_refs,
            ).to_dict()
            scoped["context_package"] = ContextPackageBuilder(self.validator).build(
                context,
                task,
                scoped["context_mount"],
            )
        scoped["task_contract"] = {
            "read_scope": read_scope(task),
            "write_scope": write_scope(task),
            "context_requirements": context_requirements(task),
            "validation_commands": validation_commands(task),
            "failure_policy": failure_policy(task),
            "parallel_safety": parallel_safety(task),
        }
        return scoped

    def _record_profiles(
        self,
        *,
        context: RuntimeContext,
        task: dict,
        worker_id: str,
        model_profile: ModelProfile,
        tool_profile: ToolPermissionProfile,
        account_profile: AccountProfile,
        sandbox_profile: SandboxProfile,
        runtime_profile: RuntimeProfile,
        context_mount: dict,
    ) -> None:
        if context.run_dir is None:
            return
        store = JsonlStore(self.validator)
        store.append(context.run_dir / "model_profiles.jsonl", model_profile.to_dict(), "model_profile")
        store.append(
            context.run_dir / "tool_permission_profiles.jsonl",
            tool_profile.to_dict(),
            "tool_permission_profile",
        )
        store.append(
            context.run_dir / "account_profiles.jsonl",
            account_profile.to_dict(),
            "account_profile",
        )
        store.append(
            context.run_dir / "sandbox_profiles.jsonl",
            sandbox_profile.to_dict(),
            "sandbox_profile",
        )
        if context_mount:
            store.append(context.run_dir / "context_mounts.jsonl", context_mount, "context_mount")
        store.append(
            context.run_dir / "runtime_profiles.jsonl",
            runtime_profile.to_dict(),
            "runtime_profile",
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "runtime_profile_mounted",
                "RuntimeProfileBuilder",
                f"Mounted {runtime_profile.runtime_profile_id} for {task['task_id']}.",
                {
                    "task_id": task["task_id"],
                    "worker_invocation_id": worker_id,
                    "runtime_profile_id": runtime_profile.runtime_profile_id,
                    "model_profile_id": model_profile.model_profile_id,
                    "tool_permission_profile_id": tool_profile.tool_permission_profile_id,
                    "context_mount_id": runtime_profile.context_mount_id,
                },
            )

    def _model_tier(self, task: dict) -> str:
        kind = task_kind(task)
        if kind in {"architecture", "review"}:
            return "strong"
        if kind in {"report", "decision"}:
            return "cheap"
        if kind in {"research", "diagnostic", "verification"} and parallel_safety(task) == "readonly":
            return "cheap"
        return "medium"

    def _model_purpose(self, task: dict) -> str:
        kind = task_kind(task)
        if kind == "research":
            return "research"
        if kind in {"diagnostic", "verification"}:
            return "debugging"
        if kind in {"report", "decision"}:
            return "summarization"
        if kind == "review":
            return "review"
        return "coding"

    def _default_runtime_profile_id(self, task: dict) -> str:
        role = str(task.get("role") or "CoderAgent").lower().replace("agent", "")
        return f"runtime-profile-execute-{role or 'coder'}"
