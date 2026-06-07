"""Optional real-model touch for L3 live workers (S72 maintainer band)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.storage.schema_validator import SchemaValidator

LIVE_PROVIDER_POLICY_KEY = "orchestration_dynamic_live_provider_gray"


def live_provider_enabled(policy: dict[str, Any] | None) -> bool:
    agent_loop = (policy or {}).get("agent_loop")
    if not isinstance(agent_loop, dict):
        return False
    return bool(agent_loop.get(LIVE_PROVIDER_POLICY_KEY))


def record_live_provider_touch(
    *,
    run_dir: Path,
    validator: SchemaValidator,
    task_id: str,
    purpose: str,
    policy: dict[str, Any] | None = None,
    model_client: ModelClient | None = None,
) -> dict[str, Any]:
    """One cheap model ping when live provider gray is enabled; otherwise no-op."""
    if not live_provider_enabled(policy):
        return {"model_calls": 0, "provider": None, "model_name": None, "enabled": False}

    client = model_client or create_model_client(run_dir, validator)
    if client is None:
        return {"model_calls": 0, "provider": None, "model_name": None, "enabled": True, "error": "no_model_client"}

    response = client.chat(
        ChatRequest(
            purpose=purpose,
            model_tier="cheap",
            messages=[
                ChatMessage(
                    role="user",
                    content=(
                        f"L3 orchestration worker touch for task `{task_id}`. "
                        "Reply with one short sentence confirming readonly scope check only."
                    ),
                )
            ],
            temperature=0.0,
            metadata={"purpose": purpose, "model_tier": "cheap", "task_id": task_id},
        )
    )
    return {
        "model_calls": 1,
        "provider": response.model_provider,
        "model_name": response.model_name,
        "enabled": True,
        "summary": (response.content or "").strip()[:240],
    }
