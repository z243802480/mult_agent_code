from __future__ import annotations

import json
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
        promotions = self._latest_promotions(
            jsonl.read_all(run_dir / "candidate_promotions.jsonl", "candidate_promotion")
        )
        task_execution = jsonl.read_all(
            run_dir / "task_execution_evidence.jsonl", "task_execution_evidence"
        )
        model_profiles = jsonl.read_all(run_dir / "model_profiles.jsonl", "model_profile")
        tool_profiles = jsonl.read_all(
            run_dir / "tool_permission_profiles.jsonl", "tool_permission_profile"
        )
        task_plan = self._read_task_plan(run_dir)
        candidate_workspaces = self._candidate_workspaces(run_dir, promotions)
        promotion_queue = self._promotion_queue(promotions)
        merge_gate_summary = self._merge_gate_summary(promotions, task_execution)
        promotion_recovery_summary = self._promotion_recovery_summary(
            promotion_queue,
            candidate_workspaces,
        )

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
        summary = self._collaboration_summary(
            child_plans,
            candidate_workspaces=candidate_workspaces,
            promotion_queue=promotion_queue,
            merge_gate_summary=merge_gate_summary,
            promotion_recovery_summary=promotion_recovery_summary,
        )
        graph = {
            "schema_version": SCHEMA_VERSION,
            "agent_run_graph_id": f"agent-run-graph-{run_id or self._run_id(workers)}",
            "run_id": run_id or self._run_id(workers),
            "status": self._status(child_plans),
            "coordination_modes": self._coordination_modes(events),
            "max_concurrency_observed": self._max_concurrency(events),
            "child_worker_plans": child_plans,
            "candidate_workspaces": candidate_workspaces,
            "promotion_queue": promotion_queue,
            "merge_gate_summary": merge_gate_summary,
            "promotion_recovery_summary": promotion_recovery_summary,
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
            "candidate_workspace_id": str(runtime_profile.get("candidate_workspace_id") or ""),
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
            "collaboration_role": self._collaboration_role(task, worker),
            "artifact_refs": (result or {}).get("artifact_refs", []),
            "validation_refs": (result or {}).get("validation_refs", []),
            "failure_evidence_refs": (result or {}).get("failure_evidence_refs", []),
            "cost": (result or {}).get("cost", {"model_calls": 0, "tool_calls": 0}),
            "summary": (result or {}).get("summary") or worker.get("summary") or "",
        }

    def _collaboration_role(self, task: dict, worker: dict | None = None) -> str:
        worker_kind = str((worker or {}).get("worker_kind") or "")
        if worker_kind == "subagent_readonly_child":
            return "research_child"
        if worker_kind == "subagent_disjoint_write_child":
            return "implementation_child"
        safety = str(task.get("parallel_safety") or "serial")
        kind = str(task.get("task_kind") or "implementation")
        if safety == "readonly":
            return "research_child"
        if safety == "disjoint_writes":
            return "implementation_child"
        if kind in {"review", "report"}:
            return "summary_child"
        return "serial_child"

    def _collaboration_summary(
        self,
        child_plans: list[dict],
        *,
        candidate_workspaces: list[dict],
        promotion_queue: list[dict],
        merge_gate_summary: dict,
        promotion_recovery_summary: dict,
    ) -> dict:
        statuses = [str(plan.get("result_status") or plan.get("status")) for plan in child_plans]
        failure_refs = self._flatten(child_plans, "failure_evidence_refs")
        next_actions = []
        if failure_refs:
            next_actions.append("Debug failed child worker plans before widening concurrency.")
        if not child_plans:
            next_actions.append("Run execute to create child worker evidence.")
        if int(merge_gate_summary.get("blocked_count") or 0) > 0:
            next_actions.append("Resolve merge gate blockers before promoting candidate writes.")
        pending_promotions = [
            item
            for item in promotion_queue
            if str(item.get("status") or "")
            in {"queued", "pending_manual_approval", "auto_approved", "approved"}
        ]
        if pending_promotions:
            next_actions.append("Settle pending candidate promotions before enabling disjoint writes.")
        unresolved_recoveries = int(promotion_recovery_summary.get("unresolved_count") or 0)
        if unresolved_recoveries:
            next_actions.append("Record reject/discard/rollback recovery for blocked promotions.")
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
            "candidate_workspace_count": len(candidate_workspaces),
            "promotion_queue_total": len(promotion_queue),
            "promotion_pending_count": len(pending_promotions),
            "promotion_blocked_count": len(
                [
                    item
                    for item in promotion_queue
                    if str(item.get("status") or "") in {"blocked", "promotion_failed"}
                ]
            ),
            "merge_gate_block_count": int(merge_gate_summary.get("blocked_count") or 0),
            "promotion_recovered_count": int(promotion_recovery_summary.get("recovered_count") or 0),
            "promotion_recovery_unresolved_count": unresolved_recoveries,
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

    def _candidate_workspaces(self, run_dir: Path, promotions: list[dict]) -> list[dict]:
        by_candidate: dict[str, dict] = {}
        candidates_dir = run_dir / "candidates"
        if candidates_dir.exists():
            for path in sorted(candidates_dir.glob("*.json")):
                try:
                    manifest = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                candidate_id = str(manifest.get("candidate_id") or path.stem)
                by_candidate[candidate_id] = {
                    "candidate_id": candidate_id,
                    "task_id": str(manifest.get("task_id") or ""),
                    "workspace": str(manifest.get("workspace") or ""),
                    "strategy": str(manifest.get("strategy") or ""),
                    "workspace_policy": str(manifest.get("workspace_policy") or ""),
                    "backend_reason": str(manifest.get("backend_reason") or ""),
                    "branch_name": manifest.get("branch_name"),
                    "status": str(manifest.get("status") or "unknown"),
                    "parent_worker_invocation_id": manifest.get("parent_worker_invocation_id"),
                    "parent_runtime_profile_id": manifest.get("parent_runtime_profile_id"),
                    "worker_kind": manifest.get("worker_kind"),
                    "parallel_safety": manifest.get("parallel_safety"),
                    "manifest_ref": str(path),
                }
        for promotion in promotions:
            candidate_id = str(promotion.get("candidate_id") or "")
            if not candidate_id:
                continue
            existing = by_candidate.get(candidate_id, {})
            by_candidate[candidate_id] = {
                "candidate_id": candidate_id,
                "task_id": str(promotion.get("task_id") or existing.get("task_id") or ""),
                "workspace": str(promotion.get("workspace") or existing.get("workspace") or ""),
                "strategy": str(promotion.get("strategy") or existing.get("strategy") or ""),
                "workspace_policy": str(
                    promotion.get("workspace_policy") or existing.get("workspace_policy") or ""
                ),
                "backend_reason": str(
                    promotion.get("backend_reason") or existing.get("backend_reason") or ""
                ),
                "branch_name": promotion.get("branch_name", existing.get("branch_name")),
                "status": str(existing.get("status") or "queued"),
                "parent_worker_invocation_id": existing.get("parent_worker_invocation_id"),
                "parent_runtime_profile_id": existing.get("parent_runtime_profile_id"),
                "worker_kind": existing.get("worker_kind"),
                "parallel_safety": existing.get("parallel_safety"),
                "promotion_ids": sorted(
                    {
                        *[str(item) for item in existing.get("promotion_ids", [])],
                        str(promotion.get("promotion_id") or ""),
                    }
                    - {""}
                ),
                "latest_promotion_status": str(promotion.get("status") or ""),
                "promotable_files": [str(item) for item in promotion.get("promotable_files") or []],
                "promoted_files": [str(item) for item in promotion.get("promoted_files") or []],
                "manifest_ref": str(existing.get("manifest_ref") or ""),
            }
        return [by_candidate[key] for key in sorted(by_candidate)]

    def _promotion_queue(self, promotions: list[dict]) -> list[dict]:
        items = []
        for promotion in promotions:
            merge_gate = promotion.get("merge_gate")
            merge_gate = merge_gate if isinstance(merge_gate, dict) else {}
            failure = promotion.get("failure")
            failure = failure if isinstance(failure, dict) else {}
            items.append(
                {
                    "promotion_id": str(promotion.get("promotion_id") or ""),
                    "task_id": str(promotion.get("task_id") or ""),
                    "candidate_id": str(promotion.get("candidate_id") or ""),
                    "status": str(promotion.get("status") or "unknown"),
                    "approval_mode": str(promotion.get("approval_mode") or ""),
                    "promotable_files": [
                        str(item) for item in promotion.get("promotable_files") or []
                    ],
                    "promoted_files": [str(item) for item in promotion.get("promoted_files") or []],
                    "merge_gate_ok": merge_gate.get("ok"),
                    "merge_gate_violations": [
                        str(item) for item in merge_gate.get("violations") or []
                    ],
                    "failure_type": str(failure.get("type") or ""),
                    "failure_message": str(failure.get("message") or ""),
                    "recovery_action": self._promotion_recovery_action(promotion),
                    "recovery_status": self._promotion_recovery_status(promotion),
                    "updated_at": str(promotion.get("updated_at") or ""),
                }
            )
        return sorted(items, key=lambda item: (item["updated_at"], item["promotion_id"]))

    def _promotion_recovery_summary(
        self,
        promotion_queue: list[dict],
        candidate_workspaces: list[dict],
    ) -> dict:
        recovered = [
            item
            for item in promotion_queue
            if str(item.get("recovery_status") or "") in {"recovered", "settled"}
        ]
        unresolved = [
            item
            for item in promotion_queue
            if str(item.get("recovery_status") or "") == "unresolved"
        ]
        discarded_candidates = {
            str(item.get("candidate_id") or "")
            for item in candidate_workspaces
            if str(item.get("status") or "") == "discarded"
        }
        recovery_actions = self._unique(
            str(item.get("recovery_action") or "")
            for item in promotion_queue
            if item.get("recovery_action")
        )
        return {
            "total": len(promotion_queue),
            "recovered_count": len(recovered),
            "unresolved_count": len(unresolved),
            "discarded_candidate_count": len(discarded_candidates - {""}),
            "recovery_actions": recovery_actions,
            "unresolved_refs": [
                str(item.get("promotion_id") or "")
                for item in unresolved
                if item.get("promotion_id")
            ],
            "recovered_refs": [
                str(item.get("promotion_id") or "")
                for item in recovered
                if item.get("promotion_id")
            ],
            "next_actions": []
            if not unresolved
            else ["Reject, discard, retry, or rollback blocked promotions before write fanout."],
        }

    def _promotion_recovery_action(self, promotion: dict) -> str:
        status = str(promotion.get("status") or "")
        decision = promotion.get("decision")
        decision = decision if isinstance(decision, dict) else {}
        action = str(decision.get("action") or "")
        if status == "discarded":
            return "discard"
        if status == "rejected":
            return "reject"
        if status == "promoted":
            return "promote"
        if action:
            return action
        if status in {"blocked", "promotion_failed"}:
            return "needs_recovery"
        return ""

    def _promotion_recovery_status(self, promotion: dict) -> str:
        status = str(promotion.get("status") or "")
        if status in {"discarded", "rejected"}:
            return "recovered"
        if status == "promoted":
            return "settled"
        if status in {"blocked", "promotion_failed"}:
            return "unresolved"
        if status in {"queued", "pending_manual_approval", "auto_approved", "approved"}:
            return "pending"
        return "settled"

    def _merge_gate_summary(self, promotions: list[dict], task_execution: list[dict]) -> dict:
        gates = []
        for promotion in promotions:
            merge_gate = promotion.get("merge_gate")
            if isinstance(merge_gate, dict):
                gates.append(
                    {
                        "source": "candidate_promotion",
                        "source_id": str(promotion.get("promotion_id") or ""),
                        "task_id": str(promotion.get("task_id") or ""),
                        "ok": merge_gate.get("ok"),
                        "promotable_files": [
                            str(item) for item in merge_gate.get("promotable_files") or []
                        ],
                        "violations": [str(item) for item in merge_gate.get("violations") or []],
                    }
                )
        for evidence in task_execution:
            contract = evidence.get("contract_check")
            contract = contract if isinstance(contract, dict) else {}
            merge_gate = contract.get("merge_gate")
            if not isinstance(merge_gate, dict):
                continue
            gates.append(
                {
                    "source": "task_execution_evidence",
                    "source_id": str(evidence.get("evidence_id") or ""),
                    "task_id": str(evidence.get("task_id") or ""),
                    "ok": merge_gate.get("ok"),
                    "promotable_files": [
                        str(item) for item in merge_gate.get("promotable_files") or []
                    ],
                    "violations": [str(item) for item in merge_gate.get("violations") or []],
                }
            )
        blocked = [item for item in gates if item.get("ok") is False]
        return {
            "total": len(gates),
            "passed_count": len([item for item in gates if item.get("ok") is True]),
            "blocked_count": len(blocked),
            "blocked_refs": [str(item.get("source_id") or "") for item in blocked if item.get("source_id")],
            "violations": self._unique(
                violation for item in blocked for violation in item.get("violations") or []
            ),
        }

    def _latest_promotions(self, promotions: list[dict]) -> list[dict]:
        latest: dict[str, dict] = {}
        for item in promotions:
            promotion_id = str(item.get("promotion_id") or "")
            if promotion_id:
                latest[promotion_id] = item
        return [latest[key] for key in sorted(latest)]

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
