"""Named access-restriction profiles.

This axis bundles *capability* permissions (shell execution, network egress, ...)
into a small named enum, the way Codex sandbox modes and Claude Code permission
modes do. It is deliberately distinct from two neighbouring concepts:

* ``core.execution_profile`` -> session_agent vs harness *run path* selection.
* ``permission_mode`` (ask / reviewed_auto / auto) -> *when* to prompt the user.

An access profile answers a third question: *what capabilities are on at all*.
The canonical use case is pinning a shared or external Beta deployment to a
"no shell / no network" posture without editing every command invocation.

The profile definitions live here in code so a workspace only needs the single
``active_access_profile`` switch in ``policies.json`` to opt in; the resolver in
``core.policy_config`` overlays the profile's permissions at load time, so every
command sees the restricted permissions with no changes to the run/execute path.
"""

from __future__ import annotations

from typing import Any

# Canonical, code-owned profiles. Users may add or override entries via an
# ``access_profiles`` object in policies.json (custom of the same name wins).
BUILTIN_ACCESS_PROFILES: dict[str, dict[str, Any]] = {
    "beta_safe": {
        "description": (
            "Beta-safe restricted access: shell execution and network egress are "
            "disabled by policy for shared or external Beta deployments. File edits "
            "inside the workspace still work; escalate by clearing the profile."
        ),
        "permissions": {
            "allow_network": False,
            "allow_shell": False,
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_secret_file_read": False,
            "allow_remote_push": False,
            "allow_deploy": False,
        },
    },
}


def available_access_profiles(policy: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return builtin profiles merged with any workspace-defined ones (custom wins)."""
    merged: dict[str, dict[str, Any]] = {
        name: dict(spec) for name, spec in BUILTIN_ACCESS_PROFILES.items()
    }
    custom = (policy or {}).get("access_profiles")
    if isinstance(custom, dict):
        for name, spec in custom.items():
            if isinstance(spec, dict):
                merged[str(name)] = spec
    return merged


def apply_access_profile(policy: dict[str, Any]) -> dict[str, Any]:
    """Overlay the active access profile's permissions onto ``policy`` in place.

    No-op when ``active_access_profile`` is unset/null or names an unknown profile,
    so the default posture is byte-identical to pre-profile behaviour.
    """
    name = policy.get("active_access_profile")
    if not name:
        return policy
    profile = available_access_profiles(policy).get(str(name))
    if not isinstance(profile, dict):
        return policy
    overrides = profile.get("permissions")
    if isinstance(overrides, dict):
        permissions = policy.setdefault("permissions", {})
        if isinstance(permissions, dict):
            for key, value in overrides.items():
                permissions[key] = bool(value)
    return policy


def access_profile_summary(policy: dict[str, Any]) -> dict[str, Any]:
    """Operator-facing snapshot: which profile is active and the resulting gates.

    Call on an already-resolved policy (post ``apply_access_profile``) so the
    shell/network flags reflect the effective posture, letting a Beta operator
    verify the deployment is actually locked down.
    """
    name = policy.get("active_access_profile")
    permissions = policy.get("permissions") if isinstance(policy.get("permissions"), dict) else {}
    return {
        "active": str(name) if name else None,
        "available": sorted(available_access_profiles(policy).keys()),
        "shell_enabled": bool(permissions.get("allow_shell", False)),
        "network_enabled": bool(permissions.get("allow_network", False)),
    }
