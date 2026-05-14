from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class RuntimeEvidenceReader:
    validator: SchemaValidator

    def run_evidence(self, run_dir: Path, *, limit: int = 20) -> dict[str, Any]:
        task_execution = self._read_jsonl(
            run_dir / "task_execution_evidence.jsonl",
            "task_execution_evidence",
        )
        worker_results = self._read_jsonl(run_dir / "worker_results.jsonl", "worker_result")
        runtime_requests = self._read_jsonl(run_dir / "runtime_requests.jsonl", "runtime_request")
        merge_gate_evidence = self._merge_gate_evidence(task_execution)
        return {
            "task_execution_evidence": task_execution[-limit:],
            "worker_results": worker_results[-limit:],
            "merge_gate_evidence": merge_gate_evidence[-limit:],
            "runtime_requests": runtime_requests[-limit:],
            "summary": self._summary(
                task_execution=task_execution,
                worker_results=worker_results,
                runtime_requests=runtime_requests,
                merge_gate_evidence=merge_gate_evidence,
            ),
        }

    def task_evidence(self, run_dir: Path, task_id: str, *, limit: int = 10) -> dict[str, Any]:
        run_evidence = self.run_evidence(run_dir, limit=max(limit, 20))
        task_execution = [
            item
            for item in run_evidence["task_execution_evidence"]
            if item.get("task_id") == task_id
        ]
        worker_results = [
            item for item in run_evidence["worker_results"] if item.get("task_id") == task_id
        ]
        runtime_requests = [
            item for item in run_evidence["runtime_requests"] if item.get("task_id") == task_id
        ]
        merge_gate_evidence = [
            item for item in run_evidence["merge_gate_evidence"] if item.get("task_id") == task_id
        ]
        return {
            "task_id": task_id,
            "task_execution_evidence": task_execution[-limit:],
            "worker_results": worker_results[-limit:],
            "merge_gate_evidence": merge_gate_evidence[-limit:],
            "runtime_requests": runtime_requests[-limit:],
            "summary": self._summary(
                task_execution=task_execution,
                worker_results=worker_results,
                runtime_requests=runtime_requests,
                merge_gate_evidence=merge_gate_evidence,
            ),
        }

    def _merge_gate_evidence(self, task_execution: list[dict]) -> list[dict]:
        items = []
        for evidence in task_execution:
            contract = evidence.get("contract_check")
            contract = contract if isinstance(contract, dict) else {}
            merge_gate = contract.get("merge_gate")
            if not isinstance(merge_gate, dict):
                continue
            items.append(
                {
                    "evidence_id": evidence.get("evidence_id"),
                    "task_id": evidence.get("task_id"),
                    "status": evidence.get("status"),
                    "summary": evidence.get("summary"),
                    "merge_gate": merge_gate,
                }
            )
        return items

    def _summary(
        self,
        *,
        task_execution: list[dict],
        worker_results: list[dict],
        runtime_requests: list[dict],
        merge_gate_evidence: list[dict],
    ) -> dict[str, Any]:
        return {
            "task_execution_count": len(task_execution),
            "blocked_execution_count": len(
                [item for item in task_execution if item.get("status") == "blocked"]
            ),
            "worker_result_count": len(worker_results),
            "failed_worker_result_count": len(
                [item for item in worker_results if item.get("status") != "succeeded"]
            ),
            "runtime_request_count": len(runtime_requests),
            "pending_runtime_request_count": len(
                [
                    item
                    for item in runtime_requests
                    if item.get("status") in {"recorded", "decision_created"}
                ]
            ),
            "merge_gate_block_count": len(
                [
                    item
                    for item in merge_gate_evidence
                    if isinstance(item.get("merge_gate"), dict)
                    and item["merge_gate"].get("ok") is False
                ]
            ),
        }

    def _read_jsonl(self, path: Path, schema_name: str) -> list[dict]:
        if not path.exists():
            return []
        return JsonlStore(self.validator).read_all(path, schema_name)
