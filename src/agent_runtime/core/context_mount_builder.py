from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.core.runtime_profile import ContextMount
from agent_runtime.core.task_contract import context_requirements, task_kind


@dataclass(frozen=True)
class ContextMountBuilder:
    run_id: str

    def build(
        self,
        task: dict,
        artifact_refs: list[str] | None = None,
        failure_evidence_refs: list[str] | None = None,
        decision_refs: list[str] | None = None,
        validation_refs: list[str] | None = None,
    ) -> ContextMount:
        requirements = context_requirements(task)
        task_id = str(task["task_id"])
        mount_type = str(requirements.get("mount_type") or self._default_mount_type(task))
        includes = {
            "root_guidance": True,
            "goal_brief": True,
            "task_brief": True,
            "artifact_refs": (artifact_refs or []) if requirements.get("include_artifacts") else [],
            "failure_evidence_refs": (
                (failure_evidence_refs or []) if requirements.get("include_failures") else []
            ),
            "decision_refs": (decision_refs or []) if requirements.get("include_decisions") else [],
            "validation_refs": (validation_refs or []) if requirements.get("include_validation") else [],
            "recent_event_count": int(requirements.get("recent_event_count") or 20),
        }
        return ContextMount(
            context_mount_id=f"context-mount-{task_id}",
            run_id=self.run_id,
            task_id=task_id,
            mount_type=mount_type,
            includes=includes,
            summary=f"{mount_type} for {task_id}.",
        )

    def _default_mount_type(self, task: dict) -> str:
        kind = task_kind(task)
        if kind in {"diagnostic", "verification"}:
            return "debug_context"
        if kind in {"report", "decision"}:
            return "summary_context"
        return "coding_context"
