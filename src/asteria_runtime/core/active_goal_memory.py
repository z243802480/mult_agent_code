from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ActiveGoalMemory:
    root: Path

    @property
    def path(self) -> Path:
        return self.root / ".asteria" / "memory" / "active_goal.md"

    def read(self) -> str:
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8")

    def write_from_run(
        self,
        *,
        goal_spec: dict,
        task_plan: dict,
        run_status: dict,
        review_status: str,
        completion: str,
        steps: Sequence[object] | None = None,
        artifacts: list[str] | None = None,
        blockers: list[str] | None = None,
        risks: list[str] | None = None,
        next_actions: list[str] | None = None,
        pending_decisions: list[dict] | None = None,
        accepted_decisions: list[dict] | None = None,
    ) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            self._render(
                goal_spec=goal_spec,
                task_plan=task_plan,
                run_status=run_status,
                review_status=review_status,
                completion=completion,
                steps=steps or [],
                artifacts=artifacts or [],
                blockers=blockers or [],
                risks=risks or [],
                next_actions=next_actions or [],
                pending_decisions=pending_decisions or [],
                accepted_decisions=accepted_decisions or [],
            ),
            encoding="utf-8",
        )
        return self.path

    def _render(
        self,
        *,
        goal_spec: dict,
        task_plan: dict,
        run_status: dict,
        review_status: str,
        completion: str,
        steps: Sequence[object],
        artifacts: list[str],
        blockers: list[str],
        risks: list[str],
        next_actions: list[str],
        pending_decisions: list[dict],
        accepted_decisions: list[dict],
    ) -> str:
        tasks = [task for task in task_plan.get("tasks", []) if isinstance(task, dict)]
        done_tasks = [task for task in tasks if task.get("status") == "done"]
        open_tasks = [task for task in tasks if task.get("status") not in {"done", "discarded"}]
        lines = [
            "# Asteria Active Goal",
            "",
            "## Current Goal",
            "",
            str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or "No goal recorded."),
            "",
            "## Current Result",
            "",
            f"- State: {self._user_state(run_status, completion, review_status)}",
            f"- Review: {self._review_label(review_status)}",
            "",
            "## Overall Plan",
            "",
        ]
        lines.extend(self._task_lines(tasks))
        lines.extend(["", "## Completed Work", ""])
        lines.extend(self._completed_lines(done_tasks, artifacts))
        lines.extend(["", "## How It Was Completed", ""])
        lines.extend(self._step_lines(steps))
        if blockers:
            lines.extend(["", "## Current Blockers", ""])
            lines.extend(f"- {self._clean(item)}" for item in blockers[:8])
        if pending_decisions:
            lines.extend(["", "## Questions For You", ""])
            lines.extend(f"- {self._clean(str(item.get('question') or 'Decision needed.'))}" for item in pending_decisions[:5])
        if accepted_decisions:
            lines.extend(["", "## Decisions Already Made", ""])
            lines.extend(
                (
                    "- "
                    f"{self._clean(str(item.get('question') or 'Decision'))} -> "
                    f"{self._clean(str(item.get('selected_option_id') or 'selected'))}"
                )
                for item in accepted_decisions[:5]
            )
        if risks:
            lines.extend(["", "## Watch Items", ""])
            lines.extend(f"- {self._clean(item)}" for item in risks[:5])
        lines.extend(["", "## Next Task", ""])
        lines.extend(self._next_task_lines(open_tasks, next_actions, completion))
        lines.extend(["", f"_Updated: {now_iso()}_", ""])
        return "\n".join(lines)

    def _task_lines(self, tasks: list[dict]) -> list[str]:
        if not tasks:
            return ["- No task plan has been created yet."]
        return [
            f"- [{self._checkbox(task)}] {self._clean(str(task.get('title') or task.get('task_id') or 'Task'))}"
            for task in tasks[:20]
        ]

    def _completed_lines(self, done_tasks: list[dict], artifacts: list[str]) -> list[str]:
        lines: list[str] = []
        if done_tasks:
            lines.extend(
                f"- {self._clean(str(task.get('summary') or task.get('title') or 'Completed task.'))}"
                for task in done_tasks[:10]
            )
        if artifacts:
            lines.extend(f"- Artifact: `{self._clean(path)}`" for path in artifacts[:10])
        return lines or ["- No completed work has been recorded yet."]

    def _step_lines(self, steps: Sequence[object]) -> list[str]:
        if not steps:
            return ["- Work history will be added as the goal progresses."]
        lines = []
        for step in steps[-10:]:
            name = self._clean(str(getattr(step, "name", "step")))
            status = self._clean(str(getattr(step, "status", "recorded")))
            summary = self._clean(str(getattr(step, "summary", "")))
            lines.append(f"- {name}: {status}" + (f" - {summary}" if summary else ""))
        return lines

    def _next_task_lines(
        self,
        open_tasks: list[dict],
        next_actions: list[str],
        completion: str,
    ) -> list[str]:
        if next_actions:
            return [f"- {self._clean(action)}" for action in next_actions[:5]]
        if open_tasks:
            task = open_tasks[0]
            return [f"- Continue: {self._clean(str(task.get('title') or 'next task'))}"]
        if completion in {"complete", "implemented_needs_review"}:
            return ["- Review the result and accept it if it matches the goal."]
        return ["- Choose the next goal to work on."]

    def _user_state(self, run_status: dict, completion: str, review_status: str) -> str:
        phase = str(run_status.get("current_phase") or "").upper()
        if phase == "ACCEPTED":
            return "accepted"
        if review_status == "pass":
            return "ready to accept"
        return completion.replace("_", " ")

    def _review_label(self, review_status: str) -> str:
        if review_status == "pass":
            return "passed"
        if review_status == "unknown":
            return "not reviewed yet"
        return review_status

    def _checkbox(self, task: dict) -> str:
        if task.get("status") == "done":
            return "x"
        return " "

    def _clean(self, text: str) -> str:
        replacements = {
            ".asteria/": "internal report",
            "run_id": "session",
            "model_route": "model routing",
            "evidence": "work record",
        }
        cleaned = text.replace("\n", " ").strip()
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        return cleaned
