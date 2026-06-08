from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from asteria_runtime.core.fast_path_policy import (
    FastPathPolicy,
    classify_fast_path,
    classify_risk_tier,
)


SESSION_AGENT = "session_agent"
HARNESS = "harness"

HARNESS_TRIGGERS = frozenset({"parallel_writes", "high_risk", "explicit_harness"})


@dataclass(frozen=True)
class ExecutionProfileResolution:
    profile_id: str
    loop_profile_id: str
    collapse_to_single_task: bool
    use_replan_lineage: bool
    use_repair_limit_decisions: bool
    reason: str
    fast_path_task_kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_session_agent(self) -> bool:
        return self.profile_id == SESSION_AGENT


def resolve_execution_profile(
    goal: str,
    *,
    fast_path: FastPathPolicy | None = None,
    parallel_writes: bool = False,
    force_harness: bool = False,
) -> ExecutionProfileResolution:
    """Choose Runtime default path: CC-like session agent vs full harness."""
    fp = fast_path or classify_fast_path(goal)
    risk = classify_risk_tier(goal, parallel_writes=parallel_writes)
    if force_harness or parallel_writes or risk.risk_tier == "high" or fp.task_kind == "high_risk":
        trigger = (
            "explicit_harness"
            if force_harness
            else "parallel_writes"
            if parallel_writes
            else "high_risk"
        )
        return ExecutionProfileResolution(
            profile_id=HARNESS,
            loop_profile_id="default",
            collapse_to_single_task=False,
            use_replan_lineage=True,
            use_repair_limit_decisions=True,
            reason=f"Harness profile required ({trigger}).",
            fast_path_task_kind=fp.task_kind,
        )
    return ExecutionProfileResolution(
        profile_id=SESSION_AGENT,
        loop_profile_id="session_agent",
        collapse_to_single_task=True,
        use_replan_lineage=False,
        use_repair_limit_decisions=False,
        reason=(
            "Default Runtime path: single-agent session with in-loop retry; "
            "audit is async evidence, not replan lineage."
        ),
        fast_path_task_kind=fp.task_kind,
    )


def session_agent_recommended_command(command: str, *, is_session_agent: bool) -> str:
    normalized = str(command or "").strip().lower().replace("asteria ", "")
    if is_session_agent and normalized.split()[0] == "replan":
        return "resume"
    return str(command or "")


def resolve_worker_execution_profile(task: dict) -> ExecutionProfileResolution:
    """Map a worker task to session_agent (readonly) or harness (write path)."""
    stored = task.get("execution_profile")
    if isinstance(stored, dict) and stored.get("profile_id") in {SESSION_AGENT, HARNESS}:
        profile_id = str(stored["profile_id"])
        return ExecutionProfileResolution(
            profile_id=profile_id,
            loop_profile_id=str(stored.get("loop_profile_id") or profile_id),
            collapse_to_single_task=profile_id == SESSION_AGENT,
            use_replan_lineage=profile_id == HARNESS,
            use_repair_limit_decisions=profile_id == HARNESS,
            reason=str(stored.get("reason") or f"Worker task persisted {profile_id} profile."),
            fast_path_task_kind=str(stored.get("fast_path_task_kind") or "worker"),
        )
    parallel_safety = str(task.get("parallel_safety") or "serial")
    write_scope = [str(item) for item in task.get("write_scope") or [] if item]
    write_allowed = task.get("write_allowed") is True or bool(write_scope)
    if parallel_safety == "readonly" or not write_allowed:
        return ExecutionProfileResolution(
            profile_id=SESSION_AGENT,
            loop_profile_id="session_agent",
            collapse_to_single_task=True,
            use_replan_lineage=False,
            use_repair_limit_decisions=False,
            reason="Readonly worker stays on session_agent profile.",
            fast_path_task_kind="complex_change",
        )
    return resolve_execution_profile(
        str(task.get("title") or task.get("description") or ""),
        parallel_writes=parallel_safety == "disjoint_writes",
        force_harness=True,
    )


def execution_profile_from_run_config(run_config: dict | None) -> ExecutionProfileResolution:
    if not run_config:
        return resolve_execution_profile("")
    stored = run_config.get("execution_profile")
    if isinstance(stored, dict):
        return ExecutionProfileResolution(
            profile_id=str(stored.get("profile_id") or SESSION_AGENT),
            loop_profile_id=str(stored.get("loop_profile_id") or SESSION_AGENT),
            collapse_to_single_task=bool(stored.get("collapse_to_single_task", True)),
            use_replan_lineage=bool(stored.get("use_replan_lineage", False)),
            use_repair_limit_decisions=bool(stored.get("use_repair_limit_decisions", False)),
            reason=str(stored.get("reason") or ""),
            fast_path_task_kind=str(stored.get("fast_path_task_kind") or "unknown"),
        )
    profile_id = str(stored or SESSION_AGENT)
    if profile_id == HARNESS:
        return ExecutionProfileResolution(
            profile_id=HARNESS,
            loop_profile_id="default",
            collapse_to_single_task=False,
            use_replan_lineage=True,
            use_repair_limit_decisions=True,
            reason="Persisted harness profile.",
            fast_path_task_kind=str(
                (run_config.get("fast_path") or {}).get("task_kind") or "unknown"
            ),
        )
    return ExecutionProfileResolution(
        profile_id=SESSION_AGENT,
        loop_profile_id="session_agent",
        collapse_to_single_task=True,
        use_replan_lineage=False,
        use_repair_limit_decisions=False,
        reason="Persisted session-agent profile.",
        fast_path_task_kind=str(
            (run_config.get("fast_path") or {}).get("task_kind") or "unknown"
        ),
    )
