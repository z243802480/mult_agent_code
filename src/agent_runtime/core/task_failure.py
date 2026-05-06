from __future__ import annotations

from pathlib import Path

from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


class TaskFailureRecorder:
    def __init__(self, run_dir: Path, validator: SchemaValidator) -> None:
        self.run_dir = run_dir
        self.store = JsonlStore(validator)
        self.path = run_dir / "task_failures.jsonl"

    def record(
        self,
        *,
        run_id: str | None,
        task: dict,
        phase: str,
        failure_type: str,
        summary: str,
        contract_check: dict | None = None,
        tool_results: list | None = None,
        verification_results: list | None = None,
        candidate: dict | None = None,
    ) -> dict:
        existing = (
            self.store.read_all(self.path, "task_failure_evidence") if self.path.exists() else []
        )
        evidence = {
            "schema_version": "0.1.0",
            "evidence_id": f"task-failure-{len(existing) + 1:04d}",
            "run_id": run_id,
            "task_id": task["task_id"],
            "phase": phase,
            "failure_type": failure_type,
            "summary": summary,
            "task_status": str(task.get("status") or "unknown"),
            "contract_check": contract_check or {},
            "tool_failures": _failed_results(tool_results or []),
            "verification_failures": _failed_results(verification_results or []),
            "candidate": candidate or {},
            "recommendations": recommendations_for_failure(failure_type, contract_check or {}),
            "created_at": now_iso(),
        }
        self.store.append(self.path, evidence, "task_failure_evidence")
        return evidence


def recommendations_for_failure(failure_type: str, contract_check: dict) -> list[str]:
    violations = [str(item) for item in contract_check.get("violations", [])]
    recommendations: list[str] = []
    if "required verification was not provided" in violations:
        recommendations.append(
            "Add a verification command that directly proves the acceptance criteria."
        )
    if "verification did not pass" in violations:
        recommendations.append(
            "Inspect verification failures and repair the smallest related artifact."
        )
    if "required changed artifact was not produced" in violations:
        recommendations.append("Produce or modify an artifact before claiming the task complete.")
    if any(item.startswith("expected changed files were not modified") for item in violations):
        expected = ", ".join(str(item) for item in contract_check.get("expected_changed_files", []))
        recommendations.append(f"Modify one of the expected task files: {expected}.")
    if failure_type == "tool_failure":
        recommendations.append(
            "Use recent tool failure summaries to choose a smaller repair action."
        )
    if failure_type == "policy_decision":
        recommendations.append("Wait for the user decision or choose a lower-risk tool call.")
    if failure_type == "exception":
        recommendations.append(
            "Repair the execution action so it satisfies schema, policy, and tool contracts."
        )
    return recommendations or ["Use the failure summary as the next debug input."]


def _failed_results(results: list) -> list[dict]:
    failures = []
    for result in results:
        if getattr(result, "ok", False):
            continue
        failures.append(
            {
                "summary": str(getattr(result, "summary", "")),
                "error": getattr(result, "error", None),
                "warnings": list(getattr(result, "warnings", []) or []),
                "data": getattr(result, "data", {})
                if isinstance(getattr(result, "data", {}), dict)
                else {},
            }
        )
    return failures[-10:]
