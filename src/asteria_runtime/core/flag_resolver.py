from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureFlag:
    """A named toggle that controls whether a capability is active.

    Feature flags are persisted in policy_config.feature_flags and control
    runtime behavior (e.g. enable streaming, enable debug export).
    """

    name: str
    enabled: bool
    description: str = ""
    requires: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "description": self.description,
            "requires": sorted(self.requires),
        }


@dataclass(frozen=True)
class CapabilityFlag:
    """Describes whether the current environment supports a required capability.

    Capability flags are derived from runtime environment (not user-configurable)
    and indicate whether required resources are actually available.
    """

    name: str
    available: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "reason": self.reason,
        }


@dataclass
class FlagResolution:
    """Result of checking a feature flag against current capabilities."""

    flag: FeatureFlag
    capability: CapabilityFlag | None
    active: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.flag.name,
            "active": self.active,
            "reason": self.reason,
            "feature_enabled": self.flag.enabled,
        }
        if self.capability:
            result["capability_available"] = self.capability.available
            result["capability_reason"] = self.capability.reason
        return result


class FlagResolver:
    """Resolves feature flags against current environment capabilities.

    A feature is only truly active when both:
    1. The feature flag is enabled in policy config
    2. All required capabilities are available in the current environment
    """

    def __init__(
        self,
        feature_flags: dict[str, FeatureFlag] | None = None,
        capability_flags: dict[str, CapabilityFlag] | None = None,
    ) -> None:
        self.features = feature_flags or {}
        self.capabilities = capability_flags or {}

    def resolve(self, name: str) -> FlagResolution | None:
        flag = self.features.get(name)
        if flag is None:
            return None

        if not flag.enabled:
            return FlagResolution(
                flag=flag,
                capability=None,
                active=False,
                reason="Feature flag is disabled.",
            )

        missing = []
        cap = None
        for req in flag.requires:
            cap = self.capabilities.get(req)
            if cap is None or not cap.available:
                missing.append(req)

        if missing:
            return FlagResolution(
                flag=flag,
                capability=cap,
                active=False,
                reason=f"Missing capabilities: {', '.join(sorted(missing))}.",
            )

        return FlagResolution(
            flag=flag,
            capability=cap,
            active=True,
            reason="Feature is enabled and all required capabilities are available.",
        )

    def resolve_all(self) -> dict[str, dict[str, Any]]:
        return {name: r.to_dict() for name in self.features if (r := self.resolve(name)) is not None}

    @classmethod
    def from_policy(
        cls,
        policy: dict[str, Any],
        environment: dict[str, bool] | None = None,
    ) -> FlagResolver:
        feature_raw = policy.get("feature_flags", {})
        capability_raw = policy.get("capability_flags", {})

        features: dict[str, FeatureFlag] = {}
        for name, value in feature_raw.items():
            if isinstance(value, bool):
                features[name] = FeatureFlag(name=name, enabled=value)
            elif isinstance(value, dict):
                features[name] = FeatureFlag(
                    name=name,
                    enabled=bool(value.get("enabled", False)),
                    description=value.get("description", ""),
                    requires=frozenset(value.get("requires", [])),
                )

        capabilities: dict[str, CapabilityFlag] = {}
        env = environment or {}
        for name, value in capability_raw.items():
            if isinstance(value, bool):
                capabilities[name] = CapabilityFlag(name=name, available=value)
            elif isinstance(value, dict):
                capabilities[name] = CapabilityFlag(
                    name=name,
                    available=bool(value.get("available", False)),
                    reason=value.get("reason", ""),
                )

        # Auto-derive environment capabilities
        _auto_derive_capabilities(capabilities, env, policy)

        return cls(feature_flags=features, capability_flags=capabilities)


def _auto_derive_capabilities(
    capabilities: dict[str, CapabilityFlag],
    environment: dict[str, bool],
    policy: dict[str, Any],
) -> None:
    """Derive standard capability flags from environment and policy state."""
    if "strong_model" not in capabilities:
        capabilities["strong_model"] = CapabilityFlag(
            name="strong_model",
            available=environment.get("strong_model_configured", False),
            reason="Strong model route is configured." if environment.get("strong_model_configured") else "No strong model route.",
        )
    if "medium_model" not in capabilities:
        capabilities["medium_model"] = CapabilityFlag(
            name="medium_model",
            available=environment.get("medium_model_configured", False),
            reason="Medium model route is configured." if environment.get("medium_model_configured") else "No medium model route.",
        )
    if "plugin_execution" not in capabilities:
        hooks = policy.get("hooks", {})
        plugins_enabled = bool(hooks.get("plugins_enabled", False))
        capabilities["plugin_execution"] = CapabilityFlag(
            name="plugin_execution",
            available=plugins_enabled,
            reason="Plugin execution is enabled." if plugins_enabled else "Plugin execution is disabled.",
        )
    if "real_model" not in capabilities:
        has_real = environment.get("real_model_available", False)
        capabilities["real_model"] = CapabilityFlag(
            name="real_model",
            available=has_real,
            reason="Real model gate has passed." if has_real else "No real model gate record.",
        )
    if "provider_streaming" not in capabilities:
        has_streaming = environment.get("provider_streaming_available", False)
        capabilities["provider_streaming"] = CapabilityFlag(
            name="provider_streaming",
            available=has_streaming,
            reason=(
                "Strong and medium provider routes have streaming enabled."
                if has_streaming
                else "Provider streaming is not enabled for all required routes."
            ),
        )
