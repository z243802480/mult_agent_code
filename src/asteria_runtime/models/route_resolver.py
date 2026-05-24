from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.models.route_diagnostics import (
    route_diagnostic_for_tier,
    route_requirement_names,
)


@dataclass(frozen=True)
class ModelRouteResolution:
    tier: str
    provider: str
    model_name: str | None
    configured: bool
    env_prefix: str
    source: str
    missing: list[str]
    next_action: str

    def to_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "provider": self.provider,
            "model_name": self.model_name,
            "configured": self.configured,
            "env_prefix": self.env_prefix,
            "source": self.source,
            "missing": self.missing,
            "next_action": self.next_action,
        }


def resolve_model_route(tier: str) -> ModelRouteResolution:
    diagnostic = route_diagnostic_for_tier(tier)
    missing = list(diagnostic.missing)
    return ModelRouteResolution(
        tier=tier,
        provider=diagnostic.provider,
        model_name=diagnostic.model_name or f"{tier}-route",
        configured=diagnostic.configured,
        env_prefix=diagnostic.env_prefix,
        source=diagnostic.source,
        missing=missing,
        next_action=_next_action(tier, diagnostic.source, missing),
    )


def route_readiness_for_tiers(tiers: list[str] | tuple[str, ...]) -> dict:
    routes = [resolve_model_route(tier).to_dict() for tier in tiers]
    blocked = [route for route in routes if route.get("configured") is False]
    if blocked:
        first = blocked[0]
        missing = first.get("missing")
        missing_items = missing if isinstance(missing, list) else []
        return {
            "status": "blocked",
            "summary": (
                f"Model route `{first['tier']}` is not fully configured: "
                + ", ".join(str(item) for item in missing_items)
            ),
            "routes": routes,
            "blockers": [str(route.get("next_action")) for route in blocked[:3]],
            "current_blocker": first.get("next_action"),
            "recommended_next_command": "model-check",
        }
    return {
        "status": "ready",
        "summary": f"{len(routes)} model route(s) are configured.",
        "routes": routes,
        "blockers": [],
        "current_blocker": None,
        "recommended_next_command": None,
    }


def route_readiness_from_records(records: list[dict]) -> dict:
    routes = [_route_from_record(record) for record in records]
    blocked = [route for route in routes if route.get("configured") is False]
    if blocked:
        first = blocked[0]
        missing = first.get("missing")
        missing_items = missing if isinstance(missing, list) else []
        return {
            "status": "blocked",
            "summary": (
                f"Model route `{first['tier']}` is not fully configured: "
                + ", ".join(str(item) for item in missing_items)
            ),
            "routes": routes,
            "blockers": [str(route.get("next_action")) for route in blocked[:3]],
            "current_blocker": first.get("next_action"),
            "recommended_next_command": "model-check",
        }
    return {
        "status": "ready" if routes else "unknown",
        "summary": f"{len(routes)} model route(s) are configured."
        if routes
        else "No model route records are available.",
        "routes": routes,
        "blockers": [],
        "current_blocker": None,
        "recommended_next_command": None,
    }


def _route_from_record(record: dict) -> dict:
    tier = str(record.get("model_tier") or record.get("tier") or "unknown")
    provider = str(record.get("provider") or "unknown")
    model_name = str(record.get("model_name") or record.get("model") or "unknown")
    if "configured" in record:
        configured = record.get("configured") is True
    else:
        configured = provider not in {"", "unknown"} and model_name not in {"", "unknown"}
    missing = [str(item) for item in record.get("missing") or []]
    if not configured and not missing:
        if provider in {"", "unknown"}:
            missing.append(f"AGENT_MODEL_{tier.upper()}_PROVIDER or AGENT_MODEL_PROVIDER")
        if model_name in {"", "unknown"}:
            missing.append(f"AGENT_MODEL_{tier.upper()}_NAME or provider default")
    next_action = str(record.get("next_action") or "")
    if not next_action:
        next_action = (
            "Model route is configured."
            if configured
            else "Configure model route requirements: " + ", ".join(missing) + "."
        )
    return {
        "tier": tier,
        "purpose": record.get("purpose"),
        "provider": provider,
        "model_name": model_name,
        "configured": configured,
        "missing": missing,
        "next_action": next_action,
    }


def _next_action(tier: str, source: str, missing: list[str]) -> str:
    if missing:
        return (
            "Configure model route requirements: "
            + ", ".join(missing)
            + ". Expected route inputs: "
            + ", ".join(route_requirement_names(tier))
            + "."
        )
    if source.startswith("fallback_tier:"):
        return (
            f"Using fallback route `{source}` for `{tier}`. Configure "
            f"AGENT_MODEL_{tier.upper()}_PROVIDER to make the route explicit."
        )
    return "Model route is configured."
