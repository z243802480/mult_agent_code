from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from asteria_runtime.core.permission_policy import (
    decision_granularity_for,
    normalize_permission_mode,
    permission_overrides_for,
    permission_policy_profile,
)
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
    workspace_envelope: dict | None = None,
    execution_profile: dict | None = None,
    fast_path: dict | None = None,
) -> dict:
    permission_mode = normalize_permission_mode(permission_level)
    config = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "mode": mode,
        "permission_level": permission_level,
        "permission_mode": permission_mode,
        "model_strategy": model_strategy,
        "decision_granularity": decision_granularity_for(permission_level),
        "permission_overrides": permission_overrides_for(permission_level),
        "permission_policy": permission_policy_profile(permission_level),
        "model_routing_overrides": _model_routing_overrides(model_strategy),
        "model_strategy_profile": _model_strategy_profile(model_strategy),
        "workspace_envelope": workspace_envelope or {},
        "created_at": now_iso(),
    }
    if execution_profile:
        config["execution_profile"] = execution_profile
    if fast_path:
        config["fast_path"] = fast_path
    return config


def write_run_config(
    *,
    run_dir: Path,
    validator: SchemaValidator,
    run_id: str,
    mode: str,
    permission_level: str,
    model_strategy: str,
    workspace_envelope: dict | None = None,
    execution_profile: dict | None = None,
    fast_path: dict | None = None,
) -> dict:
    config = build_run_config(
        run_id=run_id,
        mode=mode,
        permission_level=permission_level,
        model_strategy=model_strategy,
        workspace_envelope=workspace_envelope,
        execution_profile=execution_profile,
        fast_path=fast_path,
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
    effective["permission_mode"] = run_config.get("permission_mode") or normalize_permission_mode(
        str(run_config.get("permission_level") or "balanced")
    )
    effective["permission_policy"] = run_config.get("permission_policy") or permission_policy_profile(
        str(run_config.get("permission_level") or "balanced")
    )
    effective["workspace_envelope"] = run_config.get("workspace_envelope") or {}
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
