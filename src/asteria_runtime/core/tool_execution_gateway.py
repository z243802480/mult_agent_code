from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from asteria_runtime.core.agent_harness import (
    HarnessTurnEvent,
    ToolObservation,
    observation_from_exception,
    observation_from_tool_result,
)
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_hooks import RuntimeHookManager
from asteria_runtime.core.runtime_policy import ToolPermissionPolicy
from asteria_runtime.core.task_contract import allows_expected_failure
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


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
            args = call.get("args", {}) or {}
            tool_call_id = self._next_tool_call_id(context)
            started = perf_counter()
            start_event: dict[str, Any] | None = None
            model_telemetry = self._last_model_telemetry(context)
            turn_start_event = self._record_harness_turn(
                context,
                task,
                tool_call_id,
                event_type="turn_start",
                status="running",
                title="Agent 回合",
                summary=f"Agent is preparing to use {tool_name}.",
                execution_step="turn_start",
                telemetry=model_telemetry or None,
                data={
                    "turn_event": HarnessTurnEvent(
                        turn_id=tool_call_id,
                        run_id=context.run_id,
                        task_id=str(task.get("task_id", "")),
                        event_type="turn_start",
                        summary=f"Agent is preparing to use {tool_name}.",
                    ).to_dict(),
                    "tool_name": tool_name,
                    "arg_keys": sorted(list(args.keys())),
                    "model_telemetry": model_telemetry,
                },
            )
            pre_file_changes = self._planned_file_changes(tool_name, args, context)
            try:
                if tool_name not in allowed:
                    raise PermissionError(f"Tool is not allowed for {task['task_id']}: {tool_name}")
                self.permission_policy.enforce_tool_permission_profile(
                    task,
                    tool_name,
                    args,
                )
                start_event = self._record_tool_progress(
                    context,
                    task,
                    tool_name,
                    tool_call_id,
                    event_type="tool_call",
                    status="running",
                    title=f"Running {tool_name}",
                    summary=self._tool_start_summary(tool_name, args),
                    command=self._command_args(tool_name, args),
                    file_changes=pre_file_changes,
                    data={"arg_keys": sorted(list(args.keys()))},
                )
                self._emit(
                    context,
                    "before_tool_call",
                    "tool",
                    f"Starting tool {tool_name}",
                    task=task,
                    tool_name=tool_name,
                    data={"arg_keys": sorted(list(args.keys()))},
                )
                result = self.registry.call(
                    tool_name,
                    self.permission_policy.context_with_approval(
                        context,
                        task,
                        tool_name,
                        args,
                    ),
                    task_id=task["task_id"],
                    agent_id="CoderAgent",
                    **self._tool_args(args),
                )
                if self._accepts_diagnostic_failure(task, tool_name, result):
                    result.ok = True
                    result.error = None
                    result.summary = f"Diagnostic failure accepted: {result.summary}"
                results.append(result)
                duration_ms = int((perf_counter() - started) * 1000)
                file_changes = self._result_file_changes(tool_name, result, pre_file_changes)
                observation = observation_from_tool_result(
                    tool_name=tool_name,
                    result=result,
                    telemetry={"duration_ms": duration_ms},
                    file_changes=file_changes,
                )
                setattr(result, "harness_observation", observation)
                self._record_tool_progress(
                    context,
                    task,
                    tool_name,
                    tool_call_id,
                    event_type="tool_output",
                    status="completed" if bool(getattr(result, "ok", False)) else "failed",
                    title=f"Finished {tool_name}",
                    summary=str(getattr(result, "summary", "")),
                    parent_event_id=start_event.get("event_id") if start_event else None,
                    command=self._command_args(tool_name, args),
                    telemetry={"duration_ms": duration_ms},
                    data=self._tool_result_data(result),
                )
                self._record_harness_observation(
                    context,
                    task,
                    tool_call_id,
                    observation,
                    parent_event_id=start_event.get("event_id") if start_event else None,
                )
                self._record_file_progress(
                    context,
                    task,
                    tool_name,
                    tool_call_id,
                    result,
                    pre_file_changes,
                    parent_event_id=start_event.get("event_id") if start_event else None,
                )
                observation_event = self._record_harness_turn(
                    context,
                    task,
                    tool_call_id,
                    event_type="turn_end",
                    status="completed" if observation.ok else "failed",
                    title="Agent 回合完成",
                    summary=f"Agent observed {tool_name} and can decide the next step.",
                    parent_event_id=turn_start_event.get("event_id") if turn_start_event else None,
                    artifact_refs=observation.artifact_refs,
                    file_changes=observation.file_changes,
                    telemetry=observation.telemetry,
                    execution_step="turn_end",
                    data={
                        "turn_event": HarnessTurnEvent(
                            turn_id=tool_call_id,
                            run_id=context.run_id,
                            task_id=str(task.get("task_id", "")),
                            event_type="turn_end",
                            summary=f"Agent observed {tool_name} and can decide the next step.",
                            observation=observation,
                        ).to_dict(),
                        "observation": observation.to_dict(),
                    },
                )
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
                duration_ms = int((perf_counter() - started) * 1000)
                observation = observation_from_exception(
                    tool_name=tool_name,
                    exc=exc,
                    telemetry={"duration_ms": duration_ms},
                    file_changes=pre_file_changes,
                )
                self._record_tool_progress(
                    context,
                    task,
                    tool_name,
                    tool_call_id,
                    event_type="error",
                    status="failed",
                    title=f"{tool_name} failed",
                    summary=str(exc),
                    parent_event_id=start_event.get("event_id") if start_event else None,
                    command=self._command_args(tool_name, args),
                    telemetry={"duration_ms": duration_ms},
                    file_changes=pre_file_changes,
                    data={"error": str(exc), "error_type": exc.__class__.__name__},
                )
                observation_event = self._record_harness_turn(
                    context,
                    task,
                    tool_call_id,
                    event_type="tool_observation",
                    status="failed",
                    title="工具观察",
                    summary=observation.model_summary(),
                    artifact_refs=observation.artifact_refs,
                    file_changes=observation.file_changes,
                    telemetry=observation.telemetry,
                    data={
                        "turn_event": HarnessTurnEvent(
                            turn_id=tool_call_id,
                            run_id=context.run_id,
                            task_id=str(task.get("task_id", "")),
                            event_type="tool_observation",
                            summary=observation.model_summary(),
                            observation=observation,
                        ).to_dict(),
                        "observation": observation.to_dict(),
                    },
                    parent_event_id=start_event.get("event_id") if start_event else None,
                )
                self._record_raw_observation(
                    context,
                    task,
                    tool_call_id,
                    observation,
                    user_progress_event_id=(
                        str(observation_event.get("event_id"))
                        if observation_event and observation_event.get("event_id")
                        else None
                    ),
                )
                self._record_harness_turn(
                    context,
                    task,
                    tool_call_id,
                    event_type="turn_end",
                    status="failed",
                    title="Agent 回合失败",
                    summary=f"Agent received a failure observation from {tool_name}.",
                    parent_event_id=turn_start_event.get("event_id") if turn_start_event else None,
                    telemetry={"duration_ms": duration_ms},
                    artifact_refs=observation.artifact_refs,
                    file_changes=observation.file_changes,
                    execution_step="turn_end",
                    data={
                        "turn_event": HarnessTurnEvent(
                            turn_id=tool_call_id,
                            run_id=context.run_id,
                            task_id=str(task.get("task_id", "")),
                            event_type="turn_end",
                            summary=f"Agent received a failure observation from {tool_name}.",
                            observation=observation,
                        ).to_dict(),
                        "observation": observation.to_dict(),
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    },
                )
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

    def _progress_logger(self, context: RuntimeContext) -> UserProgressLogger | None:
        if context.run_dir is None:
            return None
        return UserProgressLogger(context.run_dir / "user_progress.jsonl", context.validator)

    def _record_tool_progress(
        self,
        context: RuntimeContext,
        task: dict,
        tool_name: str,
        tool_call_id: str,
        *,
        event_type: str,
        status: str,
        title: str,
        summary: str,
        parent_event_id: str | None = None,
        command: list[str] | None = None,
        telemetry: dict[str, Any] | None = None,
        file_changes: list[dict[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        logger = self._progress_logger(context)
        if logger is None:
            return None
        return logger.record(
            run_id=context.run_id,
            channel="tool",
            event_type=event_type,
            phase="execute",
            status=status,
            title=title,
            summary=summary,
            display_level="inspector",
            parent_event_id=parent_event_id,
            tool_call_id=tool_call_id,
            command=command,
            telemetry=telemetry,
            call_chain=[self.actor, tool_name],
            execution_chain=[str(task.get("task_id", "")), tool_name],
            file_changes=file_changes,
            data=data,
        )

    def _record_harness_observation(
        self,
        context: RuntimeContext,
        task: dict,
        tool_call_id: str,
        observation: ToolObservation,
        *,
        parent_event_id: str | None,
    ) -> None:
        turn = HarnessTurnEvent(
            turn_id=tool_call_id,
            run_id=context.run_id,
            task_id=str(task.get("task_id", "")),
            event_type="tool_observation",
            summary=observation.model_summary(),
            observation=observation,
        )
        observation_event = self._record_harness_turn(
            context,
            task,
            tool_call_id,
            event_type="tool_observation",
            status="completed" if observation.ok else "failed",
            title="工具观察",
            summary=observation.model_summary(),
            parent_event_id=parent_event_id,
            artifact_refs=observation.artifact_refs,
            file_changes=observation.file_changes,
            telemetry=observation.telemetry,
            data={"turn_event": turn.to_dict(), "observation": observation.to_dict()},
        )
        self._record_raw_observation(
            context,
            task,
            tool_call_id,
            observation,
            user_progress_event_id=(
                str(observation_event.get("event_id"))
                if observation_event and observation_event.get("event_id")
                else None
            ),
        )

    def _record_raw_observation(
        self,
        context: RuntimeContext,
        task: dict,
        tool_call_id: str,
        observation: ToolObservation,
        *,
        user_progress_event_id: str | None,
    ) -> None:
        if context.run_dir is None:
            return
        JsonlStore(context.validator).append(
            context.run_dir / "tool_observations.jsonl",
            {
                "schema_version": "0.1.0",
                "observation_id": f"tool-observation-{tool_call_id}",
                "run_id": context.run_id,
                "task_id": str(task.get("task_id", "")),
                "tool_call_id": tool_call_id,
                "tool_name": observation.tool_name,
                "ok": observation.ok,
                "status": observation.status,
                "summary": observation.summary,
                "error_class": observation.data.get("error_type") if observation.data else None,
                "artifact_refs": observation.artifact_refs,
                "evidence_refs": [str(context.run_dir / "tool_calls.jsonl")],
                "user_progress_event_id": user_progress_event_id,
                "next_hint": (
                    "continue" if observation.ok else "diagnose_then_repair_replan_ask_or_stop"
                ),
                "observation": observation.to_dict(),
                "created_at": now_iso(),
            },
            "tool_observation",
        )

    def _record_harness_turn(
        self,
        context: RuntimeContext,
        task: dict,
        tool_call_id: str,
        *,
        event_type: str,
        status: str,
        title: str,
        summary: str,
        parent_event_id: str | None = None,
        artifact_refs: list[str] | None = None,
        file_changes: list[dict[str, Any]] | None = None,
        telemetry: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        execution_step: str | None = None,
    ) -> dict[str, Any] | None:
        logger = self._progress_logger(context)
        if logger is None:
            return None
        return logger.record(
            run_id=context.run_id,
            channel="execution_chain",
            event_type=event_type,
            phase="execute",
            status=status,
            title=title,
            summary=summary,
            display_level="main",
            parent_event_id=parent_event_id,
            tool_call_id=tool_call_id,
            artifact_refs=artifact_refs,
            telemetry=telemetry,
            call_chain=[self.actor, "AgentHarness"],
            execution_chain=[str(task.get("task_id", "")), execution_step or event_type],
            file_changes=file_changes,
            data=data,
        )

    def _record_file_progress(
        self,
        context: RuntimeContext,
        task: dict,
        tool_name: str,
        tool_call_id: str,
        result: object,
        pre_file_changes: list[dict[str, Any]],
        *,
        parent_event_id: str | None,
    ) -> None:
        changes = self._result_file_changes(tool_name, result, pre_file_changes)
        if not changes or not bool(getattr(result, "ok", False)):
            return
        logger = self._progress_logger(context)
        if logger is None:
            return
        event_type = changes[0].get("event_type", "file_modified")
        logger.record(
            run_id=context.run_id,
            channel="file",
            event_type=str(event_type),
            phase="execute",
            status="completed",
            title="File changes recorded",
            summary=self._file_change_summary(changes),
            display_level="main",
            parent_event_id=parent_event_id,
            tool_call_id=tool_call_id,
            call_chain=[self.actor, tool_name],
            execution_chain=[str(task.get("task_id", "")), tool_name],
            file_changes=changes,
        )

    def _last_model_telemetry(self, context: RuntimeContext) -> dict[str, Any] | None:
        if context.run_dir is None:
            return None
        path = context.run_dir / "model_calls.jsonl"
        if not path.exists():
            return None
        last: dict[str, Any] | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                import json
                last = json.loads(line)
            except Exception:  # noqa: BLE001
                pass
        if last is None:
            return None
        return {
            "chunk_count": last.get("chunk_count"),
            "first_chunk_ms": last.get("first_chunk_ms"),
            "duration_ms": last.get("duration_ms"),
            "model_provider": last.get("model_provider"),
            "model_name": last.get("model_name"),
        }

    def _next_tool_call_id(self, context: RuntimeContext) -> str:
        if context.run_dir is None:
            return "toolcall-0000"
        existing = JsonlStore(context.validator).read_all(context.run_dir / "tool_calls.jsonl")
        return f"toolcall-{len(existing) + 1:04d}"

    def _tool_start_summary(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name in {"run_command", "run_tests"} and args.get("command"):
            return f"Running command: {args['command']}"
        if tool_name in {"write_file", "read_file", "diff_workspace"} and args.get("path"):
            return f"{tool_name}: {args['path']}"
        if tool_name == "apply_patch":
            return "Applying patch"
        return f"Running tool: {tool_name}"

    def _command_args(self, tool_name: str, args: dict[str, Any]) -> list[str]:
        if tool_name not in {"run_command", "run_tests"}:
            return []
        command = args.get("command")
        return [str(command)] if command else []

    def _tool_result_data(self, result: object) -> dict[str, Any]:
        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            return {"ok": bool(getattr(result, "ok", False)), "error": getattr(result, "error", None)}
        redacted = {
            key: value
            for key, value in data.items()
            if key not in {"content", "diff"}
        }
        redacted["ok"] = bool(getattr(result, "ok", False))
        redacted["error"] = getattr(result, "error", None)
        return redacted

    def _planned_file_changes(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: RuntimeContext,
    ) -> list[dict[str, Any]]:
        if tool_name != "write_file" or not args.get("path"):
            return []
        path = str(args["path"])
        existed = (context.root / path).exists()
        return [
            {
                "path": path,
                "operation": "modified" if existed else "created",
                "event_type": "file_modified" if existed else "file_created",
            }
        ]

    def _result_file_changes(
        self,
        tool_name: str,
        result: object,
        pre_file_changes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            return pre_file_changes
        if tool_name == "write_file" and data.get("path"):
            path = str(data["path"])
            planned = pre_file_changes[0] if pre_file_changes else {}
            return [
                {
                    "path": path,
                    "operation": planned.get("operation", "modified"),
                    "event_type": planned.get("event_type", "file_modified"),
                    "bytes": data.get("bytes"),
                    "backup_id": data.get("backup_id"),
                }
            ]
        if tool_name == "apply_patch":
            changed = data.get("changed_files")
            if isinstance(changed, list):
                return [
                    {
                        "path": str(path),
                        "operation": "modified",
                        "event_type": "file_modified",
                        "backup_id": data.get("backup_id"),
                    }
                    for path in changed
                ]
        if tool_name == "restore_backup":
            restored = data.get("restored_files")
            if isinstance(restored, list):
                return [
                    {"path": str(path), "operation": "modified", "event_type": "file_modified"}
                    for path in restored
                ]
        return pre_file_changes

    def _file_change_summary(self, changes: list[dict[str, Any]]) -> str:
        paths = [str(change.get("path", "")) for change in changes if change.get("path")]
        if not paths:
            return "Recorded file changes"
        if len(paths) == 1:
            return f"Updated {paths[0]}"
        return f"Updated {len(paths)} files: {', '.join(paths[:3])}"

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
