from __future__ import annotations

from agent_runtime.utils.time import now_iso


class RequirementPlanner:
    """Deterministic MVP planner that turns GoalSpec requirements into reviewable tasks."""

    def build_task_plan(self, goal_spec: dict, runtime_context: dict | None = None) -> dict:
        runtime_context = runtime_context or {}
        tasks: list[dict] = []
        for index, requirement in enumerate(goal_spec["expanded_requirements"], start=1):
            if requirement["priority"] == "wont":
                continue
            task_id = f"task-{index:04d}"
            expected_artifacts = self._expected_artifacts(requirement, goal_spec)
            tasks.append(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "title": self._title(requirement["description"]),
                    "description": requirement["description"],
                    "status": "ready" if not tasks else "backlog",
                    "priority": self._priority(requirement["priority"]),
                    "role": "CoderAgent",
                    "depends_on": [] if not tasks else [tasks[-1]["task_id"]],
                    "acceptance": requirement["acceptance"],
                    "allowed_tools": [
                        "read_file",
                        "search_text",
                        "write_file",
                        "apply_patch",
                        "restore_backup",
                        "run_command",
                        "run_tests",
                    ],
                    "expected_artifacts": expected_artifacts,
                    "assigned_agent_id": None,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "notes": self._notes(
                        requirement["id"],
                        requirement,
                        expected_artifacts,
                        runtime_context,
                    ),
                }
            )

        if not tasks:
            tasks.append(
                {
                    "schema_version": "0.1.0",
                    "task_id": "task-0001",
                    "title": "Clarify goal and create first implementation slice",
                    "description": goal_spec["normalized_goal"],
                    "status": "ready",
                    "priority": "high",
                    "role": "PlannerAgent",
                    "depends_on": [],
                    "acceptance": goal_spec["definition_of_done"][:3] or ["Goal is clarified"],
                    "allowed_tools": ["read_file", "search_text", "write_file"],
                    "expected_artifacts": self._fallback_artifacts(goal_spec),
                    "assigned_agent_id": None,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "notes": (
                        "Fallback task because no actionable requirements were generated. "
                        "Quality: clarity=0.60 testability=0.60 size=0.70 artifact=0.60."
                    ),
                }
            )
        return {"schema_version": "0.1.0", "tasks": tasks}

    def _priority(self, value: str) -> str:
        return {
            "must": "high",
            "should": "medium",
            "could": "low",
            "wont": "low",
        }[value]

    def _title(self, description: str) -> str:
        trimmed = description.strip()
        if len(trimmed) <= 60:
            return trimmed
        return trimmed[:57].rstrip() + "..."

    def _expected_artifacts(self, requirement: dict, goal_spec: dict) -> list[str]:
        explicit = requirement.get("expected_artifacts")
        if isinstance(explicit, list) and explicit:
            return [str(item) for item in explicit]
        description = str(requirement.get("description", "")).lower()
        target_outputs = {str(item).lower() for item in goal_spec.get("target_outputs", [])}
        artifacts: list[str] = []
        if "readme" in target_outputs or "doc" in description or "documentation" in description:
            artifacts.append("README.md")
        if "test" in description or "unit_tests" in goal_spec.get("verification_strategy", []):
            artifacts.append("tests/")
        if any(output in target_outputs for output in ["local_cli", "cli", "python_module"]):
            artifacts.append("src/")
        if any(output in target_outputs for output in ["report", "markdown_report"]):
            artifacts.append("report.md")
        if not artifacts:
            artifacts.append("implementation artifact")
        return list(dict.fromkeys(artifacts))

    def _fallback_artifacts(self, goal_spec: dict) -> list[str]:
        outputs = [str(item) for item in goal_spec.get("target_outputs", [])]
        return outputs or ["planning artifact"]

    def _notes(
        self,
        requirement_id: str,
        requirement: dict,
        expected_artifacts: list[str],
        runtime_context: dict,
    ) -> str:
        scores = self._quality_scores(requirement, expected_artifacts)
        context_note = self._context_note(runtime_context)
        return (
            f"Generated from {requirement_id}. "
            "Quality: "
            f"clarity={scores['clarity']:.2f} "
            f"testability={scores['testability']:.2f} "
            f"size={scores['size']:.2f} "
            f"artifact={scores['artifact']:.2f}."
            f"{context_note}"
        )

    def _quality_scores(self, requirement: dict, expected_artifacts: list[str]) -> dict[str, float]:
        description = str(requirement.get("description", "")).strip()
        acceptance = requirement.get("acceptance", [])
        acceptance_count = len(acceptance) if isinstance(acceptance, list) else 0
        return {
            "clarity": 0.85 if len(description.split()) >= 4 else 0.65,
            "testability": 0.85 if acceptance_count >= 1 else 0.55,
            "size": 0.80 if acceptance_count <= 4 else 0.65,
            "artifact": 0.85 if expected_artifacts else 0.50,
        }

    def _context_note(self, runtime_context: dict) -> str:
        memory_count = len(runtime_context.get("memory", []))
        snapshot_id = runtime_context.get("latest_snapshot", {}).get("snapshot_id")
        handoff_id = runtime_context.get("latest_handoff", {}).get("handoff_id")
        parts = []
        if memory_count:
            parts.append(f"{memory_count} memory entr{'y' if memory_count == 1 else 'ies'}")
        if snapshot_id:
            parts.append(f"snapshot {snapshot_id}")
        if handoff_id:
            parts.append(f"handoff {handoff_id}")
        return f" Context: {', '.join(parts)}." if parts else ""


class FollowUpTaskPlanner:
    def build_follow_up_tasks(self, eval_report: dict, existing_tasks: list[dict]) -> list[dict]:
        follow_ups = eval_report.get("outcome_eval", {}).get("follow_up_tasks", [])
        if not follow_ups:
            follow_ups = eval_report.get("trajectory_eval", {}).get("follow_up_tasks", [])
        if not isinstance(follow_ups, list):
            return []

        next_index = self._next_index(existing_tasks)
        done_or_ready = [
            task["task_id"] for task in existing_tasks if task["status"] != "discarded"
        ]
        known_items = {
            self._normalize(task.get("title", "")) for task in existing_tasks
        } | {
            self._normalize(task.get("description", "")) for task in existing_tasks
        }
        dependency = done_or_ready[-1:] if done_or_ready else []
        tasks: list[dict] = []
        for item in follow_ups:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or item.get("title") or "").strip()
            if not description:
                continue
            title = self._title(str(item.get("title") or description))
            if self._normalize(title) in known_items or self._normalize(description) in known_items:
                continue
            task_id = f"task-{next_index:04d}"
            next_index += 1
            acceptance = item.get("acceptance")
            expected_artifacts = item.get("expected_artifacts")
            if not isinstance(acceptance, list) or not acceptance:
                acceptance = ["Follow-up requirement is implemented and verified"]
            if not isinstance(expected_artifacts, list):
                expected_artifacts = []
            tasks.append(
                {
                    "schema_version": "0.1.0",
                    "task_id": task_id,
                    "title": title,
                    "description": description,
                    "status": "ready" if not dependency and not tasks else "backlog",
                    "priority": self._priority(str(item.get("priority") or "medium")),
                    "role": str(item.get("role") or "CoderAgent"),
                    "depends_on": dependency if not tasks else [tasks[-1]["task_id"]],
                    "acceptance": [str(value) for value in acceptance],
                    "allowed_tools": [
                        "read_file",
                        "search_text",
                    "write_file",
                    "apply_patch",
                    "restore_backup",
                    "run_command",
                    "run_tests",
                    ],
                    "expected_artifacts": expected_artifacts,
                    "assigned_agent_id": None,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "notes": f"Generated from review follow-up for {eval_report.get('run_id')}",
                }
            )
            known_items.add(self._normalize(title))
            known_items.add(self._normalize(description))
        return tasks

    def _next_index(self, tasks: list[dict]) -> int:
        indexes = []
        for task in tasks:
            suffix = task["task_id"].rsplit("-", 1)[-1]
            if suffix.isdigit():
                indexes.append(int(suffix))
        return (max(indexes) + 1) if indexes else 1

    def _priority(self, value: str) -> str:
        return value if value in {"critical", "high", "medium", "low"} else "medium"

    def _title(self, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) <= 60:
            return trimmed
        return trimmed[:57].rstrip() + "..."

    def _normalize(self, value: object) -> str:
        return " ".join(str(value).strip().lower().split())
