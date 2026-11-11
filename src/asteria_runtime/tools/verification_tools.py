from __future__ import annotations

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.verification_revision import load_method_authority, revise_method
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.tools.base import ToolResult


class ReviseVerificationTool:
    name = "revise_verification"

    def run(
        self, context: RuntimeContext, original_command: str, replacement_command: str,
        reason: str, coverage: str,
    ) -> ToolResult:
        if context.run_dir is None or not context.task_id:
            raise PermissionError("A method revision requires a runtime-bound current task")
        store = JsonStore(context.validator)
        path = context.run_dir / "task_plan.json"
        board = store.read(path, "task_board")
        task = next(t for t in board["tasks"] if t["task_id"] == context.task_id)
        context.validator.validate("task", task)
        goal = store.read(context.run_dir / "goal_spec.json", "goal_spec")
        project = store.read(context.asteria_dir / "project.json", "project_config")
        authority = load_method_authority(context.root, project["commands"])
        if authority is None:
            raise PermissionError("Complete project guidance is unavailable for method authority")
        guidance = authority["root_guidance"].get("content")
        records = JsonlStore(context.validator).read_all(
            context.run_dir / "tool_observations.jsonl", "tool_observation",
        )
        records = [r for r in records if r.get("run_id") == context.run_id]
        revised = revise_method(
            task, goal, guidance, project["commands"], records, original_command=original_command,
            replacement_command=replacement_command, reason=reason, coverage=coverage,
        )
        context.validator.validate("task", revised)
        board["tasks"] = [revised if t["task_id"] == context.task_id else t for t in board["tasks"]]
        store.write(path, board, "task_board")
        return ToolResult(
            ok=True, summary="Revised planner method; original failure retained, requirements unchanged",
            data={"task_id": context.task_id,
                  "revision": revised["verification_policy"]["method_revisions"][-1]},
        )
