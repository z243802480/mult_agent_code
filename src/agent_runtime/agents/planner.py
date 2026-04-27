from __future__ import annotations

from agent_runtime.utils.time import now_iso


class RequirementPlanner:
    """Deterministic MVP planner that turns GoalSpec requirements into reviewable tasks."""

    def build_task_plan(self, goal_spec: dict) -> dict:
        tasks: list[dict] = []
        for index, requirement in enumerate(goal_spec["expanded_requirements"], start=1):
            if requirement["priority"] == "wont":
                continue
            task_id = f"task-{index:04d}"
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
                        "run_command",
                        "run_tests",
                    ],
                    "expected_artifacts": [],
                    "assigned_agent_id": None,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "notes": f"Generated from {requirement['id']}",
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
                    "expected_artifacts": [],
                    "assigned_agent_id": None,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                    "notes": "Fallback task because no actionable requirements were generated.",
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
