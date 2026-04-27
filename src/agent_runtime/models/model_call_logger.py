from __future__ import annotations

from pathlib import Path

from agent_runtime.models.base import ChatRequest, ChatResponse
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


class ModelCallLogger:
    def __init__(self, run_dir: Path | None, validator: SchemaValidator | None = None) -> None:
        self.run_dir = run_dir
        self.store = JsonlStore(validator)

    def record_success(self, request: ChatRequest, response: ChatResponse) -> dict | None:
        return self._record(request, response, status="success", summary="model call succeeded")

    def record_failure(
        self,
        request: ChatRequest,
        provider: str,
        model_name: str,
        model_tier: str,
        error: str,
    ) -> dict | None:
        record = self._base_record(request, provider, model_name, model_tier)
        record.update(
            {
                "input_tokens": None,
                "output_tokens": None,
                "status": "failure",
                "created_at": now_iso(),
                "summary": error,
            }
        )
        self._append(record)
        return record

    def _record(
        self,
        request: ChatRequest,
        response: ChatResponse,
        status: str,
        summary: str,
    ) -> dict | None:
        record = self._base_record(
            request,
            response.model_provider,
            response.model_name,
            request.model_tier,
        )
        record.update(
            {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "status": status,
                "created_at": now_iso(),
                "summary": summary,
            }
        )
        self._append(record)
        return record

    def _base_record(
        self,
        request: ChatRequest,
        provider: str,
        model_name: str,
        model_tier: str,
    ) -> dict:
        existing_count = 0
        if self.run_dir:
            path = self.run_dir / "model_calls.jsonl"
            if path.exists():
                existing_count = len(JsonlStore().read_all(path))
        return {
            "schema_version": "0.1.0",
            "model_call_id": f"modelcall-{existing_count + 1:04d}",
            "run_id": request.metadata.get("run_id"),
            "agent_id": request.metadata.get("agent_id"),
            "purpose": request.purpose,
            "model_provider": provider,
            "model_name": model_name,
            "model_tier": model_tier,
        }

    def _append(self, record: dict) -> None:
        if self.run_dir is None:
            return
        self.store.append(self.run_dir / "model_calls.jsonl", record, "model_call")
