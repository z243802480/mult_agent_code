from __future__ import annotations

import os
import time
from dataclasses import dataclass

from agent_runtime.core.budget import BudgetController, BudgetExceededError
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from agent_runtime.models.http_transport import HttpResponse, HttpTransport, HttpTransportError
from agent_runtime.models.model_call_logger import ModelCallLogger


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

    @classmethod
    def from_env(
        cls,
        provider: str = "openai-compatible",
        env_prefix: str = "AGENT_MODEL",
    ) -> "OpenAICompatibleSettings":
        api_key = _env(env_prefix, "API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise OpenAICompatibleProviderError(
                f"OpenAI-compatible API key is not configured for {env_prefix}. "
                f"Set {env_prefix}_API_KEY or OPENAI_API_KEY."
            )
        model_name = _env(env_prefix, "NAME")
        if not model_name:
            raise OpenAICompatibleProviderError(
                f"{env_prefix}_NAME is required for OpenAI-compatible providers."
            )
        return cls(
            api_key=api_key,
            base_url=_env(env_prefix, "BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model_name=model_name,
            provider=provider,
            timeout_seconds=int(_env(env_prefix, "TIMEOUT_SECONDS", "90")),
            max_retries=int(_env(env_prefix, "MAX_RETRIES", "2")),
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
        for attempt in range(self.settings.max_retries + 1):
            try:
                http_response = self.transport.post_json(
                    f"{self.settings.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.api_key}",
                        "Content-Type": "application/json",
                    },
                    payload=payload,
                    timeout_seconds=timeout,
                )
                response = self._parse_response(http_response)
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
        )
        raise OpenAICompatibleProviderError(error_text)

    def _payload(self, request: ChatRequest) -> dict:
        payload = {
            "model": self.settings.model_name,
            "messages": [message.to_payload() for message in request.messages],
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_completion_tokens"] = request.max_output_tokens
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _parse_response(self, response: HttpResponse) -> ChatResponse:
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
    if env_prefix != "AGENT_MODEL":
        value = os.getenv(f"AGENT_MODEL_{key}")
        if value is not None:
            return value
    return default or ""
