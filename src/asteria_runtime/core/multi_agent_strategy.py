from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MultiAgentStrategy:
    mode: str
    max_child_workers: int
    planner_child_plan: bool
    reason: str
    suggested_model_tier: str
    worker_budget: dict
    coordination_policy: dict

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "max_child_workers": self.max_child_workers,
            "planner_child_plan": self.planner_child_plan,
            "reason": self.reason,
            "suggested_model_tier": self.suggested_model_tier,
            "worker_budget": self.worker_budget,
            "coordination_policy": self.coordination_policy,
        }


class MultiAgentStrategyAdvisor:
    """Classify task complexity into safe child-worker scaling guidance."""

    def for_task(self, task: dict) -> MultiAgentStrategy:
        if str(task.get("execution_profile") or "") == "session_agent":
            return self._strategy(
                mode="serial_worker",
                max_child_workers=1,
                planner_child_plan=False,
                reason="session-agent profile keeps a single CC-like worker",
                suggested_model_tier="medium",
                write_allowed=True,
            )
        complexity = self._complexity(task)
        write_scope = [str(item) for item in task.get("write_scope", []) if item]
        task_kind = str(task.get("task_kind") or "")
        parallel_safety = str(task.get("parallel_safety") or "serial")
        if task_kind in {"research", "diagnostic", "verification"} or not write_scope:
            return self._strategy(
                mode="readonly_fanout",
                max_child_workers=8 if complexity >= 5 else 3,
                planner_child_plan=complexity >= 3,
                reason="readonly or diagnostic work can fan out safely under shared budget",
                suggested_model_tier="medium",
                write_allowed=False,
            )
        if parallel_safety == "disjoint_writes" and len(write_scope) > 1:
            return self._strategy(
                mode="disjoint_write_workers",
                max_child_workers=min(4, len(write_scope)),
                planner_child_plan=True,
                reason="multiple disjoint write targets can be delegated to child workers",
                suggested_model_tier="medium" if complexity < 7 else "strong",
                write_allowed=True,
            )
        if complexity >= 7:
            return self._strategy(
                mode="plan_then_serial",
                max_child_workers=1,
                planner_child_plan=True,
                reason="high-complexity write task needs explicit child plan but serial merge gate",
                suggested_model_tier="strong",
                write_allowed=True,
            )
        return self._strategy(
            mode="serial_worker",
            max_child_workers=1,
            planner_child_plan=False,
            reason="single bounded write task should remain serial",
            suggested_model_tier="medium",
            write_allowed=True,
        )

    def _strategy(
        self,
        *,
        mode: str,
        max_child_workers: int,
        planner_child_plan: bool,
        reason: str,
        suggested_model_tier: str,
        write_allowed: bool,
    ) -> MultiAgentStrategy:
        return MultiAgentStrategy(
            mode=mode,
            max_child_workers=max_child_workers,
            planner_child_plan=planner_child_plan,
            reason=reason,
            suggested_model_tier=suggested_model_tier,
            worker_budget={
                "max_model_calls_per_child": 1,
                "max_tool_calls_per_child": 12 if max_child_workers > 1 else 20,
                "max_repair_attempts_per_child": 1,
            },
            coordination_policy={
                "write_allowed": write_allowed,
                "requires_disjoint_write_scope": mode == "disjoint_write_workers",
                "requires_merge_gate": write_allowed,
                "requires_summary": max_child_workers > 1 or planner_child_plan,
                "scale_out_limit": max_child_workers,
            },
        )

    def _complexity(self, task: dict) -> int:
        acceptance = self._list(task.get("acceptance"))
        artifacts = self._list(task.get("expected_artifacts"))
        changed = self._list(task.get("expected_changed_files"))
        description_words = len(str(task.get("description") or "").split())
        return (
            len(acceptance)
            + len(artifacts) * 2
            + len(changed) * 2
            + min(4, description_words // 40)
        )

    def _list(self, value: object) -> list[object]:
        return value if isinstance(value, list) else []
