from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from asteria_runtime.models.routing import MODEL_TIERS

_ENV_ASSIGNMENT_RE = re.compile(
    r"^\s*\$env:(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)\s*$"
)


def local_route_config_home() -> Path:
    configured = os.getenv("ASTERIA_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".asteria"


def local_route_config_sources() -> tuple[Path, ...]:
    home = local_route_config_home()
    return (
        home / "model.routes.local.ps1",
        home / "model.routes.ps1",
        home / "model.routes.local.json",
        home / "model.routes.json",
    )


def configured_route_tiers() -> set[str]:
    values = _load_values()
    tiers: set[str] = set()
    for tier in MODEL_TIERS:
        if values.get(f"AGENT_MODEL_{tier.upper()}_PROVIDER"):
            tiers.add(tier)
    return tiers


def local_route_value(env_prefix: str, key: str) -> str:
    values = _load_values()
    value = values.get(f"{env_prefix}_{key}")
    if value:
        return value
    if env_prefix != "AGENT_MODEL":
        return values.get(f"AGENT_MODEL_{key}", "")
    return ""


def any_local_route_value(names: tuple[str, ...]) -> str:
    values = _load_values()
    for name in names:
        value = values.get(name)
        if value:
            return value
    return ""


_CACHE_SIGNATURE: tuple[tuple[str, int, int], ...] | None = None
_CACHE_VALUES: dict[str, str] | None = None


def _load_values() -> dict[str, str]:
    global _CACHE_SIGNATURE, _CACHE_VALUES
    signature = _source_signature()
    if _CACHE_VALUES is not None and signature == _CACHE_SIGNATURE:
        return dict(_CACHE_VALUES)

    values: dict[str, str] = {}
    for source in local_route_config_sources():
        if source.suffix.lower() == ".ps1":
            values.update(_load_ps1_env_file(source))
        elif source.suffix.lower() == ".json":
            values.update(_load_json_file(source))

    _CACHE_SIGNATURE = signature
    _CACHE_VALUES = dict(values)
    return values


def _source_signature() -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for source in local_route_config_sources():
        try:
            stat = source.stat()
        except OSError:
            signature.append((str(source), -1, -1))
            continue
        signature.append((str(source), stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def _load_ps1_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        match = _ENV_ASSIGNMENT_RE.match(line)
        if match:
            values[match.group("name")] = match.group("value")
    return values


def _load_json_file(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}

    values: dict[str, str] = {}
    routes = raw.get("routes", raw)
    if isinstance(routes, dict):
        for tier, route in routes.items():
            if not isinstance(route, dict):
                continue
            prefix = "AGENT_MODEL" if str(tier).lower() in {"default", "global"} else (
                f"AGENT_MODEL_{str(tier).upper()}"
            )
            values.update(_flatten_route(prefix, route))

    for key, value in raw.items():
        if isinstance(key, str) and key.startswith("AGENT_MODEL_"):
            values[key] = _stringify(value)
    return values


def _flatten_route(prefix: str, route: dict[str, Any]) -> dict[str, str]:
    aliases = {
        "provider": "PROVIDER",
        "base_url": "BASE_URL",
        "baseUrl": "BASE_URL",
        "api_key": "API_KEY",
        "apiKey": "API_KEY",
        "name": "NAME",
        "model": "NAME",
        "model_name": "NAME",
        "modelName": "NAME",
        "timeout_seconds": "TIMEOUT_SECONDS",
        "timeoutSeconds": "TIMEOUT_SECONDS",
        "max_retries": "MAX_RETRIES",
        "maxRetries": "MAX_RETRIES",
        "streaming": "STREAMING",
        "streaming_enabled": "STREAMING",
        "streamingEnabled": "STREAMING",
        "stream_idle_timeout_seconds": "STREAM_IDLE_TIMEOUT_SECONDS",
        "streamIdleTimeoutSeconds": "STREAM_IDLE_TIMEOUT_SECONDS",
    }
    flattened: dict[str, str] = {}
    for key, value in route.items():
        env_key = aliases.get(str(key))
        if env_key:
            flattened[f"{prefix}_{env_key}"] = _stringify(value)
    return flattened


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    return str(value)
