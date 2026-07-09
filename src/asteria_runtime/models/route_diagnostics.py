from __future__ import annotations

import os
from dataclasses import dataclass

from asteria_runtime.models.factory import ZAI_PROVIDER_ALIASES, ZHIPU_PROVIDER_ALIASES
from asteria_runtime.models.local import local_provider_names
from asteria_runtime.models.local_route_config import any_local_route_value, local_route_value
from asteria_runtime.models.default_routes import default_route_for_tier
from asteria_runtime.models.model_failure import model_failure_context_from_env
from asteria_runtime.models.routing import MODEL_TIERS


@dataclass(frozen=True)
class RouteDiagnostic:
    tier: str
    configured: bool
    provider: str
    model_name: str | None
    base_url: str | None
    env_prefix: str
    source: str
    missing: list[str]
    api_key_present: bool
    streaming_enabled: bool
    stream_idle_timeout_seconds: int | None
    timeout_seconds: int | None
    fallback_used: bool = False
    fallback_source: str | None = None
    fallback_reason: str | None = None
    selection_reason: str = "explicit_route"
    returns_canned_output: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "missing": self.missing,
            "provider": self.provider,
            "model": self.model_name,
            "base_url": self.base_url,
            "env_prefix": self.env_prefix,
            "source": self.source,
            "api_key_present": self.api_key_present,
            # ADR-0016 §3 honesty: the fake/offline provider fabricates output. Surface that
            # explicitly so no consumer (doctor, gate-status, Studio) presents a canned tier as a
            # real, "configured" model. `configured` stays true (an offline run is intentional), but
            # this flag makes the canned output impossible to mistake for a real provider.
            "returns_canned_output": self.returns_canned_output,
            "streaming": {
                "enabled": self.streaming_enabled,
                "idle_timeout_seconds": self.stream_idle_timeout_seconds,
                "deadline_seconds": self.timeout_seconds,
            },
            "selection_reason": self.selection_reason,
            "fallback": {
                "used": self.fallback_used,
                "source": self.fallback_source,
                "reason": self.fallback_reason,
            },
        }


def route_diagnostic_for_tier(tier: str) -> RouteDiagnostic:
    env_prefix, provider, source = _effective_route(tier)

    context = model_failure_context_from_env(env_prefix)
    provider = provider or context.provider
    default_route = default_route_for_tier(tier)
    is_default_fallback = source == default_route.source
    model_name: str | None
    base_url: str | None
    if is_default_fallback:
        provider = default_route.provider
        model_name = default_route.model_name
        base_url = default_route.base_url
    else:
        model_name = context.model_name
        base_url = context.base_url
    api_key_present = _api_key_present(provider, env_prefix)
    missing = _missing_requirements(provider, env_prefix, api_key_present, model_name)
    fallback_used = is_default_fallback or source.startswith("fallback_tier:")
    selection_reason = _selection_reason(tier, source)
    return RouteDiagnostic(
        tier=tier,
        configured=not missing,
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        env_prefix=env_prefix,
        source=source,
        missing=missing,
        api_key_present=api_key_present,
        streaming_enabled=_env_bool(env_prefix, "STREAMING", True),
        stream_idle_timeout_seconds=(
            _env_int(env_prefix, "STREAM_IDLE_TIMEOUT_SECONDS")
            or default_route.stream_idle_timeout_seconds
        ),
        timeout_seconds=_env_int(env_prefix, "TIMEOUT_SECONDS") or default_route.deadline_seconds,
        fallback_used=fallback_used,
        fallback_source=source if fallback_used else None,
        fallback_reason=_fallback_reason(tier, source) if fallback_used else None,
        selection_reason=selection_reason,
        returns_canned_output=provider in {"fake", "offline"},
    )


def silently_canned_tiers(tiers: tuple[str, ...] = MODEL_TIERS) -> list[str]:
    """Tiers that fabricate canned output while at least one *other* tier uses a real provider.

    This is the silent-footgun subset only: a fully-offline run (every tier canned) is an
    intentional air-gap and returns ``[]``; a fully-real config also returns ``[]``. Mirrors
    gate-status ``silently_offline`` and factory ``_warn_if_tier_silently_offline`` — the mixed
    config is the hazard, because any call routed to a canned tier (summaries, classification,
    some model-checks) returns fabricated output while the operator believes a real model is set.
    """
    canned = [tier for tier in tiers if route_diagnostic_for_tier(tier).returns_canned_output]
    return canned if 0 < len(canned) < len(tiers) else []


def _effective_route(tier: str) -> tuple[str, str, str]:
    tier_prefix = f"AGENT_MODEL_{tier.upper()}"
    tier_provider = _env(f"{tier_prefix}_PROVIDER") or local_route_value(tier_prefix, "PROVIDER")
    if tier_provider:
        source = "tier" if _env(f"{tier_prefix}_PROVIDER") else "local_tier"
        return tier_prefix, tier_provider.lower(), source

    global_provider = _env("AGENT_MODEL_PROVIDER") or local_route_value("AGENT_MODEL", "PROVIDER")
    if global_provider:
        source = "global" if _env("AGENT_MODEL_PROVIDER") else "local_global"
        return "AGENT_MODEL", global_provider.lower(), source

    tier_routes = [
        (
            candidate,
            _env(f"AGENT_MODEL_{candidate.upper()}_PROVIDER")
            or local_route_value(f"AGENT_MODEL_{candidate.upper()}", "PROVIDER"),
        )
        for candidate in MODEL_TIERS
    ]
    configured_routes = [
        (candidate, provider)
        for candidate, provider in tier_routes
        if provider
    ]
    for candidate, provider in configured_routes:
        if candidate == "medium":
            return (
                f"AGENT_MODEL_{candidate.upper()}",
                provider.lower(),
                f"fallback_tier:{candidate}",
            )
    if configured_routes:
        candidate, provider = configured_routes[0]
        return (
            f"AGENT_MODEL_{candidate.upper()}",
            provider.lower(),
            f"fallback_tier:{candidate}",
        )
    default_route = default_route_for_tier(tier)
    return f"AGENT_MODEL_{tier.upper()}", default_route.provider, default_route.source


def route_environment_for_tiers(
    tiers: tuple[str, ...] = ("strong", "medium"),
    *,
    allow_tier_fallback: bool = False,
) -> dict[str, object]:
    diagnostics = {tier: route_diagnostic_for_tier(tier) for tier in tiers}
    missing_required = list(dict.fromkeys(
        missing
        for diagnostic in diagnostics.values()
        for missing in diagnostic.missing
    ))
    if not allow_tier_fallback:
        missing_required.extend(
            f"AGENT_MODEL_{diagnostic.tier.upper()}_PROVIDER or AGENT_MODEL_PROVIDER"
            for diagnostic in diagnostics.values()
            if diagnostic.source.startswith("fallback_tier:")
        )
        missing_required = list(dict.fromkeys(missing_required))
    return {
        "ready": not missing_required,
        "missing_required": missing_required,
        **{tier: diagnostic.to_dict() for tier, diagnostic in diagnostics.items()},
    }


def route_requirement_names(tier: str) -> list[str]:
    prefix = f"AGENT_MODEL_{tier.upper()}"
    if tier == "cheap":
        return [f"{prefix}_PROVIDER", "or AGENT_MODEL_PROVIDER"]
    return [
        f"{prefix}_PROVIDER or AGENT_MODEL_PROVIDER",
        f"{prefix}_NAME or provider default",
        f"{prefix}_API_KEY or provider/global API key",
    ]


def _missing_requirements(
    provider: str,
    env_prefix: str,
    api_key_present: bool,
    model_name: str | None,
) -> list[str]:
    missing: list[str] = []
    if not provider:
        missing.append(f"{env_prefix}_PROVIDER")
    if provider in {"fake", "offline"}:
        return missing
    if provider in local_provider_names():
        if not model_name:
            missing.append(f"{env_prefix}_NAME")
        return missing
    if provider == "minimax":
        if not api_key_present:
            missing.append(_api_key_requirement(env_prefix, ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY")))
        return missing
    if provider in ZAI_PROVIDER_ALIASES:
        if not api_key_present:
            missing.append(_api_key_requirement(env_prefix, ("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY")))
        return missing
    if provider in ZHIPU_PROVIDER_ALIASES:
        if not api_key_present:
            missing.append(_api_key_requirement(env_prefix, ("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "GLM_API_KEY")))
        return missing
    if provider in {"openai", "openai-compatible", "generic"}:
        if not model_name:
            missing.append(f"{env_prefix}_NAME")
        if not api_key_present:
            missing.append(_api_key_requirement(env_prefix, ("OPENAI_API_KEY",)))
        return missing
    missing.append(f"supported provider for {env_prefix}_PROVIDER")
    return missing


def _api_key_present(provider: str, env_prefix: str) -> bool:
    if _env_key(env_prefix, "API_KEY"):
        return True
    if provider in {"fake", "offline"} or provider in local_provider_names():
        return True
    if provider == "minimax":
        return _any_env(("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY")) or bool(
            any_local_route_value(("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY"))
        )
    if provider in ZAI_PROVIDER_ALIASES:
        return _any_env(("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY")) or bool(
            any_local_route_value(("ZAI_API_KEY", "GLM_API_KEY", "ZHIPU_API_KEY"))
        )
    if provider in ZHIPU_PROVIDER_ALIASES:
        return _any_env(("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "GLM_API_KEY")) or bool(
            any_local_route_value(("ZHIPU_API_KEY", "BIGMODEL_API_KEY", "GLM_API_KEY"))
        )
    if provider in {"openai", "openai-compatible", "generic"}:
        return _any_env(("OPENAI_API_KEY",)) or bool(any_local_route_value(("OPENAI_API_KEY",)))
    return False


def _api_key_requirement(env_prefix: str, aliases: tuple[str, ...]) -> str:
    names = [f"{env_prefix}_API_KEY"]
    if env_prefix != "AGENT_MODEL":
        names.append("AGENT_MODEL_API_KEY")
    names.extend(aliases)
    return " or ".join(names)


def _env_key(env_prefix: str, key: str) -> str:
    value = _env(f"{env_prefix}_{key}")
    if value:
        return value
    value = local_route_value(env_prefix, key)
    if value:
        return value
    if env_prefix != "AGENT_MODEL":
        return _env(f"AGENT_MODEL_{key}") or local_route_value("AGENT_MODEL", key)
    return ""


def _any_env(names: tuple[str, ...]) -> bool:
    return any(_env(name) for name in names)


def _env(name: str) -> str:
    return os.getenv(name) or ""


def _env_int(env_prefix: str, key: str) -> int | None:
    value = _env_key(env_prefix, key)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _env_bool(env_prefix: str, key: str, default: bool) -> bool:
    value = _env_key(env_prefix, key)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _fallback_reason(tier: str, source: str) -> str:
    if source == "default_route_policy":
        return (
            f"No explicit env/local route was found for `{tier}`; using the stable "
            "default route policy so route guidance remains auditable."
        )
    if source.startswith("fallback_tier:"):
        fallback_tier = source.split(":", 1)[1]
        return (
            f"No explicit route was found for `{tier}`; using configured `{fallback_tier}` "
            "route as a tier fallback."
        )
    return "Route fallback was used."


def _selection_reason(tier: str, source: str) -> str:
    if source == "tier":
        return f"Selected `{tier}` because tier-specific environment configuration exists."
    if source == "local_tier":
        return f"Selected `{tier}` because tier-specific local route configuration exists."
    if source == "global":
        return f"Selected `{tier}` from global environment route configuration."
    if source == "local_global":
        return f"Selected `{tier}` from global local route configuration."
    if source.startswith("fallback_tier:"):
        return _fallback_reason(tier, source)
    if source == "default_route_policy":
        return _fallback_reason(tier, source)
    return "Selected model route from available route configuration."
