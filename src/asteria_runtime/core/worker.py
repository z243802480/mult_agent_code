from __future__ import annotations

from dataclasses import dataclass, field

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
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
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
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
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
