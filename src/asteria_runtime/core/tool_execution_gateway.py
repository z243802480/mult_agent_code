from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_hooks import RuntimeHookManager
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.task_contract import allows_expected_failure


@dataclass(frozen=True)
class ToolExecutionGateway:
    registry: Any
    permission_policy: ToolPermissionPolicy
    hook_manager: RuntimeHookManager | None = None
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
            try:
                if tool_name not in allowed:
                    raise PermissionError(f"Tool is not allowed for {task['task_id']}: {tool_name}")
                self.permission_policy.enforce_tool_permission_profile(
                    task,
                    tool_name,
                    call.get("args", {}),
                )
                self._emit(
                    context,
                    "before_tool_call",
                    "tool",
                    f"Starting tool {tool_name}",
                    task=task,
                    tool_name=tool_name,
                    data={"arg_keys": sorted(list((call.get("args") or {}).keys()))},
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
                self._emit(
                    context,
                    "after_tool_call",
                    "tool",
                    f"Finished tool {tool_name}",
                    task=task,
                    tool_name=tool_name,
                    data={
                        "ok": bool(getattr(result, "ok", False)),
                        "summary": str(getattr(result, "summary", "")),
                        "error": getattr(result, "error", None),
                    },
                )
                if stop_on_failure and not result.ok:
                    raise RuntimeError(f"Tool failed: {tool_name}: {result.summary}")
                if stop_verification_on_fatal and self._fatal_verification_failure(result):
                    break
            except Exception as exc:
                self._emit(
                    context,
                    "tool_call_error",
                    "tool",
                    f"Tool {tool_name} failed: {exc}",
                    task=task,
                    tool_name=tool_name,
                    data={"error": str(exc), "error_type": exc.__class__.__name__},
                )
                raise
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

    def _emit(
        self,
        context: RuntimeContext,
        hook_name: str,
        phase: str,
        summary: str,
        *,
        task: dict,
        tool_name: str,
        data: dict,
    ) -> None:
        if self.hook_manager is None:
            return
        self.hook_manager.emit(
            context,
            hook_name,
            phase,
            self.actor,
            summary,
            task=task,
            tool_name=tool_name,
            data=data,
        )
