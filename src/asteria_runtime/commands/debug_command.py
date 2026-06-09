from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.execute_command import ExecuteCommand
from asteria_runtime.models.base import ModelClient
from asteria_runtime.core.runtime_evidence import RuntimeEvidenceReader
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.core.task_board import TaskBoard


@dataclass(frozen=True)
class RepairSummary:
    task_id: str
    status: str
    summary: str
    repair_calls: int
    verification_calls: int
    evidence_path: Path | None = None


@dataclass(frozen=True)
class DebugResult:
    run_id: str
    repaired: int
    still_blocked: int
    repairs: list[RepairSummary] = field(default_factory=list)
    cost_report_path: Path | None = None

    def to_text(self) -> str:
        lines = [
            f"Continued failed work in session: {self.run_id}",
            f"Completed tasks: {self.repaired}",
            f"Still blocked: {self.still_blocked}",
        ]
        for repair in self.repairs:
            lines.append(
                f"- {repair.task_id}: {repair.status} "
                f"({repair.repair_calls} tool, {repair.verification_calls} verification)"
            )
            if repair.evidence_path:
                lines.append(f"  evidence: {repair.evidence_path}")
        if self.cost_report_path:
            lines.append(f"Cost report: {self.cost_report_path}")
        return "\n".join(lines)


class DebugCommand:
    """Explicit compatibility action that continues failed work in the current Session loop."""

    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        task_id: str | None = None,
        max_repairs: int = 1,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.task_id = task_id
        self.max_repairs = max(1, max_repairs)
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.runtime_evidence = RuntimeEvidenceReader(self.validator)

    def run(self) -> DebugResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")

        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `asteria plan` first.")
        run_dir = run_store.run_dir(run_id)
        task_board = TaskBoard(run_dir / "task_plan.json", self.validator)
        selected = self._failed_tasks(task_board)[: self.max_repairs]
        if not selected:
            return DebugResult(
                run_id=run_id,
                repaired=0,
                still_blocked=0,
                cost_report_path=run_dir / "cost_report.json",
            )

        task_ids = {str(task["task_id"]) for task in selected}
        for task_id in task_ids:
            self._requeue_for_session(task_board, task_id)

        progress = UserProgressLogger(run_dir / "user_progress.jsonl", self.validator)
        progress.record(
            run_id=run_id,
            channel="progress",
            event_type="message",
            phase="execute",
            status="running",
            title="继续处理失败任务",
            summary=f"已将 {len(task_ids)} 个失败任务连同已有证据交回当前 Session 继续处理。",
            display_level="main",
            call_chain=["DebugCommand", "ExecuteCommand"],
            execution_chain=["explicit_debug", "session_agent_loop"],
            transcript_kind="progress",
            ui_intent="work_progress",
            data={"task_ids": sorted(task_ids)},
        )
        EventLogger(run_dir / "events.jsonl", self.validator).record(
            run_id,
            "session_recovery_requested",
            "DebugCommand",
            "Explicit debug continued failed work through ExecuteCommand.",
            {"task_ids": sorted(task_ids)},
        )

        execution = ExecuteCommand(
            self.root,
            run_id=run_id,
            max_tasks=len(task_ids),
            model_client=self.model_client,
            task_ids=task_ids,
            context_overrides={
                "session_recovery": {
                    "intent": "diagnose_and_continue",
                    "task_ids": sorted(task_ids),
                    "task_evidence": {
                        task_id: self.runtime_evidence.task_evidence(run_dir, task_id)
                        for task_id in sorted(task_ids)
                    },
                }
            },
        ).run()
        repairs = [
            RepairSummary(
                task_id=item.task_id,
                status=item.status,
                summary=item.summary,
                repair_calls=item.tool_calls,
                verification_calls=item.verification_calls,
                evidence_path=item.evidence_path,
            )
            for item in execution.executed_tasks
        ]
        return DebugResult(
            run_id=run_id,
            repaired=len([item for item in repairs if item.status == "done"]),
            still_blocked=len([item for item in repairs if item.status == "blocked"]),
            repairs=repairs,
            cost_report_path=execution.cost_report_path,
        )

    def _failed_tasks(self, task_board: TaskBoard) -> list[dict]:
        if self.task_id:
            task = task_board.get_task(self.task_id)
            return [task] if self._task_needs_debug_repair(task) else []
        return [
            task for task in task_board.list_tasks() if self._task_needs_debug_repair(task)
        ]

    def _task_needs_debug_repair(self, task: dict) -> bool:
        status = str(task.get("status") or "")
        if status == "blocked":
            return True
        if status not in {"in_progress", "testing", "reviewing"}:
            return False
        notes = str(task.get("notes") or "").lower()
        return any(
            marker in notes
            for marker in (
                "contract violated",
                "tool failed",
                "tool is not allowed",
                "permission denied",
                "repair",
                "verification did not pass",
            )
        )

    def _requeue_for_session(self, task_board: TaskBoard, task_id: str) -> None:
        status = str(task_board.get_task(task_id).get("status") or "")
        if status == "ready":
            return
        if status != "blocked":
            task_board.update_status(task_id, "blocked")
        task_board.update_status(task_id, "ready")
