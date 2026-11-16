from asteria_runtime.core.execution_permission_request import requested_execution
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.tools.base import ToolResult


class RequestExecutionPermissionTool:
    name = "request_execution_permission"

    def run(self, context: RuntimeContext, tool_name: str, args: dict, reason: str) -> ToolResult:
        target, arguments, _ = requested_execution({"tool_name": tool_name, "args": args, "reason": reason})
        if context.run_dir is None or context.task_id is None:
            raise PermissionError("An execution request requires a current runtime task")
        board = JsonStore(context.validator).read(context.run_dir / "task_plan.json", "task_board")
        task = next(t for t in board["tasks"] if t["task_id"] == context.task_id)
        if target not in task["allowed_tools"]:
            raise PermissionError("Requesting consent does not add a task capability")
        policy = ToolPermissionPolicy(context.root, context.validator)
        decision = policy.execution_decision(context, task, target, arguments)
        if decision is None or decision["status"] == "pending":
            raise PermissionError("Execution consent must be handled by the runtime approval boundary")
        approved = decision.get("selected_option_id") == "approve_once"
        return ToolResult(ok=approved, summary="Execution consent approved; command was not run" if approved
                          else "Execution consent declined; command was not run",
                          error=None if approved else "execution_request_declined",
                          data={"decision_id": decision["decision_id"], "approved": approved,
                                "executed": False, "tool_name": target, "args": arguments})
