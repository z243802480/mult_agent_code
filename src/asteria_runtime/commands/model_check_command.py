from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.agent_role_policy import AgentRoleContract, role_contract_for
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient, StreamingTelemetry
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.json_extractor import parse_json_object
from asteria_runtime.models.minimax import ModelProviderError
from asteria_runtime.models.model_failure import (
    ModelFailureRecorder,
    model_failure_context_from_env,
)
from asteria_runtime.models.openai_compatible import OpenAICompatibleProviderError
from asteria_runtime.models.route_resolver import resolve_model_route, route_health_for_tiers
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


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
    route_health: dict | None = None
    route_fallback: dict | None = None
    call_health: str | None = None

    def to_text(self) -> str:
        route = self.route_health or {}
        lines = [
            "Model check",
            f"Provider: {self.provider}",
            f"Model: {self.model_name or 'not configured'}",
            f"Base URL: {self.base_url or 'not configured'}",
            f"Route health: {route.get('status', 'unknown')}",
            f"Config: {'ok' if self.config_ok else 'failed'}",
            f"Call: {'ok' if self.call_ok else 'skipped/failed'}",
            f"Call health: {self._call_health()}",
            f"Streaming: {self._streaming_text()}",
            f"Summary: {self.summary}",
        ]
        if self.failure_type:
            lines.append(f"Failure type: {self.failure_type}")
        if self.failure_report_path:
            lines.append(f"Failure report: {self.failure_report_path}")
        if route.get("current_blocker"):
            lines.append(f"Route blocker: {route['current_blocker']}")
        if self.route_fallback:
            lines.append(
                "Call fallback: "
                f"{self.route_fallback.get('from_tier', 'unknown')} -> "
                f"{self.route_fallback.get('to_tier', 'unknown')} "
                f"({self.route_fallback.get('policy', 'unknown')})"
            )
        routes = route.get("routes") or []
        if routes:
            fallback = (routes[0].get("fallback") or {}) if isinstance(routes[0], dict) else {}
            if fallback.get("used"):
                lines.append(
                    "Route fallback: "
                    f"{fallback.get('source') or 'unknown'} - "
                    f"{fallback.get('reason') or 'no reason recorded'}"
                )
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
            "call_health": self._call_health(),
            "summary": self.summary,
            "failure_report_path": str(self.failure_report_path)
            if self.failure_report_path
            else None,
            "failure_type": self.failure_type,
            "streaming": self.streaming.to_dict() if self.streaming else None,
            "route_health": self.route_health or {},
            "route_fallback": self.route_fallback or {},
        }

    def _call_health(self) -> str:
        if self.call_health:
            return self.call_health
        if not self.call_ok:
            return "skipped" if "skipped" in self.summary.lower() else "failed"
        if _streaming_degraded(self.streaming):
            return "degraded"
        return "healthy"


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
        route_health = route_health_for_tiers((self.model_tier,))
        context = model_failure_context_from_env(_env_prefix_for_tier(self.model_tier))
        provider = route_resolution.provider or context.provider
        model_name = route_resolution.model_name or context.model_name
        base_url = route_resolution.base_url or context.base_url

        if not route_resolution.configured and self.model_client is None:
            summary = route_resolution.next_action
            return self._record_and_return(
                ModelCheckResult(
                    provider=provider,
                    model_name=model_name,
                    base_url=base_url,
                    config_ok=False,
                    call_ok=False,
                    summary=summary,
                    failure_type="configuration",
                    route_health=route_health,
                )
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
            return self._record_and_return(
                ModelCheckResult(
                    provider=provider,
                    model_name=model_name,
                    base_url=base_url,
                    config_ok=False,
                    call_ok=False,
                    summary=str(exc),
                    failure_report_path=report_path,
                    failure_type=report["failure_type"],
                    route_health=route_health,
                )
            )

        if self.skip_call:
            return self._record_and_return(
                ModelCheckResult(
                    provider=provider,
                    model_name=model_name,
                    base_url=base_url,
                    config_ok=True,
                    call_ok=False,
                    summary="Configuration loaded; model call skipped.",
                    route_health=route_health,
                )
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
            return self._record_and_return(
                ModelCheckResult(
                    provider=provider,
                    model_name=model_name,
                    base_url=base_url,
                    config_ok=True,
                    call_ok=False,
                    summary=f"Model call failed: {exc}",
                    failure_report_path=report_path,
                    failure_type=report["failure_type"],
                    route_health=route_health,
                )
            )

        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            report_path, report = self.failure_recorder.record(
                provider=provider,
                model_name=response.model_name or model_name,
                base_url=base_url,
                error="Model responded, but did not return the expected JSON payload.",
            )
            return self._record_and_return(
                ModelCheckResult(
                    provider=provider,
                    model_name=response.model_name or model_name,
                    base_url=base_url,
                    config_ok=True,
                    call_ok=False,
                    summary="Model responded, but did not return the expected JSON payload.",
                    failure_report_path=report_path,
                    failure_type=report["failure_type"],
                    route_health=route_health,
                )
            )

        route_fallback = _route_fallback(response.raw_response)
        effective_base_url = base_url
        if route_fallback.get("to_tier"):
            effective_base_url = resolve_model_route(str(route_fallback["to_tier"])).base_url
        call_health = "degraded" if _streaming_degraded(response.streaming) else "healthy"
        summary = (
            "Model returned valid JSON, but the streaming route degraded and required fallback."
            if call_health == "degraded"
            else "Model returned valid JSON for the health check prompt."
        )
        return self._record_and_return(
            ModelCheckResult(
                provider=response.model_provider or provider,
                model_name=response.model_name or model_name,
                base_url=effective_base_url or base_url,
                config_ok=True,
                call_ok=True,
                summary=summary,
                streaming=response.streaming,
                route_health=route_health,
                route_fallback=route_fallback,
                call_health=call_health,
            )
        )

    def _record_and_return(self, result: ModelCheckResult) -> ModelCheckResult:
        if self.skip_call:
            return result
        path = self.root / ".asteria" / "model" / "model_route_checks.jsonl"
        JsonlStore(self.validator).append(
            path,
            {
                "schema_version": "0.1.0",
                "created_at": now_iso(),
                "tier": self.model_tier,
                "purpose": "model_check",
                "provider": result.provider,
                "model_name": result.model_name,
                "base_url": result.base_url,
                "status": "success" if result.call_ok else "failure",
                "call_health": result._call_health(),
                "summary": result.summary,
                "failure_type": result.failure_type,
                "deadline_ms": (result.streaming or StreamingTelemetry()).deadline_ms,
                "duration_ms": (result.streaming or StreamingTelemetry()).duration_ms,
                "streaming": result.streaming.to_dict() if result.streaming else None,
                "route_fallback": result.route_fallback or {},
            },
            "model_route_check",
        )
        return result

    def _request(self) -> ChatRequest:
        role_contract = role_contract_for(role="ModelCheckAgent", purpose="model_check")
        route_resolution = resolve_model_route(self.model_tier)
        if route_resolution.deadline_seconds:
            role_contract = AgentRoleContract(
                role=role_contract.role,
                purpose=role_contract.purpose,
                default_model_tier=role_contract.default_model_tier,
                deadline_profile=role_contract.deadline_profile,
                provider_call_seconds=max(
                    role_contract.provider_call_seconds,
                    int(route_resolution.deadline_seconds),
                ),
                stream_idle_timeout_seconds=int(
                    route_resolution.stream_idle_timeout_seconds
                    or role_contract.stream_idle_timeout_seconds
                ),
                max_model_calls=role_contract.max_model_calls,
                responsibilities=role_contract.responsibilities,
                escalation_policy=role_contract.escalation_policy,
            )
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
            metadata={
                "agent_id": "ModelCheckAgent",
                "agent_role_contract": role_contract.to_dict(),
                "deadline_ms": role_contract.provider_call_seconds * 1000,
            },
        )


def _env_prefix_for_tier(model_tier: str) -> str:
    if model_tier in {"strong", "medium", "cheap"}:
        return f"AGENT_MODEL_{model_tier.upper()}"
    return "AGENT_MODEL"


def _route_fallback(raw_response: dict) -> dict:
    fallback = raw_response.get("route_fallback") if isinstance(raw_response, dict) else None
    return fallback if isinstance(fallback, dict) else {}


def _streaming_degraded(streaming: StreamingTelemetry | None) -> bool:
    if streaming is None:
        return False
    return bool(
        streaming.error_type
        or streaming.mode == "streaming_fallback_non_streaming"
        or (streaming.requested and not streaming.supported)
    )
