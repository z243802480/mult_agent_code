from __future__ import annotations

from pathlib import Path

from asteria_runtime.commands.init_command import InitCommand
from asteria_runtime.commands.orchestration_run_command import OrchestrationRunCommand
from asteria_runtime.core.orchestration_parallel_gray import (
    set_isolated_parallel_write_production_path,
    set_orchestration_dynamic_live_execution_gray,
    set_orchestration_dynamic_workflows_gray,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


def test_orchestration_run_dry_manifest(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    manifest = Path.cwd() / "benchmarks" / "orchestration_s72_ingress_manifest.json"
    result = OrchestrationRunCommand(
        root=tmp_path,
        manifest_path=manifest,
        dry_run=True,
        resume=False,
    ).run()
    assert result.ok is True
    assert result.workflow_id == "s72-ingress-probe"
    assert result.monitor is not None
    assert result.monitor.get("verifier_status") == "passed"


def test_orchestration_run_live_requires_gray(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    manifest = Path.cwd() / "benchmarks" / "orchestration_s72_ingress_manifest.json"
    result = OrchestrationRunCommand(
        root=tmp_path,
        manifest_path=manifest,
        dry_run=False,
    ).run()
    assert result.ok is False
    assert result.error == "dynamic_workflows_gray_disabled"


def test_orchestration_run_live_with_gray(tmp_path: Path) -> None:
    InitCommand(tmp_path).run()
    validator = SchemaValidator(Path.cwd() / "schemas")
    agent_dir = tmp_path / ".asteria"
    set_isolated_parallel_write_production_path(agent_dir=agent_dir, validator=validator, enabled=True)
    set_orchestration_dynamic_workflows_gray(agent_dir=agent_dir, validator=validator, enabled=True)
    set_orchestration_dynamic_live_execution_gray(agent_dir=agent_dir, validator=validator, enabled=True)
    manifest = Path.cwd() / "benchmarks" / "orchestration_s72_ingress_manifest.json"
    result = OrchestrationRunCommand(
        root=tmp_path,
        manifest_path=manifest,
        dry_run=False,
        resume=False,
    ).run()
    assert result.ok is True
    assert (Path(result.run_dir) / "workers.jsonl").exists()
