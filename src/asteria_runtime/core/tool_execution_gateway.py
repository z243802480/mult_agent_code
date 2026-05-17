from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.task_contract import allows_expected_failure


@dataclass(frozen=True)
class ToolExecutionGateway:
    registry: Any
    permission_policy: ToolPermissionPolicy
    actor: str = "ToolExecutionGateway"

    def run_tool_calls(
        self,
        calls: list[dict],
        task: dict,
        context: RuntimeContext,
        stop_on_failure: bool = True,
        stop_verification_on_fatal: bool = False,
    ) -> list[Any]:
        results = []
        allowed = set(task["allowed_tools"])
        for call in calls:
            tool_name = call["tool_name"]
            if tool_name not in allowed:
                raise PermissionError(f"Tool is not allowed for {task['task_id']}: {tool_name}")
            self.permission_policy.enforce_tool_permission_profile(
                task,
                tool_name,
                call.get("args", {}),
            )
            result = self.registry.call(
                tool_name,
                self.permission_policy.context_with_approval(
                    context,
                    task,
                    tool_name,
                    call["args"],
                ),
                task_id=task["task_id"],
                agent_id="CoderAgent",
                **self._tool_args(call["args"]),
            )
            if self._accepts_diagnostic_failure(task, tool_name, result):
                result.ok = True
                result.error = None
                result.summary = f"Diagnostic failure accepted: {result.summary}"
            results.append(result)
            if stop_on_failure and not result.ok:
                raise RuntimeError(f"Tool failed: {tool_name}: {result.summary}")
            if stop_verification_on_fatal and self._fatal_verification_failure(result):
                break
        return results

    def _accepts_diagnostic_failure(self, task: dict, tool_name: str, result: object) -> bool:
        if tool_name not in {"run_command", "run_tests"}:
            return False
        if getattr(result, "ok", False) or getattr(result, "error", None) != "nonzero_exit":
            return False
        return allows_expected_failure(task)

    def _fatal_verification_failure(self, result: object) -> bool:
        if getattr(result, "ok", False):
            return False
        data = getattr(result, "data", None)
        stderr = str(data.get("stderr", "")) if isinstance(data, dict) else ""
        summary = str(getattr(result, "summary", ""))
        text = f"{summary}\n{stderr}"
        return any(signal in text for signal in ["SyntaxError", "IndentationError"])

    def _tool_args(self, args: dict) -> dict:
        reserved = {"context", "task_id", "agent_id"}
        return {key: value for key, value in args.items() if key not in reserved}
