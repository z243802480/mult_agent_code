from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AcceptanceScenarioInfo:
    scenario: str
    capability: str
    tier: str
    kind: str = "run"

    def to_dict(self) -> dict[str, str]:
        return {
            "scenario": self.scenario,
            "capability": self.capability,
            "tier": self.tier,
            "kind": self.kind,
        }


KNOWN_ACCEPTANCE_SCENARIOS: dict[str, AcceptanceScenarioInfo] = {
    "file_smoke": AcceptanceScenarioInfo("file_smoke", "artifact_creation", "smoke"),
    "password_cli": AcceptanceScenarioInfo("password_cli", "single_file_cli", "core"),
    "markdown_kb": AcceptanceScenarioInfo("markdown_kb", "search_cli", "core"),
    "offline_artifact": AcceptanceScenarioInfo("offline_artifact", "offline_artifact", "offline"),
    "failing_tests_repair": AcceptanceScenarioInfo(
        "failing_tests_repair", "test_driven_repair", "advanced"
    ),
    "safe_file_renamer": AcceptanceScenarioInfo(
        "safe_file_renamer", "config_driven_cli", "core"
    ),
    "multi_file_todo_cli": AcceptanceScenarioInfo(
        "multi_file_todo_cli", "multi_file_change", "core"
    ),
    "config_driven_report": AcceptanceScenarioInfo(
        "config_driven_report", "configuration_change", "core"
    ),
    "docs_code_sync": AcceptanceScenarioInfo("docs_code_sync", "docs_code_sync", "advanced"),
    "refactor_existing_module": AcceptanceScenarioInfo(
        "refactor_existing_module", "safe_refactor", "advanced"
    ),
    "memory_lesson_reuse": AcceptanceScenarioInfo(
        "memory_lesson_reuse", "memory_effectiveness", "advanced", "memory"
    ),
    "decision_point": AcceptanceScenarioInfo(
        "decision_point", "decision_memory", "advanced", "decision"
    ),
}


def acceptance_metadata_index(report: dict[str, Any]) -> dict[str, dict[str, str]]:
    index = {
        name: info.to_dict()
        for name, info in KNOWN_ACCEPTANCE_SCENARIOS.items()
    }
    for item in report.get("scenario_metadata", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("scenario") or "")
        if not name:
            continue
        existing = index.get(name, {"scenario": name})
        capability = item.get("capability")
        tier = item.get("tier")
        kind = item.get("kind")
        capability_is_unknown = not capability or capability == "unknown"
        index[name] = {
            "scenario": name,
            "capability": str(
                capability
                if not capability_is_unknown
                else existing.get("capability") or "unknown"
            ),
            "tier": str(
                tier
                if tier and tier != "unknown" and not capability_is_unknown
                else existing.get("tier") or "unknown"
            ),
            "kind": str(
                kind
                if kind and kind != "unknown" and not capability_is_unknown
                else existing.get("kind") or "run"
            ),
        }
    return index


def enrich_acceptance_scenario(
    scenario: dict[str, Any],
    metadata: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    name = str(scenario.get("scenario") or "unknown")
    item = (metadata or {}).get(name) or KNOWN_ACCEPTANCE_SCENARIOS.get(name)
    item_dict = item.to_dict() if isinstance(item, AcceptanceScenarioInfo) else item or {}
    enriched = dict(scenario)
    enriched["scenario"] = name
    enriched["capability"] = scenario.get("capability") or item_dict.get("capability")
    enriched["tier"] = scenario.get("tier") or item_dict.get("tier")
    return enriched


def enrich_acceptance_report(report: dict[str, Any]) -> dict[str, Any]:
    metadata = acceptance_metadata_index(report)
    enriched = dict(report)
    enriched["scenarios"] = [
        enrich_acceptance_scenario(item, metadata)
        for item in report.get("scenarios", [])
        if isinstance(item, dict)
    ]
    known_metadata = []
    seen = set()
    for item in enriched["scenarios"]:
        name = str(item.get("scenario") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        meta = metadata.get(name, {})
        if meta:
            known_metadata.append(meta)
    if known_metadata and not enriched.get("scenario_metadata"):
        enriched["scenario_metadata"] = known_metadata
    return enriched
