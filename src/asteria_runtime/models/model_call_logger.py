from __future__ import annotations

from pathlib import Path
from threading import RLock
from contextlib import nullcontext
from typing import ContextManager

from asteria_runtime.core.context_budget import estimate_request_context
from asteria_runtime.models.base import ChatRequest, ChatResponse, StreamingTelemetry
from asteria_runtime.models.model_progress_sink import ModelProgressSink, use_model_progress_sink
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


_MODEL_CALL_LOGGER_LOCK = RLock()


class ModelCallLogger:
    def __init__(self, run_dir: Path | None, validator: SchemaValidator | None = None) -> None:
        self.run_dir = run_dir
        self.validator = validator
        self.store = JsonlStore(validator)

    def progress_context(self, request: ChatRequest) -> ContextManager[None]:
        if self.run_dir is None:
            return nullcontext()
        return use_model_progress_sink(ModelProgressSink(self.run_dir, self.validator, request))

    def record_success(self, request: ChatRequest, response: ChatResponse) -> dict | None:
        return self._record(request, response, status="success", summary="model call succeeded")

    def record_failure(
        self,
        request: ChatRequest,
        provider: str,
        model_name: str,
        model_tier: str,
        error: str,
        streaming: StreamingTelemetry | None = None,
    ) -> dict | None:
        with _MODEL_CALL_LOGGER_LOCK:
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
            if streaming is not None:
                record["duration_ms"] = streaming.duration_ms
                record["streaming"] = streaming.to_dict()
            self._append(record)
            return record

    def _record(
        self,
        request: ChatRequest,
        response: ChatResponse,
        status: str,
        summary: str,
    ) -> dict | None:
        with _MODEL_CALL_LOGGER_LOCK:
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
            if response.streaming is not None:
                record["duration_ms"] = response.streaming.duration_ms
                record["streaming"] = response.streaming.to_dict()
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
        role_contract = request.metadata.get("agent_role_contract")
        if not isinstance(role_contract, dict):
            role_contract = None
        record = {
            "schema_version": "0.1.0",
            "model_call_id": f"modelcall-{existing_count + 1:04d}",
            "run_id": request.metadata.get("run_id"),
            "agent_id": request.metadata.get("agent_id"),
            "runtime_profile_id": request.metadata.get("runtime_profile_id"),
            "model_profile_id": request.metadata.get("model_profile_id"),
            "purpose": request.purpose,
            "model_provider": provider,
            "model_name": model_name,
            "model_tier": model_tier,
            "prompt_envelope_hash": request.metadata.get("prompt_envelope_hash"),
            "prompt_envelope_path": request.metadata.get("prompt_envelope_path"),
            "context_envelope_hash": request.metadata.get("context_envelope_hash"),
            "context_envelope_path": request.metadata.get("context_envelope_path"),
            "capability_manifest_hash": request.metadata.get("capability_manifest_hash"),
            "context_mode": request.metadata.get("context_mode"),
            "fast_path_task_kind": request.metadata.get("fast_path_task_kind"),
        }
        estimate = estimate_request_context(request)
        record["context_estimate"] = estimate.to_dict()
        if role_contract is not None:
            record["agent_role_contract"] = role_contract
            record["agent_role"] = role_contract.get("role")
            record["deadline_profile"] = role_contract.get("deadline_profile")
        if request.metadata.get("model_route") is not None:
            record["model_route"] = request.metadata.get("model_route")
        # Persist a route fallback (e.g. strong->medium on timeout) as durable evidence. The
        # RoutedModelClient stamps this onto the retried request's metadata (models/routing.py);
        # without this the medium retry was logged as an ordinary medium call with no attribution.
        route_fallback = request.metadata.get("route_fallback")
        if isinstance(route_fallback, dict):
            record["route_fallback"] = route_fallback
        deadline_ms = self._deadline_ms(request, role_contract)
        if deadline_ms is not None:
            record["deadline_ms"] = deadline_ms
        return record

    def _deadline_ms(self, request: ChatRequest, role_contract: dict | None) -> int | None:
        metadata_deadline = request.metadata.get("deadline_ms")
        if isinstance(metadata_deadline, int):
            return metadata_deadline
        if isinstance(metadata_deadline, float):
            return int(metadata_deadline)
        if role_contract is not None:
            provider_call_seconds = role_contract.get("provider_call_seconds")
            if isinstance(provider_call_seconds, (int, float)):
                return int(provider_call_seconds * 1000)
        if request.timeout_seconds is not None:
            return int(request.timeout_seconds * 1000)
        return None

    def _append(self, record: dict) -> None:
        if self.run_dir is None:
            return
        self.store.append(self.run_dir / "model_calls.jsonl", record, "model_call")
