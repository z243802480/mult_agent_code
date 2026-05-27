from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ContextEnvelope:
    """Auditable model context wrapper.

    The envelope makes mounted context explicit without forcing every caller to
    immediately abandon its existing payload shape.
    """

    envelope_id: str
    audience: str
    mode: str
    intent: str
    root: Path
    run_id: str | None
    sections: list[dict[str, Any]]
    refs: list[str]
    redaction_policy: dict[str, Any]
    payload: dict[str, Any]
    payload_hash: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "envelope_id": self.envelope_id,
            "audience": self.audience,
            "mode": self.mode,
            "intent": self.intent,
            "root": str(self.root),
            "run_id": self.run_id,
            "created_at": self.created_at,
            "sections": self.sections,
            "refs": self.refs,
            "redaction_policy": self.redaction_policy,
            "payload_hash": self.payload_hash,
            "payload": self.payload,
        }

    @classmethod
    def from_payload(
        cls,
        *,
        audience: str,
        mode: str,
        intent: str,
        root: Path,
        run_id: str | None,
        refs: list[str],
        payload: dict[str, Any],
        sections: list[dict[str, Any]],
        redaction_policy: dict[str, Any] | None = None,
    ) -> "ContextEnvelope":
        payload_hash = stable_json_hash(payload)
        return cls(
            envelope_id=f"context-envelope-{mode}-{payload_hash[:12]}",
            audience=audience,
            mode=mode,
            intent=intent,
            root=root,
            run_id=run_id,
            sections=sections,
            refs=refs,
            redaction_policy=redaction_policy
            or {
                "backend_fields_allowed": intent == "debug_question",
                "protected_terms": [
                    "run_id",
                    "evidence_path",
                    "model_route",
                    "provider_raw_error",
                    "secret",
                    "token",
                    "api_key",
                ],
            },
            payload=payload,
            payload_hash=payload_hash,
            created_at=now_iso(),
        )


def stable_json_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
