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


def execution_prompt_view(
    runtime_context: dict[str, Any], *, project_guidance: str | None = None
) -> dict[str, Any]:
    """Reference project guidance already fully covered by the execution system prompt.

    Runtime enforcement and persisted evidence keep the original context. Only a copy
    already in the system prompt is reduced. Audit envelopes can contain
    additional policy and budget guidance, so they stay intact along with tool schemas,
    task contracts, failures and unknown extensions.
    """
    view = context_prompt_view(runtime_context)
    if project_guidance:
        containers = [view]
        package = view.get("context_package")
        if isinstance(package, dict):
            containers.append(package)
        for container in containers:
            guidance = container.get("root_guidance")
            if not isinstance(guidance, dict) or guidance.get("path") != "AGENTS.md":
                continue
            content = guidance.get("content")
            if (
                isinstance(content, str)
                and content.strip()
                and project_guidance.strip().startswith(content.strip())
            ):
                guidance.pop("content")
                guidance["content_ref"] = "system.project_guidance"
    return view
