from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.execution_profile import execution_profile_from_run_config
from asteria_runtime.core.run_config import load_run_config
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


CONTINUABLE_PHASES = frozenset({"ACCEPTED", "DONE", "REVIEW"})
CONTINUABLE_RUN_STATUSES = frozenset({"completed", "accepted"})


class SessionContinuationError(RuntimeError):
    """Raised when a warm continuation request cannot be applied."""


@dataclass(frozen=True)
class ContinuationEligibility:
    run_id: str
    reason: str


def assess_session_continuation(root: Path, *, validator: SchemaValidator) -> ContinuationEligibility | None:
    """Return current run when the workspace can accept a follow-up without replanning."""
    agent_dir = root / ".asteria"
    if not agent_dir.exists():
        return None
    run_store = RunStore(agent_dir, validator)
    run_id = run_store.current_session_id()
    if not run_id:
        return None
    run_dir = run_store.run_dir(run_id)
    if not run_dir.exists():
        return None
    run = run_store.load_run(run_id)
    phase = str(run.get("current_phase") or "").strip().upper()
    status = str(run.get("status") or "").strip().lower()
    if phase not in CONTINUABLE_PHASES and status not in CONTINUABLE_RUN_STATUSES:
        return None
    profile = execution_profile_from_run_config(load_run_config(run_dir, validator))
    if not profile.is_session_agent:
        return None
    task_plan_path = run_dir / "task_plan.json"
    if not task_plan_path.exists():
        return None
    return ContinuationEligibility(
        run_id=run_id,
        reason="Warm session continuation: reuse current run and skip GoalSpec/Plan.",
    )


def prepare_session_follow_up(
    root: Path,
    run_id: str,
    follow_up_goal: str,
    *,
    validator: SchemaValidator,
) -> None:
    """Append a follow-up instruction to the current session run and requeue execution."""
    goal = str(follow_up_goal or "").strip()
    if not goal:
        raise SessionContinuationError("Follow-up goal is required for session continuation.")
    agent_dir = root / ".asteria"
    run_store = RunStore(agent_dir, validator)
    run_dir = run_store.run_dir(run_id)
    if not run_dir.exists():
        raise SessionContinuationError(f"Run not found: {run_id}")
    store = JsonStore(validator)
    task_plan_path = run_dir / "task_plan.json"
    task_plan = store.read(task_plan_path, "task_board")
    tasks = list(task_plan.get("tasks") or [])
    if not tasks:
        raise SessionContinuationError("Current run has no tasks to continue.")
    target = _continuation_task(tasks)
    if target is None:
        raise SessionContinuationError("No session task available for warm continuation.")
    target["status"] = "ready"
    target["title"] = goal[:120]
    target["description"] = goal
    target["summary"] = f"Session follow-up: {goal[:160]}"
    target["updated_at"] = now_iso()
    notes = str(target.get("notes") or "").strip()
    target["notes"] = f"{notes}\n[continuation {now_iso()}] {goal}".strip()
    task_plan["tasks"] = tasks
    task_plan["updated_at"] = now_iso()
    store.write(task_plan_path, task_plan, "task_board")

    goal_spec_path = run_dir / "goal_spec.json"
    if goal_spec_path.exists():
        goal_spec = store.read(goal_spec_path, "goal_spec")
        prior = str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or "").strip()
        goal_spec["continuation_goal"] = goal
        goal_spec["normalized_goal"] = f"{prior}\n\nFollow-up:\n{goal}".strip() if prior else goal
        goal_spec["updated_at"] = now_iso()
        store.write(goal_spec_path, goal_spec, "goal_spec")

    run = run_store.load_run(run_id)
    run["status"] = "running"
    run["current_phase"] = "EXECUTE"
    run["summary"] = f"Session follow-up: {goal[:120]}"
    run["updated_at"] = now_iso()
    run_store.update_run(run)

    EventLogger(run_dir / "events.jsonl", validator).record(
        run_id,
        "session_continuation_prepared",
        "SessionContinuation",
        goal[:240],
        {"follow_up_goal": goal},
    )

    memory = ActiveGoalMemory(root)
    structured = memory.read_structured()
    memory.write_from_run(
        goal_spec={
            "goal_id": str(structured.get("goal_id") or "goal-0001"),
            "original_goal": str(structured.get("current_goal") or structured.get("original_goal") or goal),
            "normalized_goal": goal,
            "continuation_of": run_id,
        },
        task_plan=task_plan,
        run_status={"run_id": run_id, "current_phase": "EXECUTE", "status": "running"},
        review_status=str(structured.get("review_status") or "pending"),
        completion="continuation_requested",
        updated_by="session_continuation",
        update_reason="warm_follow_up",
        next_actions=[f"Execute follow-up: {goal[:120]}"],
    )


def _continuation_task(tasks: list[dict]) -> dict | None:
    for task in tasks:
        if str(task.get("task_id") or "") == "task-0001":
            return task
    for task in tasks:
        if str(task.get("status") or "").lower() in {"done", "completed", "accepted"}:
            return task
    return tasks[0] if tasks else None
