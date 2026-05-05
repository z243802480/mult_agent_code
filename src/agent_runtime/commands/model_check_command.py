from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from agent_runtime.models.factory import create_model_client
from agent_runtime.models.json_extractor import parse_json_object
from agent_runtime.models.local import (
    local_default_base_url,
    local_default_model,
    local_provider_names,
)
from agent_runtime.models.minimax import ModelProviderError, default_minimax_base_url
from agent_runtime.models.model_failure import build_model_failure_report
from agent_runtime.models.openai_compatible import OpenAICompatibleProviderError
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
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
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> ModelCheckResult:
        provider = os.getenv("AGENT_MODEL_PROVIDER", "minimax").lower()
        model_name = os.getenv("AGENT_MODEL_NAME") or self._default_model(provider)
        base_url = os.getenv("AGENT_MODEL_BASE_URL") or self._default_base_url(provider)

        try:
            client = self.model_client or create_model_client(None, self.validator)
        except (ModelProviderError, OpenAICompatibleProviderError) as exc:
            report_path, report = self._write_failure_report(provider, model_name, base_url, exc)
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
            report_path, report = self._write_failure_report(provider, model_name, base_url, exc)
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
            report_path, report = self._write_failure_report(
                provider,
                response.model_name or model_name,
                base_url,
                "Model responded, but did not return the expected JSON payload.",
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

    def _default_model(self, provider: str) -> str | None:
        if provider == "minimax":
            return "MiniMax-M2.7"
        if provider in {"fake", "offline"}:
            return "fake-offline"
        if provider in local_provider_names():
            return os.getenv("AGENT_MODEL_NAME") or local_default_model(provider)
        return None

    def _default_base_url(self, provider: str) -> str | None:
        if provider in {"fake", "offline"}:
            return "local offline provider"
        if provider in local_provider_names():
            return os.getenv("AGENT_MODEL_BASE_URL") or local_default_base_url(provider)
        if provider == "minimax":
            return default_minimax_base_url(os.getenv("AGENT_MODEL_API_KEY"))
        if provider in {"openai", "openai-compatible", "generic"}:
            return "https://api.openai.com/v1"
        return None

    def _write_failure_report(
        self,
        provider: str,
        model_name: str | None,
        base_url: str | None,
        error: Exception | str,
    ) -> tuple[Path, dict]:
        report = build_model_failure_report(
            provider=provider,
            model_name=model_name,
            base_url=base_url,
            error=error,
        )
        path = self.root / ".agent" / "model" / "latest_failure.json"
        self.store.write(path, report, "model_failure_report")
        self._record_failure_memory(report)
        return path, report

    def _record_failure_memory(self, report: dict) -> None:
        path = self.root / ".agent" / "memory" / "failures.jsonl"
        existing = self.jsonl.read_all(path, "memory_entry") if path.exists() else []
        memory = {
            "schema_version": "0.1.0",
            "memory_id": f"memory-{len(existing) + 1:04d}",
            "type": "failure_lesson",
            "content": (
                f"Model provider `{report['provider']}` failed with `{report['failure_type']}`. "
                f"Summary: {report['summary']}"
            ),
            "source": {
                "kind": "model_failure_report",
                "provider": report["provider"],
                "model_name": report["model_name"],
                "base_url": report["base_url"],
                "failure_type": report["failure_type"],
            },
            "tags": ["model", "failure", f"provider:{report['provider']}", report["failure_type"]],
            "confidence": 0.8,
            "created_at": report["created_at"],
        }
        self.jsonl.append(path, memory, "memory_entry")
