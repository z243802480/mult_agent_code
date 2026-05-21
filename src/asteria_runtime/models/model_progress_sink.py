from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
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

    def model_start(self, *, provider: str, model: str | None, mode: str) -> None:
        if self.logger is None:
            return
        event = self.logger.record(
            run_id=self._run_id(),
            channel="model",
            event_type="start",
            phase=self._phase(),
            status="running",
            title="Model response started",
            summary=self._summary("started", provider, model, mode),
            display_level="main",
            model_provider=provider,
            model_name=model,
            telemetry={"mode": mode, "purpose": self.request.purpose},
            call_chain=[str(self.request.metadata.get("agent_id") or "ModelClient"), provider],
            execution_chain=[self.request.purpose, self.request.model_tier],
        )
        self._start_event_id = str(event["event_id"])

    def model_delta(self, content: str, *, provider: str, model: str | None) -> None:
        if self.logger is None:
            return
        self.logger.record(
            run_id=self._run_id(),
            channel="model",
            event_type="delta",
            phase=self._phase(),
            status="running",
            title="Model response",
            summary="Model streamed a response chunk.",
            content_delta=content,
            display_level="main",
            parent_event_id=self._start_event_id,
            model_provider=provider,
            model_name=model,
            telemetry={"purpose": self.request.purpose},
            call_chain=[str(self.request.metadata.get("agent_id") or "ModelClient"), provider],
            execution_chain=[self.request.purpose, self.request.model_tier],
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
        self.logger.record(
            run_id=self._run_id(),
            channel="model",
            event_type="end",
            phase=self._phase(),
            status="completed",
            title="Model response completed",
            summary=self._summary("completed", provider, model, str((telemetry or {}).get("mode") or "")),
            display_level="main",
            parent_event_id=self._start_event_id,
            model_provider=provider,
            model_name=model,
            telemetry={"purpose": self.request.purpose, **(telemetry or {})},
            call_chain=[str(self.request.metadata.get("agent_id") or "ModelClient"), provider],
            execution_chain=[self.request.purpose, self.request.model_tier],
        )

    def model_error(self, *, provider: str, model: str | None, error: str) -> None:
        if self.logger is None:
            return
        self.logger.record(
            run_id=self._run_id(),
            channel="model",
            event_type="error",
            phase=self._phase(),
            status="failed",
            title="Model response failed",
            summary=error,
            display_level="main",
            parent_event_id=self._start_event_id,
            model_provider=provider,
            model_name=model,
            telemetry={"purpose": self.request.purpose},
            call_chain=[str(self.request.metadata.get("agent_id") or "ModelClient"), provider],
            execution_chain=[self.request.purpose, self.request.model_tier],
            data={"error": error},
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
