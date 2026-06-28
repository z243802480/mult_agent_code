from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.goal_queue import GoalQueueStore
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


KILL_FILE_REL = Path(".asteria") / "STOP"
LOOP_STATE_REL = Path(".asteria") / "supervised_goal_loop.json"
SUPERVISED_LOOP_EVIDENCE_FILE = "supervised_goal_loop_evidence.json"


@dataclass(frozen=True)
class SupervisedSliceOutcome:
    run_id: str
    status: str
    review_status: str = "pass"
    ready_for_accept: bool = True


@dataclass(frozen=True)
class SupervisedGoalLoopBandResult:
    ok: bool
    slices_completed: int
    slices_attempted: int
    stop_reason: str
    summary: str
    slice_run_ids: list[str] = field(default_factory=list)
    loop_state_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "slices_completed": self.slices_completed,
            "slices_attempted": self.slices_attempted,
            "stop_reason": self.stop_reason,
            "summary": self.summary,
            "slice_run_ids": list(self.slice_run_ids),
            "loop_state_path": str(self.loop_state_path) if self.loop_state_path else None,
        }


def kill_file_path(root: Path) -> Path:
    return root.resolve() / KILL_FILE_REL


def loop_state_path(root: Path) -> Path:
    return root.resolve() / LOOP_STATE_REL


def should_stop_supervised_loop(root: Path) -> tuple[bool, str | None]:
    path = kill_file_path(root)
    if path.exists():
        return True, "kill_switch"
    return False, None


def budget_hard_stop_reached(
    root: Path,
    run_id: str,
    validator: SchemaValidator,
) -> tuple[bool, str | None]:
    agent_dir = root / ".asteria"
    policy = load_policy_config(agent_dir, validator)
    cost_path = agent_dir / "runs" / run_id / "cost_report.json"
    if not cost_path.exists():
        return False, None
    report = JsonStore(validator).read(cost_path, "cost_report")
    pressure = BudgetController.pressure(policy, report)
    if pressure["status"] in {"hard_stop", "exceeded"}:
        return True, pressure["status"]
    return False, None


def persist_loop_state(root: Path, payload: dict[str, Any], validator: SchemaValidator) -> Path:
    path = loop_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # No schema contract for the supervised-loop state object (HIDE_NOT_DELETE feature);
    # explicit opt-out keeps the skip auditable rather than silent.
    JsonStore(validator).write(path, payload, allow_unvalidated=True)
    return path


def write_slice_evidence(
    run_dir: Path,
    *,
    slice_index: int,
    goal_id: str,
    goal_text: str,
    stop_reason: str | None,
    validator: SchemaValidator,
) -> Path:
    payload = {
        "schema_version": "0.1.0",
        "recorded_at": now_iso(),
        "slice_index": slice_index,
        "goal_id": goal_id,
        "goal_text": goal_text,
        "stop_reason": stop_reason,
        "supervised_loop_evidence": True,
    }
    path = run_dir / SUPERVISED_LOOP_EVIDENCE_FILE
    # No schema contract for this evidence object (HIDE_NOT_DELETE feature); explicit opt-out.
    JsonStore(validator).write(path, payload, allow_unvalidated=True)
    return path


SliceRunner = Callable[[str, dict[str, Any]], SupervisedSliceOutcome]
AcceptRunner = Callable[[str], bool]


def run_supervised_goal_loop(
    root: Path,
    validator: SchemaValidator,
    *,
    max_slices: int = 3,
    slice_runner: SliceRunner,
    accept_runner: AcceptRunner,
    progress_writer: Callable[[int, str, dict[str, Any]], None] | None = None,
) -> SupervisedGoalLoopBandResult:
    root = root.resolve()
    if max_slices < 1:
        raise ValueError("max_slices must be at least 1")
    if not NorthStarStore(root, validator).exists():
        return SupervisedGoalLoopBandResult(
            ok=False,
            slices_completed=0,
            slices_attempted=0,
            stop_reason="north_star_missing",
            summary="North Star is not configured.",
        )

    queue = GoalQueueStore(root, validator)
    queue.ensure_seeded_from_north_star()

    slices_completed = 0
    slices_attempted = 0
    slice_run_ids: list[str] = []
    stop_reason = "max_slices_reached"

    for slice_index in range(max_slices):
        stopped, reason = should_stop_supervised_loop(root)
        if stopped:
            stop_reason = reason or "kill_switch"
            break

        next_item = queue.next_pending()
        if not next_item:
            stop_reason = "queue_empty"
            break

        goal_id = str(next_item.get("goal_id") or "")
        goal_text = str(next_item.get("goal_text") or "").strip()
        if not goal_text:
            stop_reason = "invalid_queue_item"
            break

        queue.mark_in_progress(goal_id)
        slices_attempted += 1

        outcome = slice_runner(goal_text, next_item)
        if progress_writer:
            progress_writer(
                slice_index + 1,
                "slice_started",
                {"goal_id": goal_id, "goal_text": goal_text, "run_id": outcome.run_id},
            )
        queue.link_run_to_goal(goal_id, outcome.run_id)
        slice_run_ids.append(outcome.run_id)
        run_dir = root / ".asteria" / "runs" / outcome.run_id
        write_slice_evidence(
            run_dir,
            slice_index=slice_index + 1,
            goal_id=goal_id,
            goal_text=goal_text,
            stop_reason=None,
            validator=validator,
        )

        hard_stop, budget_status = budget_hard_stop_reached(root, outcome.run_id, validator)
        if hard_stop:
            stop_reason = f"budget_{budget_status}"
            queue.release_in_progress(goal_id)
            break

        if outcome.status in {"blocked", "paused"}:
            stop_reason = f"run_{outcome.status}"
            queue.release_in_progress(goal_id)
            break

        if not outcome.ready_for_accept:
            stop_reason = "awaiting_accept"
            break

        if not accept_runner(outcome.run_id):
            stop_reason = "accept_blocked"
            queue.release_in_progress(goal_id)
            break

        slices_completed += 1
        if progress_writer:
            progress_writer(
                slice_index + 1,
                "slice_completed",
                {"run_id": outcome.run_id, "goal_id": goal_id},
            )

    loop_state = {
        "schema_version": "0.1.0",
        "status": "completed" if slices_completed >= max_slices else "stopped",
        "max_slices": max_slices,
        "slices_attempted": slices_attempted,
        "slices_completed": slices_completed,
        "stop_reason": stop_reason,
        "slice_run_ids": slice_run_ids,
        "updated_at": now_iso(),
    }
    state_path = persist_loop_state(root, loop_state, validator)
    ok = slices_completed > 0 and stop_reason in {"max_slices_reached", "queue_empty"}
    summary = (
        f"Supervised loop completed {slices_completed}/{slices_attempted} slice(s); "
        f"stop_reason={stop_reason}."
    )
    return SupervisedGoalLoopBandResult(
        ok=ok,
        slices_completed=slices_completed,
        slices_attempted=slices_attempted,
        stop_reason=stop_reason,
        summary=summary,
        slice_run_ids=slice_run_ids,
        loop_state_path=state_path,
    )


def prepare_accept_ready_run(
    root: Path,
    validator: SchemaValidator,
    goal_text: str,
) -> str:
    """Band/test helper: create a minimal run that AcceptCommand(skip_review=True) can finalize."""
    from asteria_runtime.core.candidate_workspace import CandidateWorkspace
    from asteria_runtime.storage.jsonl_store import JsonlStore
    from asteria_runtime.storage.run_store import RunStore

    agent_dir = root / ".asteria"
    store = JsonStore(validator)
    run_store = RunStore(agent_dir, validator)
    run = run_store.create_run(goal_text)
    run_store.set_current_session(run["run_id"], "session")
    run_dir = run_store.run_dir(run["run_id"])
    tool_path = root / "tool.py"
    tool_path.write_text("VALUE = 1\n", encoding="utf-8")
    store.write(
        run_dir / "goal_spec.json",
        {
            "schema_version": "0.1.0",
            "goal_id": "goal-0001",
            "original_goal": goal_text,
            "normalized_goal": goal_text,
            "goal_type": "codebase_improvement",
            "assumptions": [],
            "constraints": [],
            "non_goals": [],
            "expanded_requirements": [
                {
                    "id": "req-0001",
                    "priority": "must",
                    "description": goal_text,
                    "source": "user",
                    "acceptance": ["done"],
                }
            ],
            "target_outputs": ["tool.py"],
            "definition_of_done": ["done"],
            "verification_strategy": ["review pass"],
            "budget": {},
        },
        "goal_spec",
    )
    store.write(
        run_dir / "task_plan.json",
        {
            "schema_version": "0.1.0",
            "tasks": [
                {
                    "task_id": "task-0001",
                    "title": goal_text,
                    "description": goal_text,
                    "status": "done",
                    "depends_on": [],
                    "acceptance": ["tool.py updated"],
                    "expected_artifacts": ["tool.py"],
                }
            ],
        },
        "task_board",
    )
    store.write(
        run_dir / "cost_report.json",
        {
            "schema_version": "0.1.0",
            "run_id": run["run_id"],
            "model_calls": 1,
            "tool_calls": 1,
            "estimated_input_tokens": 1,
            "estimated_output_tokens": 1,
            "strong_model_calls": 0,
            "cheap_model_calls": 0,
            "repair_attempts": 0,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        },
        "cost_report",
    )
    store.write(
        run_dir / "eval_report.json",
        {
            "schema_version": "0.1.0",
            "run_id": run["run_id"],
            "goal_eval": {},
            "artifact_eval": {},
            "outcome_eval": {},
            "trajectory_eval": {},
            "cost_eval": {},
            "overall": {"status": "pass", "score": 0.95, "reason": "band review"},
        },
        "eval_report",
    )
    candidate = CandidateWorkspace.create(root, run_dir, "task-0001")
    jsonl = JsonlStore(validator)
    jsonl.append(
        run_dir / "candidate_promotions.jsonl",
        {
            "schema_version": "0.1.0",
            "promotion_id": "promotion-0001",
            "run_id": run["run_id"],
            "task_id": "task-0001",
            "candidate_id": candidate.candidate_id,
            "workspace": str(candidate.root),
            "strategy": candidate.strategy,
            "workspace_policy": candidate.workspace_policy,
            "backend_reason": candidate.backend_reason,
            "branch_name": candidate.branch_name,
            "promotable_files": ["tool.py"],
            "promoted_files": [],
            "status": "pending_manual_approval",
            "approval_mode": "manual",
            "merge_gate": {"ok": True},
            "failure": None,
            "decision": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        },
        "candidate_promotion",
    )
    (candidate.root / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
    return run["run_id"]


def run_supervised_goal_loop_band(
    root: Path,
    validator: SchemaValidator,
    *,
    max_slices: int = 2,
) -> SupervisedGoalLoopBandResult:
    from asteria_runtime.commands.accept_command import AcceptCommand
    from asteria_runtime.commands.init_command import InitCommand

    root.mkdir(parents=True, exist_ok=True)
    InitCommand(root).run()
    NorthStarStore(root, validator).create_default(
        title="Supervised loop band",
        statement="Demonstrate bounded North Star slices",
        milestone_titles=["Band slice 1", "Band slice 2", "Band slice 3"],
    )

    def slice_runner(goal_text: str, _item: dict[str, Any]) -> SupervisedSliceOutcome:
        run_id = prepare_accept_ready_run(root, validator, goal_text)
        return SupervisedSliceOutcome(run_id=run_id, status="completed")

    def accept_runner(run_id: str) -> bool:
        return AcceptCommand(root, run_id=run_id, skip_review=True).run().accepted

    return run_supervised_goal_loop(
        root,
        validator,
        max_slices=max_slices,
        slice_runner=slice_runner,
        accept_runner=accept_runner,
    )
