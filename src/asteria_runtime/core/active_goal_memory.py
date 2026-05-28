from __future__ import annotations

import json
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

    @property
    def json_path(self) -> Path:
        return self.root / ".asteria" / "memory" / "active_goal.json"

    def read(self) -> str:
        return self.read_user_markdown()

    def read_user_markdown(self) -> str:
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8")

    def read_structured(self) -> dict:
        if not self.json_path.exists():
            return {}
        try:
            return json.loads(self.json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return self._corrupt_json_recovery(exc)

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
        updated_by: str | None = None,
        update_reason: str | None = None,
    ) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_existing_for_write()
        structured = self._structured(
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
            updated_by=updated_by,
            update_reason=update_reason,
            existing_memory=existing,
        )
        self.json_path.write_text(
            json.dumps(structured, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.path.write_text(
            self._render_from_structured(structured),
            encoding="utf-8",
        )
        return self.path

    def _structured(
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
        updated_by: str | None,
        update_reason: str | None,
        existing_memory: dict,
    ) -> dict:
        tasks = [task for task in task_plan.get("tasks", []) if isinstance(task, dict)]
        done_tasks = [task for task in tasks if task.get("status") == "done"]
        open_tasks = [task for task in tasks if task.get("status") not in {"done", "discarded"}]
        updated_at = now_iso()
        state = self._user_state(run_status, completion, review_status)
        review = self._review_label(review_status)
        conflict_blockers = self._conflict_blockers(existing_memory, run_status)
        damaged_json_blockers = self._damaged_json_blockers(existing_memory)
        all_blockers = [*conflict_blockers, *damaged_json_blockers, *blockers]
        conflict_questions = self._conflict_questions(conflict_blockers)
        return {
            "schema_version": "0.1.0",
            "memory_id": "active-goal",
            "goal_id": str(goal_spec.get("goal_id") or "current-goal"),
            "source_run_id": str(run_status.get("run_id") or ""),
            "updated_at": updated_at,
            "updated_by": updated_by or self._updated_by(run_status, review_status),
            "update_reason": update_reason
            or self._update_reason(run_status, completion, review_status),
            "current_goal": str(
                goal_spec.get("normalized_goal")
                or goal_spec.get("original_goal")
                or "No goal recorded."
            ),
            "current_result": {
                "state": state,
                "review": review,
                "completion": completion,
            },
            "overall_plan": [
                {
                    "task_id": str(task.get("task_id") or ""),
                    "title": self._clean(str(task.get("title") or task.get("task_id") or "Task")),
                    "status": str(task.get("status") or "unknown"),
                    "summary": self._clean(str(task.get("summary") or "")),
                }
                for task in tasks[:20]
            ],
            "completed_work": self._completed_lines(done_tasks, artifacts),
            "how_completed": self._step_lines(steps),
            "current_blockers": [self._clean(item) for item in all_blockers[:8]],
            "questions_for_user": [*conflict_questions, *[
                self._clean(str(item.get("question") or "Decision needed."))
                for item in pending_decisions[:5]
            ]][:5],
            "accepted_decisions": [
                {
                    "question": self._clean(str(item.get("question") or "Decision")),
                    "selected_option_id": self._clean(
                        str(item.get("selected_option_id") or "selected")
                    ),
                }
                for item in accepted_decisions[:5]
            ],
            "watch_items": [self._clean(item) for item in risks[:5]],
            "next_task": self._next_task_lines(open_tasks, next_actions, completion),
            "artifact_refs": [self._clean(path) for path in artifacts[:10]],
        }

    def _render_from_structured(self, memory: dict) -> str:
        plan = [item for item in memory.get("overall_plan", []) if isinstance(item, dict)]
        lines = [
            "# Asteria Active Goal",
            "",
            "## Current Goal",
            "",
            str(memory.get("current_goal") or "No goal recorded."),
            "",
            "## Current Result",
            "",
            f"- State: {(memory.get('current_result') or {}).get('state', 'unknown')}",
            f"- Review: {(memory.get('current_result') or {}).get('review', 'unknown')}",
            "",
            "## Overall Plan",
            "",
        ]
        lines.extend(self._task_lines(plan))
        lines.extend(["", "## Completed Work", ""])
        lines.extend(memory.get("completed_work") or ["- No completed work has been recorded yet."])
        lines.extend(["", "## How It Was Completed", ""])
        lines.extend(memory.get("how_completed") or ["- Work history will be added as the goal progresses."])
        blockers = [str(item) for item in memory.get("current_blockers") or [] if item]
        if blockers:
            lines.extend(["", "## Current Blockers", ""])
            lines.extend(f"- {self._clean(item)}" for item in blockers[:8])
        questions = [str(item) for item in memory.get("questions_for_user") or [] if item]
        if questions:
            lines.extend(["", "## Questions For You", ""])
            lines.extend(f"- {self._clean(item)}" for item in questions[:5])
        decisions = [item for item in memory.get("accepted_decisions") or [] if isinstance(item, dict)]
        if decisions:
            lines.extend(["", "## Decisions Already Made", ""])
            lines.extend(
                (
                    "- "
                    f"{self._clean(str(item.get('question') or 'Decision'))} -> "
                    f"{self._clean(str(item.get('selected_option_id') or 'selected'))}"
                )
                for item in decisions[:5]
            )
        risks = [str(item) for item in memory.get("watch_items") or [] if item]
        if risks:
            lines.extend(["", "## Watch Items", ""])
            lines.extend(f"- {self._clean(item)}" for item in risks[:5])
        lines.extend(["", "## Next Task", ""])
        lines.extend(memory.get("next_task") or ["- Choose the next goal to work on."])
        lines.extend(["", f"_Updated: {memory.get('updated_at') or now_iso()}_", ""])
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

    def _updated_by(self, run_status: dict, review_status: str) -> str:
        phase = str(run_status.get("current_phase") or "").upper()
        if phase == "ACCEPTED":
            return "accept"
        if phase == "REVIEWED" or review_status not in {"unknown", ""}:
            return "review"
        if phase in {"DEBUG", "REPAIR"}:
            return "repair"
        return "run"

    def _update_reason(self, run_status: dict, completion: str, review_status: str) -> str:
        phase = str(run_status.get("current_phase") or "").upper()
        if phase == "ACCEPTED":
            return "accepted_result"
        if review_status == "pass":
            return "review_passed"
        if completion == "implemented_needs_review":
            return "ready_for_review"
        if completion == "blocked":
            return "blocked"
        return "run_progress"

    def _read_existing_for_write(self) -> dict:
        if not self.json_path.exists():
            return {}
        try:
            existing = json.loads(self.json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"recovery": self._corrupt_json_recovery_payload(exc)}
        return existing if isinstance(existing, dict) else {}

    def _corrupt_json_recovery(self, exc: json.JSONDecodeError) -> dict:
        markdown = self.read_user_markdown()
        return {
            "schema_version": "0.1.0",
            "memory_id": "active-goal",
            "goal_id": "current-goal",
            "source_run_id": "",
            "updated_at": now_iso(),
            "updated_by": "run",
            "update_reason": "recovery_from_corrupt_json",
            "current_goal": self._goal_from_markdown(markdown),
            "current_result": {
                "state": "needs repair",
                "review": "unknown",
                "completion": "blocked",
            },
            "overall_plan": [],
            "completed_work": ["- Structured memory could not be read; using Markdown fallback."],
            "how_completed": ["- Repair active_goal.json or regenerate it from the latest run."],
            "current_blockers": [self._corrupt_json_message(exc)],
            "questions_for_user": [
                "Should Asteria regenerate active_goal.json from the latest run evidence?"
            ],
            "accepted_decisions": [],
            "watch_items": ["active_goal.json is damaged"],
            "next_task": ["- Repair or regenerate .asteria/memory/active_goal.json."],
            "artifact_refs": [str(self.path)] if self.path.exists() else [],
        }

    def _corrupt_json_recovery_payload(self, exc: json.JSONDecodeError) -> dict:
        return {
            "status": "corrupt_json",
            "path": str(self.json_path),
            "message": self._corrupt_json_message(exc),
            "fallback_markdown_available": self.path.exists(),
        }

    def _corrupt_json_message(self, exc: json.JSONDecodeError) -> str:
        return (
            "active_goal.json is damaged and could not be parsed "
            f"(line {exc.lineno}, column {exc.colno})."
        )

    def _goal_from_markdown(self, markdown: str) -> str:
        lines = [line.strip() for line in markdown.splitlines()]
        for index, line in enumerate(lines):
            if line == "## Current Goal":
                for candidate in lines[index + 1 :]:
                    if candidate and not candidate.startswith("#"):
                        return self._clean(candidate)
        return "Active goal memory needs repair."

    def _conflict_blockers(self, existing_memory: dict, run_status: dict) -> list[str]:
        existing_run_id = str(existing_memory.get("source_run_id") or "")
        new_run_id = str(run_status.get("run_id") or "")
        if not existing_run_id or not new_run_id or existing_run_id == new_run_id:
            return []
        result = existing_memory.get("current_result") or {}
        if str(result.get("state") or "").lower() == "accepted":
            return []
        return [
            "Active goal memory was previously written by another unfinished run; "
            f"previous={existing_run_id}, current={new_run_id}."
        ]

    def _conflict_questions(self, blockers: list[str]) -> list[str]:
        if not blockers:
            return []
        return ["Confirm which run should own the active long-task memory before accepting."]

    def _damaged_json_blockers(self, existing_memory: dict) -> list[str]:
        recovery = existing_memory.get("recovery") if isinstance(existing_memory, dict) else None
        if not isinstance(recovery, dict) or recovery.get("status") != "corrupt_json":
            return []
        return [str(recovery.get("message") or "active_goal.json was regenerated after damage.")]

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
