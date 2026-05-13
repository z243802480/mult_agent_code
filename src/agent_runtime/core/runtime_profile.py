from __future__ import annotations

from dataclasses import dataclass, field


SCHEMA_VERSION = "0.1.0"


@dataclass(frozen=True)
class BudgetProfile:
    max_model_calls: int
    max_tool_calls: int
    max_runtime_minutes: int | None = None

    def to_dict(self) -> dict:
        data = {
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
        }
        if self.max_runtime_minutes is not None:
            data["max_runtime_minutes"] = self.max_runtime_minutes
        return data


@dataclass(frozen=True)
class ModelProfile:
    model_profile_id: str
    purpose: str
    provider: str
    model_name: str
    model_tier: str
    fallback_profile_ids: list[str] = field(default_factory=list)
    limits: dict | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        data = {
            "schema_version": self.schema_version,
            "model_profile_id": self.model_profile_id,
            "purpose": self.purpose,
            "provider": self.provider,
            "model_name": self.model_name,
            "model_tier": self.model_tier,
            "fallback_profile_ids": self.fallback_profile_ids,
        }
        if self.limits is not None:
            data["limits"] = self.limits
        return data


@dataclass(frozen=True)
class ToolPermissionProfile:
    tool_permission_profile_id: str
    allowed_tools: list[str]
    read_scope: list[str]
    write_scope: list[str]
    allow_network: bool = False
    allow_shell: bool = True
    allow_destructive_shell: bool = False
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "tool_permission_profile_id": self.tool_permission_profile_id,
            "allowed_tools": self.allowed_tools,
            "read_scope": self.read_scope,
            "write_scope": self.write_scope,
            "allow_network": self.allow_network,
            "allow_shell": self.allow_shell,
            "allow_destructive_shell": self.allow_destructive_shell,
        }


@dataclass(frozen=True)
class AccountProfile:
    account_profile_id: str
    provider: str
    credential_ref: str
    permission_tier: str = "standard"
    rate_limit_hint: dict | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        data = {
            "schema_version": self.schema_version,
            "account_profile_id": self.account_profile_id,
            "provider": self.provider,
            "credential_ref": self.credential_ref,
            "permission_tier": self.permission_tier,
        }
        if self.rate_limit_hint is not None:
            data["rate_limit_hint"] = self.rate_limit_hint
        return data


@dataclass(frozen=True)
class SandboxProfile:
    sandbox_profile_id: str
    backend: str
    workspace_policy: str
    cleanup_policy: str = "keep_evidence"
    export_required: list[str] = field(default_factory=lambda: ["artifact_index", "diff"])
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "sandbox_profile_id": self.sandbox_profile_id,
            "backend": self.backend,
            "workspace_policy": self.workspace_policy,
            "cleanup_policy": self.cleanup_policy,
            "export_required": self.export_required,
        }


@dataclass(frozen=True)
class ContextMount:
    context_mount_id: str
    run_id: str
    task_id: str
    mount_type: str
    includes: dict
    summary: str = ""
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "context_mount_id": self.context_mount_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "mount_type": self.mount_type,
            "includes": self.includes,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class RuntimeProfile:
    runtime_profile_id: str
    agent_id: str
    model_profile_id: str
    tool_permission_profile_id: str
    sandbox_profile_id: str
    context_mount_id: str
    budget: BudgetProfile
    account_profile_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "runtime_profile_id": self.runtime_profile_id,
            "agent_id": self.agent_id,
            "model_profile_id": self.model_profile_id,
            "tool_permission_profile_id": self.tool_permission_profile_id,
            "account_profile_id": self.account_profile_id,
            "sandbox_profile_id": self.sandbox_profile_id,
            "context_mount_id": self.context_mount_id,
            "budget": self.budget.to_dict(),
        }
