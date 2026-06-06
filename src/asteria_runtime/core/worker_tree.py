from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.agent_run_graph import AgentRunGraphBuilder
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class WorkerTreeBuilder:
    validator: SchemaValidator

    def build(self, run_dir: Path) -> dict:
        agent_run_graph = self._agent_run_graph(run_dir)
        workers = JsonlStore(self.validator).read_all(
            run_dir / "workers.jsonl", "worker_invocation"
        )
        results = JsonlStore(self.validator).read_all(
            run_dir / "worker_results.jsonl", "worker_result"
        )
        events = JsonlStore(self.validator).read_all(run_dir / "events.jsonl", "event")
        result_by_worker = {item["worker_invocation_id"]: item for item in results}
        nodes = {
            worker["worker_invocation_id"]: self._node(
                worker,
                result_by_worker.get(worker["worker_invocation_id"]),
            )
            for worker in workers
        }
        roots, orphan_workers = self._tree(nodes)
        status_counts: dict[str, int] = {}
        for node in nodes.values():
            status = str(node.get("result_status") or node.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "total_workers": len(nodes),
            "status_counts": status_counts,
            "successful_workers": status_counts.get("succeeded", 0),
            "failed_workers": sum(
                status_counts.get(status, 0) for status in {"failed", "denied", "timeout"}
            ),
            "parallel_batches": self._parallel_batches(events),
            "coordination_modes": self._coordination_modes(events),
            "total_model_calls": sum(
                int((node.get("cost") or {}).get("model_calls", 0))
                for node in nodes.values()
            ),
            "total_tool_calls": sum(
                int((node.get("cost") or {}).get("tool_calls", 0))
                for node in nodes.values()
            ),
            "agent_run_graph": agent_run_graph,
            "collaboration_summary": agent_run_graph.get("collaboration_summary", {}),
            "orphan_workers": orphan_workers,
            "roots": roots,
        }

    def _agent_run_graph(self, run_dir: Path) -> dict:
        path = run_dir / "agent_run_graph.json"
        if path.exists():
            return JsonStore(self.validator).read(path, "agent_run_graph")
        return AgentRunGraphBuilder(self.validator).build(run_dir)

    def _node(self, worker: dict, result: dict | None) -> dict:
        return {
            "worker_invocation_id": worker["worker_invocation_id"],
            "worker_result_id": (result or {}).get("worker_result_id"),
            "parent_worker_invocation_id": worker.get("parent_worker_invocation_id"),
            "parent_task_id": worker.get("parent_task_id"),
            "worker_kind": worker.get("worker_kind"),
            "parallel_safety": worker.get("parallel_safety"),
            "child_plan_refs": worker.get("child_plan_refs", []),
            "task_id": worker["task_id"],
            "agent_id": worker["agent_id"],
            "runtime_profile_id": worker["runtime_profile_id"],
            "execution_profile_id": worker.get("execution_profile_id"),
            "spawn_kind": worker.get("spawn_kind"),
            "fake_path": worker.get("fake_path"),
            "status": worker["status"],
            "result_status": (result or {}).get("status"),
            "artifact_refs": (result or {}).get("artifact_refs", []),
            "validation_refs": (result or {}).get("validation_refs", []),
            "failure_evidence_refs": (result or {}).get("failure_evidence_refs", []),
            "cost": (result or {}).get("cost", {"model_calls": 0, "tool_calls": 0}),
            "summary": (result or {}).get("summary") or worker.get("summary") or "",
            "children": [],
        }

    def _tree(self, nodes: dict[str, dict]) -> tuple[list[dict], list[str]]:
        roots: list[dict] = []
        orphan_workers: list[str] = []
        for node in nodes.values():
            parent_id = str(node.get("parent_worker_invocation_id") or "")
            if not parent_id:
                roots.append(node)
                continue
            parent = nodes.get(parent_id)
            if parent is None:
                roots.append(node)
                orphan_workers.append(str(node.get("worker_invocation_id") or ""))
                continue
            parent.setdefault("children", []).append(node)
        return roots, orphan_workers

    def _coordination_modes(self, events: list[dict]) -> list[str]:
        modes = []
        for event in events:
            if event.get("type") != "task_graph_selection":
                continue
            reason = str((event.get("data") or {}).get("reason") or "")
            if reason and reason not in modes:
                modes.append(reason)
        return modes

    def _parallel_batches(self, events: list[dict]) -> int:
        return len(
            [
                event
                for event in events
                if event.get("type") == "task_graph_selection"
                and (event.get("data") or {}).get("reason")
                in {"readonly_batch_selection", "parallel_safe_batch_selection"}
            ]
        )
