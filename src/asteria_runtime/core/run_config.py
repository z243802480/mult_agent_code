from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


SCHEMA_VERSION = "0.1.0"


def build_run_config(
    *,
    run_id: str,
    mode: str,
    permission_level: str,
    model_strategy: str,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "mode": mode,
        "permission_level": permission_level,
        "model_strategy": model_strategy,
        "decision_granularity": _decision_granularity(permission_level),
        "permission_overrides": _permission_overrides(permission_level),
        "model_routing_overrides": _model_routing_overrides(model_strategy),
        "model_strategy_profile": _model_strategy_profile(model_strategy),
        "created_at": now_iso(),
    }


def write_run_config(
    *,
    run_dir: Path,
    validator: SchemaValidator,
    run_id: str,
    mode: str,
    permission_level: str,
    model_strategy: str,
) -> dict:
    config = build_run_config(
        run_id=run_id,
        mode=mode,
        permission_level=permission_level,
        model_strategy=model_strategy,
    )
    JsonStore(validator).write(run_dir / "run_config.json", config, "run_config")
    return config


def load_run_config(run_dir: Path, validator: SchemaValidator) -> dict | None:
    path = run_dir / "run_config.json"
    if not path.exists():
        return None
    return JsonStore(validator).read(path, "run_config")


def apply_run_config(policy: dict, run_config: dict | None) -> dict:
    if not run_config:
        return policy
    effective = deepcopy(policy)
    effective["decision_granularity"] = run_config["decision_granularity"]
    effective_permissions = effective.setdefault("permissions", {})
    effective_permissions.update(run_config.get("permission_overrides") or {})
    effective_model_routing = effective.setdefault("model_routing", {})
    effective_model_routing.update(run_config.get("model_routing_overrides") or {})
    effective["model_strategy_profile"] = run_config.get(
        "model_strategy_profile"
    ) or _model_strategy_profile(str(run_config.get("model_strategy") or "auto"))
    effective["run_config"] = run_config
    return effective


def effective_policy_for_run(
    *,
    policy: dict,
    run_dir: Path,
    validator: SchemaValidator,
) -> dict:
    return apply_run_config(policy, load_run_config(run_dir, validator))


def _decision_granularity(permission_level: str) -> str:
    return {
        "ask": "manual",
        "balanced": "balanced",
        "auto": "autopilot",
    }[permission_level]


def _permission_overrides(permission_level: str) -> dict:
    if permission_level == "ask":
        return {
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_secret_file_read": False,
            "allow_remote_push": False,
            "allow_deploy": False,
        }
    if permission_level == "auto":
        return {
            "allow_destructive_shell": False,
            "allow_global_package_install": False,
            "allow_secret_file_read": False,
            "allow_deploy": False,
        }
    return {}


def _model_routing_overrides(model_strategy: str) -> dict:
    # User-facing strategies are policy biases, not a fixed purpose->tier route table.
    # Explicit project/user overrides may be added here later, but the default path
    # should let RuntimeProfileBuilder combine task kind, risk, capability feedback,
    # and budget instead of clobbering all model routes at run creation time.
    _ = model_strategy
    return {}


def _model_strategy_profile(model_strategy: str) -> dict:
    if model_strategy == "quality":
        return {
            "strategy": "quality",
            "selection_policy": "prefer_capability_fit_with_budget",
            "bias": "escalate_high_risk_or_complex_tasks",
            "tier_preference": ["strong", "medium", "cheap"],
            "allow_downgrade": False,
            "notes": "Do not force every route to strong; upgrade only when task shape or risk needs it.",
        }
    if model_strategy == "economy":
        return {
            "strategy": "economy",
            "selection_policy": "prefer_low_cost_with_safety_escalation",
            "bias": "downgrade_low_risk_tasks",
            "tier_preference": ["cheap", "medium", "strong"],
            "allow_escalation": True,
            "notes": "Use cheaper routes for low-risk work, but keep high-risk/review/architecture eligible for stronger routes.",
        }
    if model_strategy == "local":
        return {
            "strategy": "local",
            "selection_policy": "prefer_configured_local_route_with_fallback",
            "bias": "prefer_local_when_available",
            "tier_preference": ["medium", "cheap", "strong"],
            "requires_configured_local_route": True,
            "notes": "Current model_profile schema only supports cheap/medium/strong; local is a preference until provider routes are configured.",
        }
    return {
        "strategy": "auto",
        "selection_policy": "task_default_with_capability_feedback",
        "bias": "balanced",
        "tier_preference": [],
        "notes": "Let task kind, explicit hints, policy defaults, capability feedback, and budget choose the route.",
    }
