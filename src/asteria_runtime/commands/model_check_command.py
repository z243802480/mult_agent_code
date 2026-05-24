from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient, StreamingTelemetry
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.json_extractor import parse_json_object
from asteria_runtime.models.minimax import ModelProviderError
from asteria_runtime.models.model_failure import (
    ModelFailureRecorder,
    model_failure_context_from_env,
)
from asteria_runtime.models.openai_compatible import OpenAICompatibleProviderError
from asteria_runtime.models.route_resolver import resolve_model_route, route_readiness_for_tiers
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class ModelCheckResult:
    provider: str
    model_name: str | None
    base_url: str | None
    config_ok: bool
    call_ok: bool
    summary: str
    failure_report_path: Path | None = None
    failure_type: str | None = None
    streaming: StreamingTelemetry | None = None
    route_readiness: dict | None = None

    def to_text(self) -> str:
        route = self.route_readiness or {}
        lines = [
            "Model check",
            f"Provider: {self.provider}",
            f"Model: {self.model_name or 'not configured'}",
            f"Base URL: {self.base_url or 'not configured'}",
            f"Route readiness: {route.get('status', 'unknown')}",
            f"Config: {'ok' if self.config_ok else 'failed'}",
            f"Call: {'ok' if self.call_ok else 'skipped/failed'}",
            f"Streaming: {self._streaming_text()}",
            f"Summary: {self.summary}",
        ]
        if self.failure_type:
            lines.append(f"Failure type: {self.failure_type}")
        if self.failure_report_path:
            lines.append(f"Failure report: {self.failure_report_path}")
        if route.get("current_blocker"):
            lines.append(f"Route blocker: {route['current_blocker']}")
        return "\n".join(lines)

    def _streaming_text(self) -> str:
        if self.streaming is None:
            return "not observed"
        if self.streaming.requested:
            first = (
                f", first_chunk_ms={self.streaming.first_chunk_ms}"
                if self.streaming.first_chunk_ms is not None
                else ""
            )
            return f"{self.streaming.mode} chunks={self.streaming.chunk_count}{first}"
        return f"{self.streaming.mode} duration_ms={self.streaming.duration_ms}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
            "provider": self.provider,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "config_ok": self.config_ok,
            "call_ok": self.call_ok,
            "summary": self.summary,
            "failure_report_path": str(self.failure_report_path)
            if self.failure_report_path
            else None,
            "failure_type": self.failure_type,
            "streaming": self.streaming.to_dict() if self.streaming else None,
            "route_readiness": self.route_readiness or {},
        }


class ModelCheckCommand:
    def __init__(
        self,
        root: Path,
        skip_call: bool = False,
        model_tier: str = "cheap",
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.skip_call = skip_call
        self.model_tier = model_tier
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.failure_recorder = ModelFailureRecorder(self.root, self.validator)

    def run(self) -> ModelCheckResult:
        route_resolution = resolve_model_route(self.model_tier)
        route_readiness = route_readiness_for_tiers((self.model_tier,))
        context = model_failure_context_from_env(_env_prefix_for_tier(self.model_tier))
        provider = route_resolution.provider or context.provider
        model_name = route_resolution.model_name or context.model_name
        base_url = context.base_url

        if not route_resolution.configured and self.model_client is None:
            summary = route_resolution.next_action
            return ModelCheckResult(
                provider=provider,
                model_name=model_name,
                base_url=base_url,
                config_ok=False,
                call_ok=False,
                summary=summary,
                failure_type="configuration",
                route_readiness=route_readiness,
            )

        try:
            client = self.model_client or create_model_client(None, self.validator)
        except (ModelProviderError, OpenAICompatibleProviderError) as exc:
            report_path, report = self.failure_recorder.record(
                provider=provider,
                model_name=model_name,
                base_url=base_url,
                error=exc,
            )
            return ModelCheckResult(
                provider=provider,
                model_name=model_name,
                base_url=base_url,
                config_ok=False,
                call_ok=False,
                summary=str(exc),
                failure_report_path=report_path,
                failure_type=report["failure_type"],
                route_readiness=route_readiness,
            )

        if self.skip_call:
            return ModelCheckResult(
                provider=provider,
                model_name=model_name,
                base_url=base_url,
                config_ok=True,
                call_ok=False,
                summary="Configuration loaded; model call skipped.",
                route_readiness=route_readiness,
            )

        try:
            response = client.chat(self._request())
            parsed = parse_json_object(response.content)
        except Exception as exc:  # noqa: BLE001 - diagnostic command reports provider boundary failures
            report_path, report = self.failure_recorder.record(
                provider=provider,
                model_name=model_name,
                base_url=base_url,
                error=exc,
            )
            return ModelCheckResult(
                provider=provider,
                model_name=model_name,
                base_url=base_url,
                config_ok=True,
                call_ok=False,
                summary=f"Model call failed: {exc}",
                failure_report_path=report_path,
                failure_type=report["failure_type"],
                route_readiness=route_readiness,
            )

        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            report_path, report = self.failure_recorder.record(
                provider=provider,
                model_name=response.model_name or model_name,
                base_url=base_url,
                error="Model responded, but did not return the expected JSON payload.",
            )
            return ModelCheckResult(
                provider=provider,
                model_name=response.model_name or model_name,
                base_url=base_url,
                config_ok=True,
                call_ok=False,
                summary="Model responded, but did not return the expected JSON payload.",
                failure_report_path=report_path,
                failure_type=report["failure_type"],
                route_readiness=route_readiness,
            )

        return ModelCheckResult(
            provider=response.model_provider or provider,
            model_name=response.model_name or model_name,
            base_url=base_url,
            config_ok=True,
            call_ok=True,
            summary="Model returned valid JSON for the health check prompt.",
            streaming=response.streaming,
            route_readiness=route_readiness,
        )

    def _request(self) -> ChatRequest:
        return ChatRequest(
            purpose="model_check",
            model_tier=self.model_tier,
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "Return only valid JSON as the final answer. Do not wrap in markdown."
                    ),
                ),
                ChatMessage(role="user", content='Return exactly: {"ok": true}'),
            ],
            response_format="json",
            temperature=0.1,
            max_output_tokens=512,
            metadata={"agent_id": "ModelCheckCommand"},
        )


def _env_prefix_for_tier(model_tier: str) -> str:
    if model_tier in {"strong", "medium", "cheap"}:
        return f"AGENT_MODEL_{model_tier.upper()}"
    return "AGENT_MODEL"
