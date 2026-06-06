from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class SwarmScenarioCheck:
    name: str
    ok: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "reason": self.reason}


@dataclass(frozen=True)
class SwarmScenarioAuditResult:
    ok: bool
    detected_paths: list[str] = field(default_factory=list)
    checks: list[SwarmScenarioCheck] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detected_paths": self.detected_paths,
            "summary": self.summary,
            "checks": [item.to_dict() for item in self.checks],
        }


class SwarmScenarioAuditor:
    """Audit a run_dir for Phase 5 harness scenario evidence (execute vs subagent paths)."""

    def __init__(self, validator: SchemaValidator) -> None:
        self.validator = validator
        self._store = JsonlStore(validator)

    def evaluate_run_dir(self, run_dir: Path) -> SwarmScenarioAuditResult:
        checks: list[SwarmScenarioCheck] = []
        detected: list[str] = []

        if self._evaluate_execute_parallel_disjoint(run_dir, checks):
            detected.append("execute_parallel_disjoint")
        if self._evaluate_subagent_swarm_planning(run_dir, checks):
            detected.append("subagent_swarm_planning")

        ok = bool(detected)
        summary = (
            f"Phase 5 scenario audit passed ({', '.join(detected)})."
            if ok
            else "Phase 5 scenario audit blocked: no recognized harness path in run_dir."
        )
        return SwarmScenarioAuditResult(ok=ok, detected_paths=detected, checks=checks, summary=summary)

    def _evaluate_execute_parallel_disjoint(self, run_dir: Path, checks: list[SwarmScenarioCheck]) -> bool:
        events = self._read_events(run_dir)
        has_parallel = any(
            event.get("type") == "task_graph_selection"
            and str((event.get("data") or {}).get("reason") or "") == "parallel_safe_batch_selection"
            for event in events
        )
        if not has_parallel:
            return False

        workers = self._read(run_dir, "worker_results.jsonl", "worker_result")
        experiments = self._read(run_dir, "experiments.jsonl", "experiment")
        graph_path = run_dir / "agent_run_graph.json"
        promoted = {
            path
            for item in experiments
            for path in ((item.get("candidate") or {}).get("promoted_files") or [])
            if path
        }
        ok = len(workers) >= 2 and len(promoted) >= 2 and graph_path.exists()
        checks.append(
            SwarmScenarioCheck(
                "execute_parallel_disjoint",
                ok,
                f"{len(workers)} worker result(s), {len(promoted)} promoted file(s), graph={graph_path.exists()}.",
            )
        )
        return ok

    def _evaluate_subagent_swarm_planning(self, run_dir: Path, checks: list[SwarmScenarioCheck]) -> bool:
        child_path = run_dir / "subagent_child_plans.jsonl"
        swarm_path = run_dir / "swarm_execution_plans.jsonl"
        if not child_path.exists() or not swarm_path.exists():
            return False

        child_plans = self._read(run_dir, "subagent_child_plans.jsonl", "subagent_child_plan")
        swarm_plans = self._read(run_dir, "swarm_execution_plans.jsonl", "swarm_execution_plan")
        linked = bool(
            swarm_plans
            and child_plans
            and str(swarm_plans[-1].get("subagent_child_plan_id") or "")
            == str(child_plans[-1].get("subagent_child_plan_id") or "")
        )
        ok = bool(child_plans) and bool(swarm_plans) and linked
        checks.append(
            SwarmScenarioCheck(
                "subagent_swarm_planning",
                ok,
                f"{len(child_plans)} child plan(s), {len(swarm_plans)} swarm plan(s), linked={linked}.",
            )
        )
        return ok

    def _read(self, run_dir: Path, name: str, schema: str) -> list[dict]:
        path = run_dir / name
        if not path.exists():
            return []
        return self._store.read_all(path, schema)

    def _read_events(self, run_dir: Path) -> list[dict]:
        path = run_dir / "events.jsonl"
        if not path.exists():
            return []
        return [item for item in self._read_raw_jsonl(path) if isinstance(item, dict)]

    def _read_raw_jsonl(self, path: Path) -> list[dict]:
        import json

        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
