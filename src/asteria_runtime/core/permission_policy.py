from __future__ import annotations

from typing import Any


PERMISSION_MODE_ALIASES = {
    "ask": "ask_everything",
    "ask_everything": "ask_everything",
    "balanced": "reviewed_auto",
    "reviewed_auto": "reviewed_auto",
    "auto": "auto",
}


def normalize_permission_mode(permission_level: str) -> str:
    try:
        return PERMISSION_MODE_ALIASES[permission_level]
    except KeyError as exc:
        allowed = ", ".join(sorted(PERMISSION_MODE_ALIASES))
        raise ValueError(f"Unknown permission level {permission_level!r}; expected one of {allowed}") from exc


def autonomy_rings_default_on(permission_level: str | None) -> bool:
    """Set-and-forget default: bind the autonomy rings (auto_repair / auto_replan /
    auto_replan_goal) to the permission mode so "pick a mode and let it develop" is real.

    - ``auto`` / ``reviewed_auto`` → rings default ON: a task failure self-repairs / re-plans
      within the existing bounded fuses (repair/replan budgets, recovery-cycle limit, lineage cap,
      budget hard-stop) instead of stopping the run to ask the human to type ``resume``. High-risk
      shell / deploy / push still pause under the always-on hard guards — the rings govern *failure
      recovery*, not permission. (User-authorized default flip, 2026-07-13.)
    - ``ask_everything`` → rings default OFF: keep the explicit step-by-step supervised behaviour.
    - unknown / missing mode → treat as ``reviewed_auto`` (the run default) → ON.

    An explicit ``agent_loop.<ring>`` flag in policy still overrides this default (byte-reversible).
    """
    if permission_level is None:
        return True
    try:
        mode = normalize_permission_mode(str(permission_level))
    except ValueError:
        return True
    return mode != "ask_everything"


def decision_granularity_for(permission_level: str) -> str:
    return {
        "ask_everything": "manual",
        "reviewed_auto": "balanced",
        "auto": "autopilot",
    }[normalize_permission_mode(permission_level)]


def permission_overrides_for(permission_level: str) -> dict[str, bool]:
    mode = normalize_permission_mode(permission_level)
    hard_guards = {
        "allow_destructive_shell": False,
        "allow_global_package_install": False,
        "allow_secret_file_read": False,
        "allow_remote_push": False,
        "allow_deploy": False,
    }
    if mode in {"ask_everything", "auto"}:
        return hard_guards
    return {}


def permission_policy_profile(permission_level: str) -> dict[str, Any]:
    mode = normalize_permission_mode(permission_level)
    if mode == "ask_everything":
        return {
            "mode": mode,
            "default_action": "ask",
            "auto_allow_low_risk": False,
            "ask_options": [
                "allow_once",
                "deny",
                "switch_to_plan",
            ],
            "hard_guards": _hard_guards(),
        }
    if mode == "auto":
        return {
            "mode": mode,
            "default_action": "auto_advance",
            "auto_allow_low_risk": True,
            "ask_options": [],
            "hard_guards": _hard_guards(),
            "notes": "Autopilot controls the loop, but runtime hard guards remain active.",
        }
    return {
        "mode": mode,
        "default_action": "review_low_risk_then_ask",
        "auto_allow_low_risk": True,
        "ask_options": [
            "allow_once",
            "deny",
            "switch_to_plan",
        ],
        "hard_guards": _hard_guards(),
    }


def _hard_guards() -> list[str]:
    return [
        "protected_paths",
        "secrets",
        "destructive_shell",
        "global_package_install",
        "remote_push",
        "production_deploy",
        "budget_hard_stop",
        "workspace_boundary",
        "irreversible_delete",
    ]
