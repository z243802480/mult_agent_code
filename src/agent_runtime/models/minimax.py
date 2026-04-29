from __future__ import annotations

import os
import time
from dataclasses import dataclass

from agent_runtime.core.budget import BudgetController, BudgetExceededError
from agent_runtime.models.base import ChatRequest, ChatResponse, TokenUsage
from agent_runtime.models.http_transport import HttpResponse, HttpTransport, HttpTransportError
from agent_runtime.models.model_call_logger import ModelCallLogger


class ModelProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class MiniMaxSettings:
    api_key: str
    base_url: str = "https://api.minimax.io/v1"
    model_name: str = "MiniMax-M2.7"
    timeout_seconds: int = 90
    max_retries: int = 2

    @classmethod
    def from_env(cls, env_prefix: str = "AGENT_MODEL") -> "MiniMaxSettings":
        api_key = (
            _env(env_prefix, "API_KEY")
            or os.getenv("MINIMAX_API_KEY")
            or os.getenv("MINIMAX_CN_API_KEY")
        )
        if not api_key:
            raise ModelProviderError(
                f"MiniMax API key is not configured for {env_prefix}. "
                f"Set {env_prefix}_API_KEY, MINIMAX_API_KEY, or MINIMAX_CN_API_KEY."
            )
        default_base_url = default_minimax_base_url(api_key)
        return cls(
            api_key=api_key,
            base_url=_env(env_prefix, "BASE_URL", default_base_url).rstrip("/"),
            model_name=_env(env_prefix, "NAME", "MiniMax-M2.7"),
            timeout_seconds=int(_env(env_prefix, "TIMEOUT_SECONDS", "90")),
            max_retries=int(_env(env_prefix, "MAX_RETRIES", "2")),
        )


class MiniMaxOpenAICompatibleClient:
    provider = "minimax"

    def __init__(
        self,
        settings: MiniMaxSettings,
        transport: HttpTransport | None = None,
        logger: ModelCallLogger | None = None,
        budget: BudgetController | None = None,
    ) -> None:
        self.settings = settings
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
                raise ModelProviderError(error_text) from exc

        payload = self._payload(request)
        timeout = request.timeout_seconds or self.settings.timeout_seconds
        last_error: Exception | None = None

        for attempt in range(self.settings.max_retries + 1):
            try:
                http_response = self.transport.post_json(
                    self._chat_url(),
                    headers={
                        "Authorization": f"Bearer {self.settings.api_key}",
                        "Content-Type": "application/json",
                    },
                    payload=payload,
                    timeout_seconds=timeout,
                )
                response = self._parse_response(http_response)
                if self.budget:
                    self._update_budget_tokens(response)
                self.logger.record_success(request, response)
                return response
            except Exception as exc:  # noqa: BLE001 - provider boundary normalizes all failures
                last_error = exc
                if not self._should_retry(exc, attempt):
                    break
                time.sleep(min(3, 1 + attempt * 2))

        error_text = str(last_error) if last_error else "unknown MiniMax provider error"
        self.logger.record_failure(
            request,
            provider=self.provider,
            model_name=self.settings.model_name,
            model_tier=request.model_tier,
            error=error_text,
        )
        raise ModelProviderError(error_text)

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
            # MiniMax's OpenAI-compatible endpoint accepts OpenAI-style request bodies,
            # but JSON mode availability can vary by model. Keep this optional and
            # still validate JSON at the runtime boundary.
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _chat_url(self) -> str:
        return f"{self.settings.base_url}/chat/completions"

    def _parse_response(self, response: HttpResponse) -> ChatResponse:
        if response.status_code < 200 or response.status_code >= 300:
            raise ModelProviderError(f"MiniMax HTTP {response.status_code}: {response.body}")

        body = response.body
        base_resp = body.get("base_resp")
        if isinstance(base_resp, dict) and base_resp.get("status_code") not in (None, 0):
            raise ModelProviderError(f"MiniMax error: {base_resp}")

        choices = body.get("choices") or []
        if not choices:
            raise ModelProviderError("MiniMax response did not include choices")
        first = choices[0]
        message = first.get("message") or {}
        content = message.get("content")
        if content is None:
            raise ModelProviderError("MiniMax response did not include message.content")

        usage = body.get("usage") or {}
        token_usage = TokenUsage(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            usage_estimated=False,
        )
        return ChatResponse(
            content=content,
            finish_reason=first.get("finish_reason"),
            usage=token_usage,
            model_provider=self.provider,
            model_name=body.get("model") or self.settings.model_name,
            raw_response=body,
        )

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        if attempt >= self.settings.max_retries:
            return False
        if isinstance(exc, HttpTransportError):
            return True
        message = str(exc)
        return "429" in message or "timeout" in message.lower() or "HTTP 5" in message

    def _update_budget_tokens(self, response: ChatResponse) -> None:
        if not self.budget:
            return
        self.budget.record_model_tokens(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


def _env(env_prefix: str, key: str, default: str | None = None) -> str:
    value = os.getenv(f"{env_prefix}_{key}")
    if value is not None:
        return value
    if env_prefix != "AGENT_MODEL":
        value = os.getenv(f"AGENT_MODEL_{key}")
        if value is not None:
            return value
    return default or ""


def default_minimax_base_url(api_key: str | None = None) -> str:
    if api_key and api_key.startswith("sk-cp-"):
        return "https://api.minimaxi.com/v1"
    return "https://api.minimax.io/v1"
