from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorTaxonomyEntry:
    error_type: str
    user_summary: str
    auto_recovery: str
    next_action: str
    release_gate: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "error_type": self.error_type,
            "user_summary": self.user_summary,
            "auto_recovery": self.auto_recovery,
            "next_action": self.next_action,
            "release_gate": self.release_gate,
        }


ERROR_TAXONOMY: dict[str, ErrorTaxonomyEntry] = {
    "configuration": ErrorTaxonomyEntry(
        error_type="configuration",
        user_summary="Runtime configuration is missing or inconsistent.",
        auto_recovery="Defaults may be migrated when the meaning is stable.",
        next_action="Run `asteria doctor --json` and fix the reported configuration keys.",
        release_gate=True,
    ),
    "provider": ErrorTaxonomyEntry(
        error_type="provider",
        user_summary="Model provider route or gate evidence is unavailable.",
        auto_recovery="Retry is allowed within deadline and budget limits.",
        next_action="Run `asteria model-check` or `asteria real-model-gate`.",
        release_gate=True,
    ),
    "schema": ErrorTaxonomyEntry(
        error_type="schema",
        user_summary="A persisted runtime object or package schema is missing or invalid.",
        auto_recovery="Run a registered migration when available; otherwise stop.",
        next_action="Run `asteria package-check --json` and inspect schema checks.",
        release_gate=True,
    ),
    "plugin": ErrorTaxonomyEntry(
        error_type="plugin",
        user_summary="Plugin manifest or hook policy is blocked or inconsistent.",
        auto_recovery="Plugin execution remains disabled unless policy explicitly allows it.",
        next_action="Run `asteria plugins doctor --json`.",
        release_gate=False,
    ),
    "candidate_workspace": ErrorTaxonomyEntry(
        error_type="candidate_workspace",
        user_summary="Candidate workspace backend or git state needs attention.",
        auto_recovery="Fallback to temp workspace when git worktree is unavailable.",
        next_action="Review git tracked state and candidate workspace diagnostics.",
        release_gate=False,
    ),
    "promotion": ErrorTaxonomyEntry(
        error_type="promotion",
        user_summary="Candidate promotion is unresolved or failed.",
        auto_recovery="Retry is allowed after merge gate and workspace checks.",
        next_action="Run `asteria promotions list` then approve, retry, reject, or discard.",
        release_gate=True,
    ),
    "internal": ErrorTaxonomyEntry(
        error_type="internal",
        user_summary="Unexpected runtime failure.",
        auto_recovery="Stop and preserve evidence.",
        next_action="Inspect logs and file a runtime repair task.",
        release_gate=True,
    ),
}


CHECK_ERROR_TYPES: dict[str, str] = {
    "agent_dir": "configuration",
    "root_guidance": "configuration",
    "runtime_config": "configuration",
    "plugins": "plugin",
    "git": "candidate_workspace",
    "real_model_gate": "provider",
    "pyproject": "configuration",
    "build_backend": "configuration",
    "console_script": "configuration",
    "version_sync": "configuration",
    "validation_command_modules": "configuration",
    "hook_plugin_control_surface": "plugin",
    "validation_route_template": "configuration",
    "validation_docs": "configuration",
    "validation_runbook": "configuration",
}


def classify_check(check_name: str) -> str:
    if check_name.startswith("model_"):
        return "provider"
    return CHECK_ERROR_TYPES.get(check_name, "internal")


def taxonomy_entry(error_type: str) -> dict[str, object]:
    entry = ERROR_TAXONOMY.get(error_type, ERROR_TAXONOMY["internal"])
    return entry.to_dict()


def taxonomy_summary() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "categories": sorted(ERROR_TAXONOMY),
    }
