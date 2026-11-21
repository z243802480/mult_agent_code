from __future__ import annotations

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.verification_revision import load_method_authority, revise_method
from asteria_runtime.core.verification_references import (
    current_reference_task, referenced_command, referenced_observation, verification_methods,
)
from asteria_runtime.core.task_verification import observation_command
from asteria_runtime.core.agent_harness import ToolObservation
from asteria_runtime.core.verification_evidence import VerificationEvidenceError
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.tools.base import ToolResult


class ReviseVerificationTool:
    name = "revise_verification"

    def run(
        self, context: RuntimeContext, original_command: str | None = None,
        replacement_command: str | None = None, reason: str = "", coverage: str = "", *,
        original_verification_ref: str | None = None,
        failed_tool_call_id: str | None = None, passed_tool_call_id: str | None = None,
    ) -> ToolResult:
        try:
            return self._revise(
                context, original_command, replacement_command, reason, coverage,
                original_verification_ref=original_verification_ref,
                failed_tool_call_id=failed_tool_call_id, passed_tool_call_id=passed_tool_call_id,
            )
        except VerificationEvidenceError as exc:
            return ToolResult(
                ok=False, status="denied", summary="revise_verification denied by policy",
                error=str(exc), data={"verification_rejection": exc.evidence},
            )

    def _revise(
        self, context: RuntimeContext, original_command: str | None = None,
        replacement_command: str | None = None, reason: str = "", coverage: str = "", *,
        original_verification_ref: str | None = None,
        failed_tool_call_id: str | None = None, passed_tool_call_id: str | None = None,
    ) -> ToolResult:
        if context.run_dir is None or not context.task_id:
            raise PermissionError("A method revision requires a runtime-bound current task")
        store = JsonStore(context.validator)
        path = context.run_dir / "task_plan.json"
        board = store.read(path, "task_board")
        matches = [t for t in board["tasks"] if t["task_id"] == context.task_id]
        if len(matches) != 1:
            raise PermissionError("Method revision requires one unambiguous current task")
        task = matches[0]
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
        reference_mode = any(value is not None for value in (
            original_verification_ref, failed_tool_call_id, passed_tool_call_id,
        ))
        selected_failure = selected_pass = None
        if reference_mode:
            if self.name not in task.get("allowed_tools", []):
                raise PermissionError("The current task does not allow method revision")
            if current_reference_task(context) != task:
                raise PermissionError("The method reference task changed during resolution")
            if (original_command is not None or replacement_command is not None
                    or not all(isinstance(value, str) and value for value in (
                        original_verification_ref, failed_tool_call_id, passed_tool_call_id))):
                raise PermissionError("Use complete execution references or exact commands, never mix them")
            assert isinstance(original_verification_ref, str)
            assert isinstance(failed_tool_call_id, str) and isinstance(passed_tool_call_id, str)
            original_command = referenced_command(task, context, original_verification_ref)
            selected_failure = referenced_observation(records, failed_tool_call_id, context, task)
            selected_pass = referenced_observation(records, passed_tool_call_id, context, task)
            if observation_command(ToolObservation(**selected_failure["observation"])) != original_command:
                raise PermissionError("The failed execution does not reference the registered original method")
            replacement_command = observation_command(ToolObservation(**selected_pass["observation"]))
        if not isinstance(original_command, str) or not isinstance(replacement_command, str):
            raise ValueError("Provide both exact commands or complete method/execution references")
        records = [r for r in records if r.get("run_id") == context.run_id]
        revised = revise_method(
            task, goal, guidance, project["commands"], records, original_command=original_command,
            replacement_command=replacement_command, reason=reason, coverage=coverage,
        )
        revision = revised["verification_policy"]["method_revisions"][-1]
        if selected_failure is not None and selected_pass is not None:
            if (revision["failed_observation_id"] != selected_failure["observation_id"]
                    or revision["passed_observation_id"] != selected_pass["observation_id"]):
                raise PermissionError("Execution references are stale; use the latest method outcomes")
            revision["reference_binding"] = {"original_verification_ref": original_verification_ref,
                                             "failed_tool_call_id": failed_tool_call_id,
                                             "passed_tool_call_id": passed_tool_call_id}
        context.validator.validate("task", revised)
        board["tasks"] = [revised if t["task_id"] == context.task_id else t for t in board["tasks"]]
        store.write(path, board, "task_board")
        return ToolResult(
            ok=True, summary="Revised planner method; original failure retained; coverage unverified",
            data={"task_id": context.task_id,
                  "verification_methods": verification_methods(revised, context), "revision": revision},
        )
