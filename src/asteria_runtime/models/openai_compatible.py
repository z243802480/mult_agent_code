from __future__ import annotations

import os
import time
from dataclasses import dataclass

from asteria_runtime.core.budget import BudgetController, BudgetExceededError
from asteria_runtime.models.base import ChatRequest, ChatResponse, StreamingTelemetry, TokenUsage
from asteria_runtime.models.http_transport import HttpResponse, HttpTransport, HttpTransportError
from asteria_runtime.models.local_route_config import any_local_route_value, local_route_value
from asteria_runtime.models.model_call_logger import ModelCallLogger


class OpenAICompatibleProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAICompatibleSettings:
    api_key: str
    base_url: str
    model_name: str
    provider: str = "openai-compatible"
    timeout_seconds: int = 90
    max_retries: int = 2
    streaming_enabled: bool = True
    stream_idle_timeout_seconds: int = 30

    @classmethod
    def from_env(
        cls,
        provider: str = "openai-compatible",
        env_prefix: str = "AGENT_MODEL",
        default_base_url: str = "https://api.openai.com/v1",
        default_model_name: str | None = None,
        api_key_env_names: tuple[str, ...] = ("OPENAI_API_KEY",),
    ) -> "OpenAICompatibleSettings":
        api_key = _env(env_prefix, "API_KEY") or _first_env(api_key_env_names)
        if not api_key:
            raise OpenAICompatibleProviderError(
                f"OpenAI-compatible API key is not configured for {env_prefix}. "
                f"Set {env_prefix}_API_KEY or one of: {', '.join(api_key_env_names)}."
            )
        model_name = _env(env_prefix, "NAME") or default_model_name
        if not model_name:
            raise OpenAICompatibleProviderError(
                f"{env_prefix}_NAME is required for OpenAI-compatible providers."
            )
        return cls(
            api_key=api_key,
            base_url=_env(env_prefix, "BASE_URL", default_base_url).rstrip("/"),
            model_name=model_name,
            provider=provider,
            timeout_seconds=int(_env(env_prefix, "TIMEOUT_SECONDS", "90")),
            max_retries=int(_env(env_prefix, "MAX_RETRIES", "2")),
            streaming_enabled=_env_bool(env_prefix, "STREAMING", True),
            stream_idle_timeout_seconds=int(
                _env(env_prefix, "STREAM_IDLE_TIMEOUT_SECONDS", "30")
            ),
        )


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: OpenAICompatibleSettings,
        transport: HttpTransport | None = None,
        logger: ModelCallLogger | None = None,
        budget: BudgetController | None = None,
    ) -> None:
        self.settings = settings
        self.provider = settings.provider
        self.transport = transport or HttpTransport()
        self.logger = logger or ModelCallLogger(None)
        self.budget = budget

    def chat(self, request: ChatRequest) -> ChatResponse:
        if self.budget:
            try:
                self.budget.record_model_call(request.model_tier)
            except BudgetExceededError as exc:
                error_text = str(exc)
                self.logger.record_failure(
                    request,
                    provider=self.provider,
                    model_name=self.settings.model_name,
                    model_tier=request.model_tier,
                    error=error_text,
                )
                raise OpenAICompatibleProviderError(error_text) from exc

        payload = self._payload(request)
        timeout = request.timeout_seconds or self.settings.timeout_seconds
        last_error: Exception | None = None
        call_started = time.monotonic()
        for attempt in range(self.settings.max_retries + 1):
            try:
                with self.logger.progress_context(request):
                    response = self._call_provider(payload, timeout)
                if self.budget:
                    self.budget.record_model_tokens(
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                    )
                self.logger.record_success(request, response)
                return response
            except Exception as exc:  # noqa: BLE001 - provider boundary normalizes all failures
                last_error = exc
                if not self._should_retry(exc, attempt):
                    break
                time.sleep(min(3, 1 + attempt * 2))

        error_text = str(last_error) if last_error else "unknown OpenAI-compatible provider error"
        self.logger.record_failure(
            request,
            provider=self.provider,
            model_name=self.settings.model_name,
            model_tier=request.model_tier,
            error=error_text,
            streaming=StreamingTelemetry(
                requested=self.settings.streaming_enabled,
                supported=False,
                mode="streaming_failed" if self.settings.streaming_enabled else "non_streaming_failed",
                duration_ms=int((time.monotonic() - call_started) * 1000),
                idle_timeout_ms=timeout * 1000,
                deadline_ms=timeout * 1000,
                error_type="provider_error",
            ),
        )
        raise OpenAICompatibleProviderError(error_text)

    def _payload(self, request: ChatRequest) -> dict:
        payload = {
            "model": self.settings.model_name,
            "messages": [message.to_payload() for message in request.messages],
            "stream": self.settings.streaming_enabled,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_completion_tokens"] = request.max_output_tokens
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        if self.settings.streaming_enabled:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _call_provider(self, payload: dict, timeout: int) -> ChatResponse:
        url = f"{self.settings.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.streaming_enabled:
            stream_started = time.monotonic()
            try:
                stream_response = self.transport.post_json_stream(
                    url,
                    headers=headers,
                    payload=payload,
                    timeout_seconds=timeout,
                    idle_timeout_seconds=min(timeout, self.settings.stream_idle_timeout_seconds),
                    deadline_seconds=timeout,
                )
            except HttpTransportError as exc:
                if not _is_streaming_setup_error(str(exc)):
                    raise
                remaining_timeout = _remaining_timeout_seconds(stream_started, timeout)
                if remaining_timeout <= 0:
                    raise
                return self._call_provider_non_streaming(
                    url,
                    headers,
                    payload,
                    remaining_timeout,
                    fallback_started=stream_started,
                    fallback_error_type="streaming_transport_error",
                )
            if _is_streaming_unsupported(stream_response.status_code, stream_response.body):
                return self._call_provider_non_streaming(
                    url,
                    headers,
                    payload,
                    _remaining_timeout_seconds(stream_started, timeout),
                    fallback_started=stream_started,
                    fallback_error_type="streaming_unsupported",
                )
            return self._parse_response(
                HttpResponse(stream_response.status_code, stream_response.body),
                stream_response.telemetry,
            )
        return self._call_provider_non_streaming(url, headers, payload, timeout)

    def _call_provider_non_streaming(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        timeout: int,
        *,
        fallback_started: float | None = None,
        fallback_error_type: str | None = None,
    ) -> ChatResponse:
        non_streaming_payload = dict(payload)
        non_streaming_payload["stream"] = False
        non_streaming_payload.pop("stream_options", None)
        started = time.monotonic()
        http_response = self.transport.post_json(
            url,
            headers=headers,
            payload=non_streaming_payload,
            timeout_seconds=timeout,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        if fallback_started is not None:
            duration_ms = int((time.monotonic() - fallback_started) * 1000)
        telemetry = StreamingTelemetry(
            requested=fallback_started is not None,
            supported=False,
            mode="streaming_fallback_non_streaming" if fallback_started is not None else "non_streaming",
            duration_ms=duration_ms,
            idle_timeout_ms=timeout * 1000,
            deadline_ms=timeout * 1000,
            error_type=fallback_error_type,
        )
        return self._parse_response(http_response, telemetry)

    def _parse_response(
        self,
        response: HttpResponse,
        telemetry: StreamingTelemetry | None = None,
    ) -> ChatResponse:
        if response.status_code < 200 or response.status_code >= 300:
            raise OpenAICompatibleProviderError(f"HTTP {response.status_code}: {response.body}")
        choices = response.body.get("choices") or []
        if not choices:
            raise OpenAICompatibleProviderError("response did not include choices")
        first = choices[0]
        message = first.get("message") or {}
        content = message.get("content")
        if content is None:
            raise OpenAICompatibleProviderError("response did not include message.content")
        usage = response.body.get("usage") or {}
        return ChatResponse(
            content=content,
            finish_reason=first.get("finish_reason"),
            usage=TokenUsage(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                usage_estimated=False,
            ),
            model_provider=self.provider,
            model_name=response.body.get("model") or self.settings.model_name,
            raw_response=response.body,
            streaming=telemetry,
        )

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        if attempt >= self.settings.max_retries:
            return False
        if isinstance(exc, HttpTransportError):
            return True
        message = str(exc)
        return "429" in message or "timeout" in message.lower() or "HTTP 5" in message


def _env(env_prefix: str, key: str, default: str | None = None) -> str:
    value = os.getenv(f"{env_prefix}_{key}")
    if value is not None:
        return value
    value = local_route_value(env_prefix, key)
    if value:
        return value
    if env_prefix != "AGENT_MODEL":
        value = os.getenv(f"AGENT_MODEL_{key}")
        if value is not None:
            return value
        value = local_route_value("AGENT_MODEL", key)
        if value:
            return value
    return default or ""


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return any_local_route_value(names)


def _env_bool(env_prefix: str, key: str, default: bool) -> bool:
    value = _env(env_prefix, key)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _is_streaming_unsupported(status_code: int, body: dict) -> bool:
    if status_code < 400:
        return False
    text = str(body).lower()
    streaming_words = ("stream", "streaming", "sse", "server-sent")
    unsupported_words = (
        "not support",
        "unsupported",
        "does not support",
        "not enabled",
        "invalid parameter",
        "unknown parameter",
    )
    return any(word in text for word in streaming_words) and any(
        word in text for word in unsupported_words
    )


def _is_streaming_setup_error(message: str) -> bool:
    text = message.lower()
    return any(
        marker in text
        for marker in (
            "unexpected_eof",
            "eof occurred",
            "connection reset",
            "connection aborted",
            "stream request timed out",
            "stream deadline exceeded",
            "ssl",
            "tls",
        )
    )


def _remaining_timeout_seconds(started: float, timeout: int) -> int:
    elapsed = int(time.monotonic() - started)
    return max(0, timeout - elapsed)
