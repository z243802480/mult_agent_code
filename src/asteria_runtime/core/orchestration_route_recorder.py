from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.core.orchestration_router import OrchestrationRouteResult
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


def orchestration_routes_path(agent_dir: Path) -> Path:
    return agent_dir / "orchestration_routes.jsonl"


def record_orchestration_route(
    agent_dir: Path,
    *,
    message: str,
    route: OrchestrationRouteResult,
    validator: SchemaValidator,
    requested_mode: str = "auto",
    router_mode: str = "model",
    model_tier: str = "strong",
    source_command: str = "route",
) -> Path:
    path = orchestration_routes_path(agent_dir)
    payload: dict[str, Any] = {
        "schema_version": "0.1.0",
        "recorded_at": now_iso(),
        "source_command": source_command,
        "requested_mode": requested_mode,
        "router_mode": router_mode,
        "model_tier": model_tier,
        "message_preview": str(message or "").strip()[:240],
        "capability_id": route.capability_id,
        "studio_mode": route.studio_mode,
        "route_kind": route.route_kind,
        "route_source": route.source,
        "confidence": route.confidence,
        "reason": route.reason,
        "follow_up_notes": route.follow_up_notes,
    }
    JsonlStore(validator).append(path, payload)
    return path
