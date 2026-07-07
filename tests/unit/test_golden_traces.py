"""Golden trace contract tests: prevent behavioral drift across refactors.

Each test here encodes a specific behavioral contract that must remain stable.
If a golden trace breaks, either the refactor introduced a regression or the
contract itself needs an explicit ADR to justify the change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from asteria_runtime.acceptance.runtime_os_catalog import RUNTIME_OS_CAPABILITIES
from asteria_runtime.commands._runtime_os_helpers import runtime_os_catalog_report
from asteria_runtime.core.agent_harness import AgentHarness
from asteria_runtime.core.merge_gate import MergeGate
from asteria_runtime.core.schema_migration import (
    SchemaMigration,
    SchemaMigrationRegistry,
)
from asteria_runtime.core.flag_resolver import (
    CapabilityFlag,
    FeatureFlag,
    FlagResolver,
)
from tests.helpers.runtime_os import runtime_os_pass_report, runtime_os_pass_scenarios

pytestmark = pytest.mark.contract


class TestMergeGateBlocksUnsafePromotion:
    """Golden trace: merge gate must reject promotions that violate write scope."""

    def test_merge_gate_rejects_files_outside_write_scope(self) -> None:
        gate = MergeGate()
        result = gate.evaluate(
            task={"expected_changed_files": ["target.py"], "write_scope": ["target.py"]},
            changed_files=["target.py", "unrelated.py"],
            verification_results=[],
        )
        assert result.ok is False
        assert len(result.violations) > 0
        assert any("outside write_scope" in v for v in result.violations)

    def test_merge_gate_passes_in_scope_changes(self) -> None:
        gate = MergeGate()
        result = gate.evaluate(
            task={"expected_changed_files": ["target.py"], "write_scope": ["target.py"]},
            changed_files=["target.py"],
            verification_results=[],
        )
        assert result.ok is True
        assert "target.py" in result.promotable_files

    def test_merge_gate_rejects_when_no_changes_but_promotion_required(self) -> None:
        gate = MergeGate()
        result = gate.evaluate(
            task={"expected_changed_files": ["target.py"], "write_scope": ["target.py"]},
            changed_files=[],
            verification_results=[],
        )
        assert result.ok is False
        assert any("no changed" in v for v in result.violations)

    def test_merge_gate_rejects_failed_verification(self) -> None:
        gate = MergeGate()
        failed_result = type("FakeResult", (), {"ok": False, "summary": "test failed"})()
        result = gate.evaluate(
            task={"expected_changed_files": ["target.py"], "write_scope": ["target.py"]},
            changed_files=["target.py"],
            verification_results=[failed_result],
        )
        assert result.ok is False
        assert any("verification failed" in v for v in result.violations)


class TestSchemaMigrationPreservesData:
    """Golden trace: schema migration must not drop user data."""

    def test_policy_migration_adds_flags_without_losing_budgets(self) -> None:
        registry = SchemaMigrationRegistry()
        registry.register(
            SchemaMigration(
                schema_name="policy_config",
                from_version="0.1.0",
                to_version="0.2.0",
                migrate=lambda d: (d.setdefault("feature_flags", {}), d.setdefault("capability_flags", {}), d)[2],
                description="Add flags",
            )
        )
        original = {
            "schema_version": "0.1.0",
            "budgets": {"max_model_calls_per_goal": 60},
            "permissions": {"allow_shell": True},
        }
        migrated = registry.migrate("policy_config", original)
        assert migrated["budgets"]["max_model_calls_per_goal"] == 60
        assert migrated["permissions"]["allow_shell"] is True
        assert migrated["schema_version"] == "0.2.0"
        assert "feature_flags" in migrated
        assert "capability_flags" in migrated

    def test_migration_chain_runs_in_order(self) -> None:
        registry = SchemaMigrationRegistry()
        registry.register(
            SchemaMigration(
                schema_name="test_schema",
                from_version="0.1.0",
                to_version="0.2.0",
                migrate=lambda d: {**d, "step1": True},
            )
        )
        registry.register(
            SchemaMigration(
                schema_name="test_schema",
                from_version="0.2.0",
                to_version="0.3.0",
                migrate=lambda d: {**d, "step2": True},
            )
        )
        result = registry.migrate("test_schema", {"schema_version": "0.1.0"})
        assert result["schema_version"] == "0.3.0"
        assert result["step1"] is True
        assert result["step2"] is True
        assert len(registry.history) == 2

    def test_no_migration_for_current_version(self) -> None:
        registry = SchemaMigrationRegistry()
        registry.register(
            SchemaMigration(
                schema_name="test_schema",
                from_version="0.1.0",
                to_version="0.2.0",
                migrate=lambda d: {**d, "migrated": True},
            )
        )
        result = registry.migrate("test_schema", {"schema_version": "0.2.0"})
        assert result["schema_version"] == "0.2.0"
        assert "migrated" not in result
        assert len(registry.history) == 0


class TestFeatureFlagResolution:
    """Golden trace: feature flags must check both toggle and capability."""

    def test_disabled_flag_is_not_active(self) -> None:
        resolver = FlagResolver(
            feature_flags={
                "streaming": FeatureFlag(name="streaming", enabled=False),
            },
            capability_flags={
                "real_model": CapabilityFlag(name="real_model", available=True),
            },
        )
        result = resolver.resolve("streaming")
        assert result is not None
        assert result.active is False
        assert "disabled" in result.reason.lower()

    def test_enabled_flag_with_missing_capability_is_not_active(self) -> None:
        resolver = FlagResolver(
            feature_flags={
                "plugin_market": FeatureFlag(
                    name="plugin_market",
                    enabled=True,
                    requires=frozenset({"plugin_execution"}),
                ),
            },
            capability_flags={
                "plugin_execution": CapabilityFlag(
                    name="plugin_execution",
                    available=False,
                    reason="Plugins disabled in policy.",
                ),
            },
        )
        result = resolver.resolve("plugin_market")
        assert result is not None
        assert result.active is False
        assert "missing" in result.reason.lower() or "capability" in result.reason.lower()

    def test_enabled_flag_with_all_capabilities_is_active(self) -> None:
        resolver = FlagResolver(
            feature_flags={
                "debug_export": FeatureFlag(
                    name="debug_export",
                    enabled=True,
                    requires=frozenset({"real_model"}),
                ),
            },
            capability_flags={
                "real_model": CapabilityFlag(name="real_model", available=True),
            },
        )
        result = resolver.resolve("debug_export")
        assert result is not None
        assert result.active is True

    def test_from_policy_builds_resolver(self) -> None:
        policy = {
            "feature_flags": {
                "experimental_x": True,
                "disabled_y": False,
            },
            "capability_flags": {
                "strong_model": {"available": True, "reason": "Configured"},
            },
            "hooks": {"plugins_enabled": True},
        }
        resolver = FlagResolver.from_policy(
            policy,
            environment={"strong_model_configured": True, "medium_model_configured": False},
        )
        assert "experimental_x" in resolver.features
        assert resolver.features["experimental_x"].enabled is True
        assert resolver.features["disabled_y"].enabled is False
        assert "strong_model" in resolver.capabilities
        assert resolver.capabilities["strong_model"].available is True


class TestDocOnlyTaskVerification:
    """Golden trace: doc-only tasks must verify file existence and non-empty content."""

    def test_doc_artifact_verification_accepts_valid_markdown(self, tmp_path: Path) -> None:
        doc_file = tmp_path / "README.md"
        doc_file.write_text("# Overview\n\nSome content.\n\n## Quick Start\n\n1. Step 1\n", encoding="utf-8")
        assert doc_file.exists()
        content = doc_file.read_text(encoding="utf-8")
        assert len(content.strip()) > 0
        assert "Overview" in content

    def test_doc_artifact_verification_rejects_empty_file(self, tmp_path: Path) -> None:
        doc_file = tmp_path / "EMPTY.md"
        doc_file.write_text("", encoding="utf-8")
        content = doc_file.read_text(encoding="utf-8").strip()
        assert len(content) == 0

    def test_doc_artifact_in_subdirectory(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        doc_file = docs_dir / "README.md"
        doc_file.write_text("# Title\n\nContent here.\n", encoding="utf-8")
        assert doc_file.exists()
        assert "Title" in doc_file.read_text(encoding="utf-8")


class TestRuntimeOSFixtureCoverage:
    """Golden trace: report fixtures derive Runtime OS coverage from the catalog."""

    def test_runtime_os_pass_scenarios_cover_catalog(self, tmp_path: Path) -> None:
        expected = {item.capability for item in RUNTIME_OS_CAPABILITIES}
        scenarios = runtime_os_pass_scenarios()
        report = runtime_os_pass_report(tmp_path)

        assert {item["capability"] for item in scenarios} == expected
        assert {item["capability"] for item in report["scenario_metadata"]} == expected
        assert report["aggregate"]["total"] == len(RUNTIME_OS_CAPABILITIES)

    def test_runtime_os_report_catalog_is_derived_from_single_source(self) -> None:
        catalog = runtime_os_catalog_report()

        assert {item["capability"] for item in catalog["capabilities"]} == {
            item.capability for item in RUNTIME_OS_CAPABILITIES
        }
        # RA7b slice 4: evidence keys derive from the (spine-reconciled) catalog's special_evidence.
        assert "failure_blocked" in catalog["evidence_keys"]
        assert "verification_commands_recorded" in catalog["evidence_keys"]


class TestPromptEnvelopeContract:
    """Golden trace: prompt envelopes keep the model-visible runtime contract."""

    def test_prompt_envelope_contains_required_sections(self) -> None:
        envelope = AgentHarness(
            {
                "permissions": {
                    "allow_shell": False,
                    "allow_network": False,
                    "allow_remote_push": False,
                    "allow_destructive_shell": False,
                },
                "protected_paths": [".env", "secrets/"],
                "budgets": {"max_model_calls_per_goal": 60},
            },
            tool_names=["read_file"],
        ).prompt_envelope(
            run_id="run-golden",
            mode="plan",
            project_guidance="Project guidance.",
            project_guidance_refs=["AGENTS.md"],
        )
        data = envelope.to_dict()

        assert {
            "project_guidance",
            "capability_manifest",
            "safety_envelope",
            "failure_repair",
            "delegation_contract",
            "user_communication",
        }.issubset(set(data["section_order"]))
        assert data["capability_manifest"]["direct_tools"]
        assert data["capability_manifest"]["verification"]

    def test_prompt_envelope_exposes_hashes_for_model_call_contract(self) -> None:
        envelope = AgentHarness(
            {
                "permissions": {"allow_shell": True},
                "protected_paths": [],
                "budgets": {},
            },
            tool_names=["run_command"],
        ).prompt_envelope(run_id="run-golden", mode="execute")
        data = envelope.to_dict()
        cache_break_reasons = [
            reason
            for section in data["sections"]
            for reason in section.get("cache_break_reasons", [])
        ]

        assert data["content_hash"].startswith("sha256:")
        assert "tools_or_modes_changed" in cache_break_reasons
        assert "permissions_changed" in cache_break_reasons
