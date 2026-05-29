from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable
from pathlib import Path

from asteria_runtime.core.runtime_profile import SCHEMA_VERSION
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class AgentRunGraphBuilder:
    validator: SchemaValidator

    def build(self, run_dir: Path, run_id: str | None = None) -> dict:
        jsonl = JsonlStore(self.validator)
        workers = jsonl.read_all(run_dir / "workers.jsonl", "worker_invocation")
        results = jsonl.read_all(run_dir / "worker_results.jsonl", "worker_result")
        events = jsonl.read_all(run_dir / "events.jsonl", "event")
        runtime_profiles = jsonl.read_all(run_dir / "runtime_profiles.jsonl", "runtime_profile")
        subagent_child_plans = jsonl.read_all(
            run_dir / "subagent_child_plans.jsonl", "subagent_child_plan"
        )
        model_profiles = jsonl.read_all(run_dir / "model_profiles.jsonl", "model_profile")
        tool_profiles = jsonl.read_all(
            run_dir / "tool_permission_profiles.jsonl", "tool_permission_profile"
        )
        task_plan = self._read_task_plan(run_dir)

        result_by_worker = {item["worker_invocation_id"]: item for item in results}
        runtime_by_id = {item["runtime_profile_id"]: item for item in runtime_profiles}
        model_by_id = {item["model_profile_id"]: item for item in model_profiles}
        tool_by_id = {item["tool_permission_profile_id"]: item for item in tool_profiles}
        task_by_id = {item["task_id"]: item for item in task_plan}
        coordination_by_task = self._coordination_by_task(events)
        child_plan_by_worker = {
            str(item.get("worker_invocation_id") or ""): item for item in subagent_child_plans
        }

        child_plans = [
            self._child_worker_plan(
                worker=worker,
                result=result_by_worker.get(worker["worker_invocation_id"]),
                runtime_profile=runtime_by_id.get(worker["runtime_profile_id"], {}),
                subagent_child_plan=child_plan_by_worker.get(worker["worker_invocation_id"], {}),
                model_profiles=model_by_id,
                tool_profiles=tool_by_id,
                task=task_by_id.get(worker["task_id"], {}),
                coordination_by_task=coordination_by_task,
            )
            for worker in workers
        ]
        summary = self._collaboration_summary(child_plans)
        graph = {
            "schema_version": SCHEMA_VERSION,
            "agent_run_graph_id": f"agent-run-graph-{run_id or self._run_id(workers)}",
            "run_id": run_id or self._run_id(workers),
            "status": self._status(child_plans),
            "coordination_modes": self._coordination_modes(events),
            "max_concurrency_observed": self._max_concurrency(events),
            "child_worker_plans": child_plans,
            "collaboration_summary": summary,
            "updated_at": now_iso(),
        }
        self.validator.validate("agent_run_graph", graph)
        return graph

    def write(self, run_dir: Path, run_id: str | None = None) -> dict:
        graph = self.build(run_dir, run_id=run_id)
        JsonStore(self.validator).write(run_dir / "agent_run_graph.json", graph, "agent_run_graph")
        return graph

    def _child_worker_plan(
        self,
        *,
        worker: dict,
        result: dict | None,
        runtime_profile: dict,
        subagent_child_plan: dict,
        model_profiles: dict[str, dict],
        tool_profiles: dict[str, dict],
        task: dict,
        coordination_by_task: dict[str, str],
    ) -> dict:
        model_profile = model_profiles.get(str(runtime_profile.get("model_profile_id")), {})
        tool_profile = tool_profiles.get(
            str(runtime_profile.get("tool_permission_profile_id")), {}
        )
        task_id = str(worker["task_id"])
        raw_strategy = task.get("multi_agent_strategy")
        strategy: dict = raw_strategy if isinstance(raw_strategy, dict) else {}
        result_status = (result or {}).get("status")
        return {
            "child_worker_plan_id": f"child-plan-{worker['worker_invocation_id']}",
            "worker_invocation_id": worker["worker_invocation_id"],
            "worker_result_id": (result or {}).get("worker_result_id"),
            "parent_worker_invocation_id": worker.get("parent_worker_invocation_id"),
            "subagent_child_plan_id": str(
                subagent_child_plan.get("subagent_child_plan_id") or ""
            ),
            "decomposition_strategy": str(
                subagent_child_plan.get("decomposition_strategy") or ""
            ),
            "scheduling_strategy": str(subagent_child_plan.get("scheduling_strategy") or ""),
            "planned_child_count": len(subagent_child_plan.get("child_tasks") or []),
            "planned_child_tasks": subagent_child_plan.get("child_tasks") or [],
            "task_id": task_id,
            "agent_id": worker["agent_id"],
            "status": worker["status"],
            "result_status": result_status,
            "runtime_profile_id": worker["runtime_profile_id"],
            "context_mount_id": str(runtime_profile.get("context_mount_id") or ""),
            "model_profile_id": str(runtime_profile.get("model_profile_id") or ""),
            "tool_permission_profile_id": str(
                runtime_profile.get("tool_permission_profile_id") or ""
            ),
            "model_tier": str(model_profile.get("model_tier") or "medium"),
            "budget": runtime_profile.get(
                "budget", {"max_model_calls": 1, "max_tool_calls": 1}
            ),
            "strategy_mode": str(strategy.get("mode") or ""),
            "strategy_max_child_workers": int(strategy.get("max_child_workers") or 1),
            "read_scope": [str(item) for item in tool_profile.get("read_scope", [])],
            "write_scope": [str(item) for item in tool_profile.get("write_scope", [])],
            "depends_on": [str(item) for item in task.get("depends_on", [])],
            "coordination_mode": coordination_by_task.get(task_id, "serial_ready_selection"),
            "collaboration_role": self._collaboration_role(task),
            "artifact_refs": (result or {}).get("artifact_refs", []),
            "validation_refs": (result or {}).get("validation_refs", []),
            "failure_evidence_refs": (result or {}).get("failure_evidence_refs", []),
            "cost": (result or {}).get("cost", {"model_calls": 0, "tool_calls": 0}),
            "summary": (result or {}).get("summary") or worker.get("summary") or "",
        }

    def _collaboration_role(self, task: dict) -> str:
        safety = str(task.get("parallel_safety") or "serial")
        kind = str(task.get("task_kind") or "implementation")
        if safety == "readonly":
            return "research_child"
        if safety == "disjoint_writes":
            return "implementation_child"
        if kind in {"review", "report"}:
            return "summary_child"
        return "serial_child"

    def _collaboration_summary(self, child_plans: list[dict]) -> dict:
        statuses = [str(plan.get("result_status") or plan.get("status")) for plan in child_plans]
        failure_refs = self._flatten(child_plans, "failure_evidence_refs")
        next_actions = []
        if failure_refs:
            next_actions.append("Debug failed child worker plans before widening concurrency.")
        if not child_plans:
            next_actions.append("Run execute to create child worker evidence.")
        strategy_modes = self._unique(
            str(plan.get("strategy_mode") or "") for plan in child_plans if plan.get("strategy_mode")
        )
        return {
            "total_workers": len(child_plans),
            "successful_workers": statuses.count("succeeded"),
            "failed_workers": len([status for status in statuses if status == "failed"]),
            "blocked_workers": len(
                [status for status in statuses if status in {"denied", "timeout", "partial"}]
            ),
            "total_model_calls": sum(
                int((plan.get("cost") or {}).get("model_calls", 0)) for plan in child_plans
            ),
            "total_tool_calls": sum(
                int((plan.get("cost") or {}).get("tool_calls", 0)) for plan in child_plans
            ),
            "artifact_refs": self._flatten(child_plans, "artifact_refs"),
            "validation_refs": self._flatten(child_plans, "validation_refs"),
            "failure_evidence_refs": failure_refs,
            "merge_strategy": "merge_gate_then_promotion_queue",
            "collaboration_protocol": {
                "isolation_model": "candidate_workspace_per_write_worker",
                "review_agent_role": "summarize_child_diffs_conflicts_and_release_risks",
                "debug_agent_role": "retry_or_replace_failed_child_worker_from_evidence",
                "merge_gate_role": "block_scope_conflicts_and_failed_validation_before_promotion",
                "promotion_queue_role": "centralize_manual_approval_retry_reject_or_discard",
            },
            "strategy_modes": strategy_modes,
            "next_actions": next_actions,
        }

    def _status(self, child_plans: list[dict]) -> str:
        if not child_plans:
            return "empty"
        statuses = {str(plan.get("result_status") or plan.get("status")) for plan in child_plans}
        if statuses == {"succeeded"}:
            return "succeeded"
        if statuses & {"failed", "denied", "timeout"}:
            return "blocked"
        if "running" in statuses:
            return "running"
        return "partial"

    def _coordination_by_task(self, events: list[dict]) -> dict[str, str]:
        mapping = {}
        for event in events:
            if event.get("type") != "task_graph_selection":
                continue
            data = event.get("data") or {}
            reason = str(data.get("reason") or "serial_ready_selection")
            for task_id in data.get("task_ids") or []:
                mapping[str(task_id)] = reason
        return mapping

    def _coordination_modes(self, events: list[dict]) -> list[str]:
        modes = []
        for reason in self._coordination_by_task(events).values():
            if reason not in modes:
                modes.append(reason)
        return modes

    def _max_concurrency(self, events: list[dict]) -> int:
        observed = [1]
        for event in events:
            if event.get("type") != "task_graph_selection":
                continue
            observed.append(len((event.get("data") or {}).get("task_ids") or []))
        return max(observed)

    def _read_task_plan(self, run_dir: Path) -> list[dict]:
        path = run_dir / "task_plan.json"
        if not path.exists():
            return []
        task_plan = JsonStore(self.validator).read(path, "task_board")
        return [item for item in task_plan.get("tasks", []) if isinstance(item, dict)]

    def _run_id(self, workers: list[dict]) -> str:
        if workers:
            return str(workers[0].get("run_id") or "")
        return ""

    def _flatten(self, child_plans: list[dict], key: str) -> list[str]:
        values = []
        for plan in child_plans:
            for item in plan.get(key, []):
                if str(item) not in values:
                    values.append(str(item))
        return values

    def _unique(self, values: Iterable[object]) -> list[str]:
        unique = []
        for value in values:
            if value and str(value) not in unique:
                unique.append(str(value))
        return unique
