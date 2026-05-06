from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class TaskPlanIssue:
    task_id: str | None
    severity: str
    code: str
    message: str
    recommendation: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "task_id": self.task_id,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "recommendation": self.recommendation,
        }


class TaskPlanEvaluator:
    """Deterministic quality gate for task granularity and verifiability."""

    def evaluate(
        self,
        task_plan: dict[str, Any],
        goal_spec: dict[str, Any],
        run_id: str | None = None,
    ) -> dict[str, Any]:
        tasks = [task for task in task_plan.get("tasks", []) if isinstance(task, dict)]
        issues: list[TaskPlanIssue] = []
        issues.extend(self._board_issues(tasks, goal_spec))
        for task in tasks:
            issues.extend(self._task_issues(task))

        scores = self._scores(tasks, issues)
        overall_score = round(
            (
                scores["granularity_score"]
                + scores["dependency_score"]
                + scores["acceptance_score"]
                + scores["artifact_score"]
                + scores["tooling_score"]
            )
            / 5,
            3,
        )
        status = self._status(overall_score, issues)
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "created_at": now_iso(),
            "status": status,
            "overall_score": overall_score,
            "scores": scores,
            "summary": self._summary(status, overall_score, issues),
            "issues": [issue.to_dict() for issue in issues],
            "recommendations": self._recommendations(issues),
            "task_count": len(tasks),
        }

    def _board_issues(self, tasks: list[dict[str, Any]], goal_spec: dict[str, Any]) -> list[TaskPlanIssue]:
        issues: list[TaskPlanIssue] = []
        if not tasks:
            issues.append(
                TaskPlanIssue(
                    None,
                    "error",
                    "empty_plan",
                    "Task plan has no tasks.",
                    "Regenerate the plan from the goal specification.",
                )
            )
            return issues

        ready_tasks = [task for task in tasks if task.get("status") == "ready"]
        if not ready_tasks:
            issues.append(
                TaskPlanIssue(
                    None,
                    "error",
                    "no_ready_task",
                    "Task plan has no ready entry task.",
                    "Mark the first executable task as ready.",
                )
            )
        if len(ready_tasks) > 2 and len(tasks) <= 6:
            issues.append(
                TaskPlanIssue(
                    None,
                    "warning",
                    "too_many_entrypoints",
                    "Task plan has many ready tasks for a small plan.",
                    "Add dependencies or sequence tasks into a clear implementation path.",
                )
            )

        task_ids = [str(task.get("task_id") or "") for task in tasks]
        duplicate_ids = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
        for task_id in duplicate_ids:
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "error",
                    "duplicate_task_id",
                    f"Task id {task_id} appears more than once.",
                    "Regenerate unique task ids before execution.",
                )
            )

        known_ids = set(task_ids)
        for task in tasks:
            task_id = str(task.get("task_id") or "unknown")
            depends_on = task.get("depends_on", [])
            if not isinstance(depends_on, list):
                issues.append(
                    TaskPlanIssue(
                        task_id,
                        "error",
                        "invalid_dependencies",
                        "Task dependencies must be a list.",
                        "Use an explicit list of task ids in depends_on.",
                    )
                )
                continue
            for dependency in depends_on:
                if dependency not in known_ids:
                    issues.append(
                        TaskPlanIssue(
                            task_id,
                            "error",
                            "missing_dependency",
                            f"Dependency {dependency!r} does not exist.",
                            "Remove the dependency or create the referenced task.",
                        )
                    )
                if dependency == task_id:
                    issues.append(
                        TaskPlanIssue(
                            task_id,
                            "error",
                            "self_dependency",
                            "Task depends on itself.",
                            "Remove the self dependency.",
                        )
                    )

        must_requirements = [
            requirement
            for requirement in goal_spec.get("expanded_requirements", [])
            if isinstance(requirement, dict) and requirement.get("priority") == "must"
        ]
        if len(tasks) < min(2, len(must_requirements)) and len(must_requirements) >= 3:
            issues.append(
                TaskPlanIssue(
                    None,
                    "warning",
                    "under_decomposed_plan",
                    "Several must requirements were collapsed into too few tasks.",
                    "Split the plan into independently verifiable implementation slices.",
                )
            )
        if len(tasks) > 12:
            issues.append(
                TaskPlanIssue(
                    None,
                    "warning",
                    "over_decomposed_plan",
                    "Task plan has more than 12 tasks for one MVP goal.",
                    "Merge tiny tasks that share the same artifact and verification path.",
                )
            )
        return issues

    def _task_issues(self, task: dict[str, Any]) -> list[TaskPlanIssue]:
        task_id = str(task.get("task_id") or "unknown")
        issues: list[TaskPlanIssue] = []
        description = str(task.get("description") or "").strip()
        title = str(task.get("title") or "").strip()
        acceptance = [
            str(item).strip()
            for item in task.get("acceptance", [])
            if isinstance(item, str) and item.strip()
        ]
        artifacts = [
            str(item).strip()
            for item in task.get("expected_artifacts", [])
            if isinstance(item, str) and item.strip()
        ]
        tools = [
            str(item).strip()
            for item in task.get("allowed_tools", [])
            if isinstance(item, str) and item.strip()
        ]
        kind = str(task.get("task_kind") or "implementation")

        if len(title.split()) < 2 and len(title) < 8:
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "warning",
                    "vague_title",
                    "Task title is too vague to scan quickly.",
                    "Use a short verb-object title that names the intended artifact.",
                )
            )
        if len(description.split()) < 4:
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "error",
                    "vague_description",
                    "Task description is too short to execute safely.",
                    "Describe the implementation slice, behavior, and target artifact.",
                )
            )
        if not acceptance:
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "error",
                    "missing_acceptance",
                    "Task has no acceptance criteria.",
                    "Add 1-4 observable acceptance criteria.",
                )
            )
        if len(acceptance) > 4 and task.get("task_id") != "task-0001":
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "warning",
                    "oversized_acceptance",
                    "Task has more than 4 acceptance criteria.",
                    "Split the task by artifact or behavior so each slice can be verified.",
                )
            )
        if acceptance and not any(self._is_observable(item) for item in acceptance):
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "warning",
                    "weak_acceptance",
                    "Acceptance criteria do not name observable behavior, files, tests, or commands.",
                    "Rewrite at least one criterion so a tool or reviewer can verify it.",
                )
            )
        if kind in {"implementation", "ui", "report"} and not artifacts:
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "error",
                    "missing_artifact",
                    "Deliverable task has no expected artifact.",
                    "Add expected_artifacts for files, reports, UI assets, or test outputs.",
                )
            )
        if any(artifact in {"implementation artifact", "planning artifact"} for artifact in artifacts):
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "warning",
                    "generic_artifact",
                    "Task uses a generic expected artifact.",
                    "Replace generic artifact names with concrete file paths or report names.",
                )
            )
        if kind in {"implementation", "ui"} and "apply_patch" not in tools and "write_file" not in tools:
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "error",
                    "missing_write_tool",
                    "Implementation task cannot write changes with its allowed tools.",
                    "Allow apply_patch or write_file for implementation tasks.",
                )
            )
        if task.get("verification_policy", {}).get("required") and "run_tests" not in tools and "run_command" not in tools:
            issues.append(
                TaskPlanIssue(
                    task_id,
                    "warning",
                    "missing_verification_tool",
                    "Task requires verification but has no command/test tool.",
                    "Allow run_tests or run_command so acceptance can be checked.",
                )
            )
        return issues

    def _scores(self, tasks: list[dict[str, Any]], issues: list[TaskPlanIssue]) -> dict[str, float]:
        return {
            "granularity_score": self._score(issues, {"under_decomposed_plan", "over_decomposed_plan", "oversized_acceptance"}),
            "dependency_score": self._score(issues, {"missing_dependency", "self_dependency", "invalid_dependencies", "no_ready_task", "too_many_entrypoints"}),
            "acceptance_score": self._score(issues, {"missing_acceptance", "weak_acceptance"}),
            "artifact_score": self._score(issues, {"missing_artifact", "generic_artifact"}),
            "tooling_score": self._score(issues, {"missing_write_tool", "missing_verification_tool"}),
        } if tasks else {
            "granularity_score": 0.0,
            "dependency_score": 0.0,
            "acceptance_score": 0.0,
            "artifact_score": 0.0,
            "tooling_score": 0.0,
        }

    def _score(self, issues: list[TaskPlanIssue], codes: set[str]) -> float:
        score = 1.0
        for issue in issues:
            if issue.code not in codes:
                continue
            score -= 0.25 if issue.severity == "error" else 0.12
        return round(max(0.0, score), 3)

    def _status(self, overall_score: float, issues: list[TaskPlanIssue]) -> str:
        if any(issue.severity == "error" for issue in issues) or overall_score < 0.70:
            return "fail"
        if issues or overall_score < 0.85:
            return "warn"
        return "pass"

    def _summary(self, status: str, overall_score: float, issues: list[TaskPlanIssue]) -> str:
        error_count = sum(1 for issue in issues if issue.severity == "error")
        warning_count = sum(1 for issue in issues if issue.severity == "warning")
        return (
            f"Task plan quality {status} with score {overall_score:.2f}; "
            f"{error_count} error(s), {warning_count} warning(s)."
        )

    def _recommendations(self, issues: list[TaskPlanIssue]) -> list[str]:
        recommendations = [issue.recommendation for issue in issues]
        return list(dict.fromkeys(recommendations))[:10]

    def _is_observable(self, value: str) -> bool:
        text = value.lower()
        markers = {
            "exists",
            "created",
            "updated",
            "returns",
            "prints",
            "shows",
            "passes",
            "contains",
            "matches",
            "command",
            "test",
            "file",
            "report",
            "\u8fd0\u884c",
            "\u663e\u793a",
            "\u751f\u6210",
            "\u901a\u8fc7",
            "\u8fd4\u56de",
            "\u5305\u542b",
        }
        return any(marker in text for marker in markers)
