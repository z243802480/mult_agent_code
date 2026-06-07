from __future__ import annotations

from asteria_runtime.core.orchestration_spawn_policy import (
    SPAWN_DECISION_POLICY,
    catalog_selection_guidance,
    subagent_manifest_extras,
)


def test_spawn_decision_policy_principles() -> None:
    text = " ".join(SPAWN_DECISION_POLICY.principles).lower()
    assert "strong" in text
    assert "keyword" in text or "never spawn" in " ".join(
        SPAWN_DECISION_POLICY.subagent_when_not_to_use
    ).lower()


def test_catalog_guidance_includes_loop_subagent_boundary() -> None:
    guidance = " ".join(catalog_selection_guidance()).lower()
    assert "agentloop" in guidance or "subagent" in guidance
    assert "keyword" in guidance or "file count" in guidance


def test_subagent_manifest_extras_non_empty() -> None:
    extras = subagent_manifest_extras()
    assert len(extras["when_to_use"]) >= 2
    assert len(extras["when_not_to_use"]) >= 2
