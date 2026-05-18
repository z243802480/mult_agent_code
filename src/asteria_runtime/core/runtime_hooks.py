from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


RuntimeHookHandler = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class RuntimeHookPolicy:
    enabled: bool = True
    plugins_enabled: bool = False
    allowed_hook_names: frozenset[str] = frozenset(
        {
            "before_worker",
            "after_worker",
            "worker_error",
            "before_tool_call",
            "after_tool_call",
            "tool_call_error",
        }
    )
    redacted_data_keys: frozenset[str] = frozenset(
        {
            "secret",
            "token",
            "api_key",
            "apikey",
            "authorization",
            "password",
            "credential",
            "raw_context",
        }
    )
    handler_timeout_ms: int = 1000

    @classmethod
    def from_config(cls, policy: dict[str, Any]) -> RuntimeHookPolicy:
        raw_hooks = policy.get("hooks")
        hooks: dict[str, Any] = raw_hooks if isinstance(raw_hooks, dict) else {}
        default = cls()
        return cls(
            enabled=bool(hooks.get("enabled", True)),
            plugins_enabled=bool(hooks.get("plugins_enabled", False)),
            allowed_hook_names=frozenset(
                hooks.get("allowed_hook_names") or default.allowed_hook_names
            ),
            redacted_data_keys=frozenset(
                hooks.get("redacted_data_keys") or default.redacted_data_keys
            ),
            handler_timeout_ms=int(hooks.get("handler_timeout_ms") or default.handler_timeout_ms),
        )


@dataclass(frozen=True)
class RuntimeHookEvent:
    run_id: str | None
    hook_name: str
    phase: str
    actor: str
    summary: str
    task_id: str | None = None
    worker_invocation_id: str | None = None
    tool_name: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_record(self, hook_event_id: str) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "hook_event_id": hook_event_id,
            "run_id": self.run_id,
            "hook_name": self.hook_name,
            "phase": self.phase,
            "actor": self.actor,
            "task_id": self.task_id,
            "worker_invocation_id": self.worker_invocation_id,
            "tool_name": self.tool_name,
            "summary": self.summary,
            "data": self.data,
            "created_at": now_iso(),
        }


class RuntimeHookManager:
    """Durable lifecycle hook bus for runtime internals and future plugins.

    Hooks are observational by default: handler failures are recorded as events, but
    they do not fail the run. Policy enforcement remains in the existing runtime
    policy and gateway layers.
    """

    def __init__(
        self,
        validator: SchemaValidator,
        handlers: list[RuntimeHookHandler] | None = None,
        policy: RuntimeHookPolicy | None = None,
    ) -> None:
        self.validator = validator
        self.store = JsonlStore(validator)
        self.handlers = handlers or []
        self.policy = policy or RuntimeHookPolicy()
        self._lock = RLock()

    def configure(self, policy: dict[str, Any] | RuntimeHookPolicy) -> None:
        self.policy = (
            policy if isinstance(policy, RuntimeHookPolicy) else RuntimeHookPolicy.from_config(policy)
        )

    def emit(
        self,
        context: RuntimeContext,
        hook_name: str,
        phase: str,
        actor: str,
        summary: str,
        *,
        task: dict[str, Any] | None = None,
        worker_invocation_id: str | None = None,
        tool_name: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.policy.enabled:
            return None
        if hook_name not in self.policy.allowed_hook_names:
            self._record_event(
                context,
                "runtime_hook_blocked",
                f"Runtime hook blocked by policy: {hook_name}",
                {"hook_name": hook_name, "phase": phase, "actor": actor},
            )
            return None
        run_dir = context.run_dir
        if run_dir is None:
            return None
        hook_path = run_dir / "runtime_hooks.jsonl"
        with self._lock:
            hook_event_id = f"hook-{self._existing_count(hook_path) + 1:04d}"
            record = RuntimeHookEvent(
                run_id=context.run_id,
                hook_name=hook_name,
                phase=phase,
                actor=actor,
                task_id=self._task_id(task),
                worker_invocation_id=worker_invocation_id,
                tool_name=tool_name,
                summary=summary,
                data=self._redact_data(data or {}),
            ).to_record(hook_event_id)
            self.store.append(hook_path, record, "runtime_hook_event")
        self._record_event(context, "runtime_hook_emitted", summary, record)
        self._dispatch_handlers(context, record)
        return record

    def _dispatch_handlers(self, context: RuntimeContext, record: dict[str, Any]) -> None:
        for handler in self.handlers:
            try:
                handler(record)
            except Exception as exc:  # noqa: BLE001 - hook extensions must not break runs
                self._record_event(
                    context,
                    "runtime_hook_handler_failed",
                    f"Runtime hook handler failed for {record['hook_name']}: {exc}",
                    {
                        "hook_event_id": record["hook_event_id"],
                        "hook_name": record["hook_name"],
                        "handler": getattr(handler, "__name__", handler.__class__.__name__),
                        "error": str(exc),
                    },
                )

    def _record_event(
        self,
        context: RuntimeContext,
        event_type: str,
        summary: str,
        data: dict[str, Any],
    ) -> None:
        if context.event_logger is None:
            return
        context.event_logger.record(
            context.run_id,
            event_type,
            "RuntimeHookManager",
            summary,
            data,
        )

    def _existing_count(self, path: Path) -> int:
        return len(JsonlStore().read_all(path))

    def _task_id(self, task: dict[str, Any] | None) -> str | None:
        if not task:
            return None
        value = task.get("task_id")
        return str(value) if value is not None else None

    def _redact_data(self, data: Any) -> Any:
        if isinstance(data, dict):
            redacted = {}
            for key, value in data.items():
                if str(key).lower() in self.policy.redacted_data_keys:
                    redacted[key] = "<redacted>"
                else:
                    redacted[key] = self._redact_data(value)
            return redacted
        if isinstance(data, list):
            return [self._redact_data(item) for item in data]
        return data
