from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from asteria_runtime.core.runtime_profile import SCHEMA_VERSION


@dataclass(frozen=True)
class WorkerInvocation:
    worker_invocation_id: str
    run_id: str
    task_id: str
    agent_id: str
    runtime_profile_id: str
    status: str
    started_at: str
    ended_at: str | None = None
    summary: str = ""
    delegation_brief: dict | None = None
    brief_quality: dict | None = None
    parent_worker_invocation_id: str | None = None
    parent_task_id: str | None = None
    worker_kind: str | None = None
    parallel_safety: str | None = None
    execution_profile_id: str | None = None
    spawn_kind: str | None = None
    fake_path: bool | None = None
    child_plan_refs: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "worker_invocation_id": self.worker_invocation_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "runtime_profile_id": self.runtime_profile_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "summary": self.summary,
        }
        if self.delegation_brief is not None:
            data["delegation_brief"] = self.delegation_brief
        if self.brief_quality is not None:
            data["brief_quality"] = self.brief_quality
        if self.parent_worker_invocation_id is not None:
            data["parent_worker_invocation_id"] = self.parent_worker_invocation_id
        if self.parent_task_id is not None:
            data["parent_task_id"] = self.parent_task_id
        if self.worker_kind is not None:
            data["worker_kind"] = self.worker_kind
        if self.parallel_safety is not None:
            data["parallel_safety"] = self.parallel_safety
        if self.execution_profile_id is not None:
            data["execution_profile_id"] = self.execution_profile_id
        if self.spawn_kind is not None:
            data["spawn_kind"] = self.spawn_kind
        if self.fake_path is not None:
            data["fake_path"] = self.fake_path
        if self.child_plan_refs:
            data["child_plan_refs"] = self.child_plan_refs
        return data


@dataclass(frozen=True)
class WorkerCost:
    model_calls: int = 0
    tool_calls: int = 0

    def to_dict(self) -> dict:
        return {
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
        }


@dataclass(frozen=True)
class WorkerResult:
    worker_result_id: str
    worker_invocation_id: str
    run_id: str
    task_id: str
    status: str
    summary: str
    artifact_refs: list[str] = field(default_factory=list)
    validation_refs: list[str] = field(default_factory=list)
    failure_evidence_refs: list[str] = field(default_factory=list)
    cost: WorkerCost = field(default_factory=WorkerCost)
    parent_worker_invocation_id: str | None = None
    worker_kind: str | None = None
    child_plan_refs: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        data = {
            "schema_version": self.schema_version,
            "worker_result_id": self.worker_result_id,
            "worker_invocation_id": self.worker_invocation_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "status": self.status,
            "artifact_refs": self.artifact_refs,
            "validation_refs": self.validation_refs,
            "failure_evidence_refs": self.failure_evidence_refs,
            "cost": self.cost.to_dict(),
            "summary": self.summary,
        }
        if self.parent_worker_invocation_id is not None:
            data["parent_worker_invocation_id"] = self.parent_worker_invocation_id
        if self.worker_kind is not None:
            data["worker_kind"] = self.worker_kind
        if self.child_plan_refs:
            data["child_plan_refs"] = self.child_plan_refs
        return data
