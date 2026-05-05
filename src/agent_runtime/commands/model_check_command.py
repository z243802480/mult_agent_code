from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.json_extractor import parse_json_object
from agent_runtime.models.minimax import ModelProviderError
from agent_runtime.models.model_failure import (
    ModelFailureRecorder,
    model_failure_context_from_env,
)
from agent_runtime.models.openai_compatible import OpenAICompatibleProviderError
from agent_runtime.storage.schema_validator import SchemaValidator


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

    def to_text(self) -> str:
        lines = [
            "Model check",
            f"Provider: {self.provider}",
            f"Model: {self.model_name or 'not configured'}",
            f"Base URL: {self.base_url or 'not configured'}",
            f"Config: {'ok' if self.config_ok else 'failed'}",
            f"Call: {'ok' if self.call_ok else 'skipped/failed'}",
            f"Summary: {self.summary}",
        ]
        if self.failure_type:
            lines.append(f"Failure type: {self.failure_type}")
        if self.failure_report_path:
            lines.append(f"Failure report: {self.failure_report_path}")
        return "\n".join(lines)


class ModelCheckCommand:
    def __init__(
        self,
        root: Path,
        skip_call: bool = False,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.skip_call = skip_call
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.failure_recorder = ModelFailureRecorder(self.root, self.validator)

    def run(self) -> ModelCheckResult:
        context = model_failure_context_from_env()
        provider = context.provider
        model_name = context.model_name
        base_url = context.base_url

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
            )

        if self.skip_call:
            return ModelCheckResult(
                provider=provider,
                model_name=model_name,
                base_url=base_url,
                config_ok=True,
                call_ok=False,
                summary="Configuration loaded; model call skipped.",
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
            )

        return ModelCheckResult(
            provider=response.model_provider or provider,
            model_name=response.model_name or model_name,
            base_url=base_url,
            config_ok=True,
            call_ok=True,
            summary="Model returned valid JSON for the health check prompt.",
        )

    def _request(self) -> ChatRequest:
        return ChatRequest(
            purpose="model_check",
            model_tier="cheap",
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
