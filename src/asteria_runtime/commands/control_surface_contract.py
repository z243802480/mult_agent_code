from __future__ import annotations


def control_surface_contract(
    *,
    command: str,
    audience: str,
    stable_fields: list[str],
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "command": command,
        "audience": audience,
        "stability": "additive",
        "stable_fields": stable_fields,
    }
