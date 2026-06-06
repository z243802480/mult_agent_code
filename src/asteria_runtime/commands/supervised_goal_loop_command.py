from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from asteria_runtime.commands.accept_command import AcceptCommand
from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.run_command import RunCommand
from asteria_runtime.core.north_star import NorthStarStore
from asteria_runtime.core.supervised_goal_loop import (
    SupervisedSliceOutcome,
    run_supervised_goal_loop,
)
from asteria_runtime.resources import schema_dir
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger


@dataclass(frozen=True)
class SupervisedGoalLoopResult:
    ok: bool
    slices_completed: int
    slices_attempted: int
    stop_reason: str
    summary: str
    slice_run_ids: list[str] = field(default_factory=list)
    loop_state_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "ok": self.ok,
            "slices_completed": self.slices_completed,
            "slices_attempted": self.slices_attempted,
            "stop_reason": self.stop_reason,
            "summary": self.summary,
            "slice_run_ids": list(self.slice_run_ids),
            "loop_state_path": str(self.loop_state_path) if self.loop_state_path else None,
        }

    def to_text(self) -> str:
        lines = [
            f"Supervised goal loop: {'ok' if self.ok else 'stopped'}",
            f"Slices completed: {self.slices_completed}/{self.slices_attempted}",
            f"Stop reason: {self.stop_reason}",
            self.summary,
        ]
        if self.slice_run_ids:
            lines.append("Slice runs:")
            lines.extend(f"- {run_id}" for run_id in self.slice_run_ids)
        if self.loop_state_path:
            lines.append(f"Loop state: {self.loop_state_path}")
        return "\n".join(lines)


class SupervisedGoalLoopCommand:
    """Bounded North Star multi-slice loop with kill switch and budget guard."""

    def __init__(
        self,
        root: Path,
        *,
        max_slices: int = 3,
        enable_research: bool = False,
        skip_accept: bool = False,
        permission_level: str = "balanced",
        model_strategy: str = "auto",
        slice_runner: Callable[[str, dict[str, Any]], SupervisedSliceOutcome] | None = None,
        accept_runner: Callable[[str], bool] | None = None,
        validator: SchemaValidator | None = None,
    ) -> None:
        self.root = root.resolve()
        self.max_slices = max_slices
        self.enable_research = enable_research
        self.skip_accept = skip_accept
        self.permission_level = permission_level
        self.model_strategy = model_strategy
        self.slice_runner = slice_runner
        self.accept_runner = accept_runner
        self.validator = validator or SchemaValidator(schema_dir())

    def run(self) -> SupervisedGoalLoopResult:
        if not (self.root / ".asteria").exists():
            InitCommand(self.root).run()
        if not NorthStarStore(self.root, self.validator).exists():
            raise RuntimeError(
                "North Star is not configured. Run `asteria init` with north star or configure "
                "`.asteria/north_star.json` before `--toward-north-star`."
            )

        progress_events: list[dict[str, Any]] = []

        def progress_writer(slice_index: int, phase: str, data: dict[str, Any]) -> None:
            progress_events.append(
                {"slice_index": slice_index, "phase": phase, "data": dict(data)}
            )

        band = run_supervised_goal_loop(
            self.root,
            self.validator,
            max_slices=self.max_slices,
            slice_runner=self._slice_runner,
            accept_runner=self._accept_runner,
            progress_writer=progress_writer,
        )
        self._write_supervision_progress(band.slice_run_ids, progress_events)
        return SupervisedGoalLoopResult(
            ok=band.ok,
            slices_completed=band.slices_completed,
            slices_attempted=band.slices_attempted,
            stop_reason=band.stop_reason,
            summary=band.summary,
            slice_run_ids=list(band.slice_run_ids),
            loop_state_path=band.loop_state_path,
        )

    def _slice_runner(self, goal_text: str, queue_item: dict[str, Any]) -> SupervisedSliceOutcome:
        if self.slice_runner is not None:
            return self.slice_runner(goal_text, queue_item)
        run = RunCommand(
            self.root,
            goal=goal_text,
            enable_research=self.enable_research,
            mode="goal",
            permission_level=self.permission_level,
            model_strategy=self.model_strategy,
        ).run()
        review_status = "pass" if run.status == "completed" else "unknown"
        return SupervisedSliceOutcome(
            run_id=run.run_id,
            status=run.status,
            review_status=review_status,
            ready_for_accept=run.status == "completed",
        )

    def _accept_runner(self, run_id: str) -> bool:
        if self.skip_accept:
            return True
        if self.accept_runner is not None:
            return self.accept_runner(run_id)
        return AcceptCommand(self.root, run_id=run_id, skip_review=True).run().accepted

    def _write_supervision_progress(
        self,
        slice_run_ids: list[str],
        progress_events: list[dict[str, Any]],
    ) -> None:
        if not slice_run_ids:
            return
        last_run_id = slice_run_ids[-1]
        run_dir = self.root / ".asteria" / "runs" / last_run_id
        if not run_dir.exists():
            return
        progress = UserProgressLogger(run_dir / "user_progress.jsonl", self.validator)
        for event in progress_events:
            phase = str(event.get("phase") or "")
            slice_index = int(event.get("slice_index") or 0)
            data = event.get("data") or {}
            if phase == "slice_started":
                progress.record(
                    run_id=last_run_id,
                    channel="progress",
                    phase="execute",
                    status="running",
                    title=f"监督续跑 slice {slice_index}",
                    summary=f"开始 North Star slice：{data.get('goal_text', '')}",
                    data={"supervised_loop": True, **data},
                    display_level="main",
                    transcript_kind="progress",
                )
            elif phase == "slice_completed":
                progress.record(
                    run_id=last_run_id,
                    channel="conclusion",
                    phase="result",
                    status="completed",
                    title=f"监督 slice {slice_index} 已验收",
                    summary="本 slice 已在监督循环内完成 accept。",
                    data={"supervised_loop": True, **data},
                    display_level="main",
                    transcript_kind="final",
                )
