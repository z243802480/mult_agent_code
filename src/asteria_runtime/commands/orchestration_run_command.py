from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.orchestration_dynamic_runner import (
    run_dynamic_orchestration,
)
from asteria_runtime.core.orchestration_workflow_monitor import build_workflow_monitor_projection
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.swarm_flag_rollout import with_maintainer_probe_policy
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class OrchestrationRunResult:
    ok: bool
    run_id: str
    run_dir: str
    workflow_id: str
    dry_run: bool
    summary: str
    monitor: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "workflow_id": self.workflow_id,
            "dry_run": self.dry_run,
            "summary": self.summary,
            "monitor": self.monitor,
            "error": self.error,
        }

    def to_text(self) -> str:
        status = "ok" if self.ok else "failed"
        lines = [
            f"Orchestration run {status}: {self.workflow_id}",
            f"Run id: {self.run_id}",
            f"Mode: {'dry-run' if self.dry_run else 'live'}",
            self.summary,
        ]
        if self.error:
            lines.append(f"Error: {self.error}")
        if self.monitor:
            lines.append(
                "Monitor: "
                f"steps={self.monitor.get('completed_steps')}/{self.monitor.get('step_count')} "
                f"merge={self.monitor.get('merge_status')} "
                f"verifier={self.monitor.get('verifier_status')}"
            )
        return "\n".join(lines)


class OrchestrationRunCommand:
    """Run L3 dynamic orchestration manifest (S72 maintainer band)."""

    def __init__(
        self,
        root: Path,
        *,
        manifest_path: Path,
        dry_run: bool = True,
        resume: bool = True,
        run_id: str | None = None,
        policy: dict[str, Any] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.manifest_path = manifest_path.resolve()
        self.dry_run = dry_run
        self.resume = resume
        self.run_id = run_id
        self.policy = policy
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> OrchestrationRunResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            return OrchestrationRunResult(
                ok=False,
                run_id="",
                run_dir="",
                workflow_id="",
                dry_run=self.dry_run,
                summary="Workspace is not initialized.",
                error="missing .asteria",
            )
        if not self.manifest_path.exists():
            return OrchestrationRunResult(
                ok=False,
                run_id="",
                run_dir="",
                workflow_id="",
                dry_run=self.dry_run,
                summary="Manifest file not found.",
                error=str(self.manifest_path),
            )

        policy = self.policy or load_policy_config(agent_dir, self.validator)
        agent_loop = policy.get("agent_loop") if isinstance(policy.get("agent_loop"), dict) else {}
        if not self.dry_run:
            if not bool(agent_loop.get("orchestration_dynamic_workflows_gray")):
                return OrchestrationRunResult(
                    ok=False,
                    run_id="",
                    run_dir="",
                    workflow_id="",
                    dry_run=False,
                    summary="Live orchestration requires orchestration_dynamic_workflows_gray.",
                    error="dynamic_workflows_gray_disabled",
                )
            if not bool(agent_loop.get("orchestration_dynamic_live_execution_gray")):
                return OrchestrationRunResult(
                    ok=False,
                    run_id="",
                    run_dir="",
                    workflow_id="",
                    dry_run=False,
                    summary="Live orchestration requires orchestration_dynamic_live_execution_gray.",
                    error="live_execution_gray_disabled",
                )

        effective_run_id = self.run_id or f"run-l3-{now_iso().replace(':', '').replace('+', '')[:15]}"
        run_dir = agent_dir / "runs" / effective_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        effective_policy = with_maintainer_probe_policy(policy) if not self.dry_run else policy

        result = run_dynamic_orchestration(
            manifest_path=self.manifest_path,
            run_dir=run_dir,
            policy=effective_policy,
            dry_run=self.dry_run,
            resume=self.resume,
            root=self.root,
            validator=self.validator,
            run_id=effective_run_id,
        )
        monitor = build_workflow_monitor_projection(run_dir, workflow_id=result.manifest_footprint.get("workflow_id"))
        return OrchestrationRunResult(
            ok=result.ok,
            run_id=effective_run_id,
            run_dir=str(run_dir),
            workflow_id=str(result.manifest_footprint.get("workflow_id") or "unknown"),
            dry_run=self.dry_run,
            summary=result.summary,
            monitor=monitor,
            error=None if result.ok else result.summary,
        )
