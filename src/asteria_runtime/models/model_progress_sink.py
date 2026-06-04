from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import time
from typing import Any, Iterator

from asteria_runtime.models.base import ChatRequest
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger


_ACTIVE_MODEL_PROGRESS_SINK: ContextVar["ModelProgressSink | None"] = ContextVar(
    "asteria_model_progress_sink",
    default=None,
)


class ModelProgressSink:
    def __init__(
        self,
        run_dir: Path | None,
        validator: SchemaValidator | None,
        request: ChatRequest,
    ) -> None:
        self.run_dir = run_dir
        self.request = request
        self.logger = (
            UserProgressLogger(run_dir / "user_progress.jsonl", validator)
            if run_dir is not None
            else None
        )
        self._start_event_id: str | None = None
        self._started_at_monotonic: float | None = None

    def model_start(self, *, provider: str, model: str | None, mode: str) -> None:
        self._started_at_monotonic = time.monotonic()
        if self.logger is None:
            return
        context = self._progress_context({"mode": mode})
        event = self.logger.record(
            run_id=self._run_id(),
            channel="model",
            event_type="start",
            phase=self._phase(),
            status="running",
            title="Thinking",
            summary="Asteria is preparing the next step.",
            display_level="main",
            model_provider=provider,
            model_name=model,
            telemetry=context["telemetry"],
            call_chain=[str(self.request.metadata.get("agent_id") or "ModelClient"), provider],
            execution_chain=[self.request.purpose, self.request.model_tier],
            data=context["data"],
            transcript_kind="progress",
            ui_intent="work_progress",
        )
        self._start_event_id = str(event["event_id"])

    def model_delta(self, content: str, *, provider: str, model: str | None) -> None:
        if self.logger is None:
            return
        context = self._progress_context()
        self.logger.record(
            run_id=self._run_id(),
            channel="model",
            event_type="delta",
            phase=self._phase(),
            status="running",
            title="Drafting",
            summary="Asteria is drafting a response.",
            content_delta=content,
            display_level="inspector",
            parent_event_id=self._start_event_id,
            model_provider=provider,
            model_name=model,
            telemetry=context["telemetry"],
            call_chain=[str(self.request.metadata.get("agent_id") or "ModelClient"), provider],
            execution_chain=[self.request.purpose, self.request.model_tier],
            data=context["data"],
            transcript_kind="assistant_message",
            ui_intent="inform",
        )

    def model_end(
        self,
        *,
        provider: str,
        model: str | None,
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        if self.logger is None:
            return
        context = self._progress_context(telemetry or {})
        self.logger.record(
            run_id=self._run_id(),
            channel="model",
            event_type="end",
            phase=self._phase(),
            status="completed",
            title="Draft complete",
            summary="Asteria finished drafting this step.",
            display_level="main",
            parent_event_id=self._start_event_id,
            model_provider=provider,
            model_name=model,
            telemetry=context["telemetry"],
            call_chain=[str(self.request.metadata.get("agent_id") or "ModelClient"), provider],
            execution_chain=[self.request.purpose, self.request.model_tier],
            data=context["data"],
            transcript_kind="progress",
            ui_intent="work_progress",
        )

    def model_error(self, *, provider: str, model: str | None, error: str) -> None:
        if self.logger is None:
            return
        context = self._progress_context()
        self.logger.record(
            run_id=self._run_id(),
            channel="model",
            event_type="error",
            phase=self._phase(),
            status="failed",
            title="Model connection interrupted",
            summary="The model response failed before Asteria received a usable step.",
            display_level="main",
            parent_event_id=self._start_event_id,
            model_provider=provider,
            model_name=model,
            telemetry=context["telemetry"],
            call_chain=[str(self.request.metadata.get("agent_id") or "ModelClient"), provider],
            execution_chain=[self.request.purpose, self.request.model_tier],
            data={**context["data"], "error": error},
            transcript_kind="diagnostic",
        )

    def _run_id(self) -> str | None:
        run_id = self.request.metadata.get("run_id")
        return str(run_id) if run_id else None

    def _phase(self) -> str:
        purpose = self.request.purpose
        if purpose in {"task_execution", "task_repair"}:
            return "execute"
        if purpose in {"run_review", "model_check"}:
            return "review"
        return "plan"

    def _summary(self, verb: str, provider: str, model: str | None, mode: str) -> str:
        model_part = f"/{model}" if model else ""
        mode_part = f" ({mode})" if mode else ""
        return f"{provider}{model_part} {verb}{mode_part} for {self.request.purpose}."

    def _progress_context(self, telemetry: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
        contract = self._role_contract()
        context_telemetry: dict[str, Any] = {
            "purpose": self.request.purpose,
            "model_tier": self.request.model_tier,
        }
        for key in [
            "runtime_profile_id",
            "model_profile_id",
            "task_id",
            "attempt",
            "model_route",
        ]:
            value = self.request.metadata.get(key)
            if value is not None:
                context_telemetry[key] = value
        if contract:
            for source_key, target_key in [
                ("role", "role"),
                ("purpose", "role_purpose"),
                ("deadline_profile", "deadline_profile"),
                ("provider_call_seconds", "provider_call_seconds"),
                ("stream_idle_timeout_seconds", "stream_idle_timeout_seconds"),
                ("max_model_calls", "max_model_calls"),
            ]:
                value = contract.get(source_key)
                if value is not None:
                    context_telemetry[target_key] = value
        deadline_ms = self._deadline_ms(contract)
        if deadline_ms is not None:
            context_telemetry["deadline_ms"] = deadline_ms
        remaining_ms = self._deadline_remaining_ms(deadline_ms)
        if remaining_ms is not None:
            context_telemetry["deadline_remaining_ms"] = remaining_ms
        context_telemetry.update(telemetry or {})
        data: dict[str, Any] = {}
        if contract:
            data["agent_role_contract"] = contract
        return {"telemetry": context_telemetry, "data": data}

    def _role_contract(self) -> dict[str, Any]:
        contract = self.request.metadata.get("agent_role_contract")
        return contract if isinstance(contract, dict) else {}

    def _deadline_ms(self, contract: dict[str, Any]) -> int | None:
        metadata_deadline = self.request.metadata.get("deadline_ms")
        if isinstance(metadata_deadline, int):
            return metadata_deadline
        if isinstance(metadata_deadline, float):
            return int(metadata_deadline)
        provider_call_seconds = contract.get("provider_call_seconds")
        if isinstance(provider_call_seconds, (int, float)):
            return int(provider_call_seconds * 1000)
        if self.request.timeout_seconds is not None:
            return int(self.request.timeout_seconds * 1000)
        return None

    def _deadline_remaining_ms(self, deadline_ms: int | None) -> int | None:
        if deadline_ms is None or self._started_at_monotonic is None:
            return None
        elapsed_ms = int((time.monotonic() - self._started_at_monotonic) * 1000)
        return max(0, deadline_ms - elapsed_ms)


class NoopModelProgressSink:
    def model_start(self, *, provider: str, model: str | None, mode: str) -> None:
        return

    def model_delta(self, content: str, *, provider: str, model: str | None) -> None:
        return

    def model_end(
        self,
        *,
        provider: str,
        model: str | None,
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        return

    def model_error(self, *, provider: str, model: str | None, error: str) -> None:
        return


@contextmanager
def use_model_progress_sink(sink: ModelProgressSink) -> Iterator[None]:
    token = _ACTIVE_MODEL_PROGRESS_SINK.set(sink)
    try:
        yield
    finally:
        _ACTIVE_MODEL_PROGRESS_SINK.reset(token)


def model_progress_sink() -> ModelProgressSink | NoopModelProgressSink:
    return _ACTIVE_MODEL_PROGRESS_SINK.get() or NoopModelProgressSink()
