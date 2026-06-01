from __future__ import annotations

from copy import deepcopy
from typing import Any


def context_prompt_view(runtime_context: dict[str, Any]) -> dict[str, Any]:
    """Return a prompt-safe context view without duplicating persisted envelope payloads."""

    view = deepcopy(runtime_context)
    package = view.get("context_package")
    if not isinstance(package, dict):
        return view
    envelope = package.get("context_envelope")
    if not isinstance(envelope, dict) or "payload" not in envelope:
        return view
    package["context_envelope"] = {
        key: value
        for key, value in envelope.items()
        if key != "payload"
    }
    package["context_envelope"]["payload_omitted"] = True
    package["context_envelope"]["payload_ref"] = package.get("context_envelope_path")
    return view
