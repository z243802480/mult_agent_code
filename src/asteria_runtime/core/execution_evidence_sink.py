from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_failure import TaskFailureRecorder
from asteria_runtime.core.validation_result import ValidationResult
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.utils.time import now_iso


_VALIDATION_RESULT_LOCK = RLock()


@dataclass(frozen=True)
class ExecutionEvidenceSink:
    validator: SchemaValidator
    actor: str = "ExecutionEvidenceSink"

    def record_validation_results(
        self,
        context: RuntimeContext,
        task: dict,
        calls: list[dict],
        results: list[Any],
    ) -> list[str]:
        if context.run_dir is None or not results:
            return []
        path = context.run_dir / "validation_results.jsonl"
        store = JsonlStore(self.validator)
        refs: list[str] = []
        with _VALIDATION_RESULT_LOCK:
            existing_count = self._jsonl_count(path)
            for offset, result in enumerate(results, start=1):
                call = calls[offset - 1] if offset <= len(calls) else {}
                raw_args = call.get("args")
                args = raw_args if isinstance(raw_args, dict) else {}
                validation = ValidationResult(
                    validation_result_id=f"validation-{existing_count + offset:04d}",
                    run_id=context.run_id,
                    task_id=task["task_id"],
                    tool_name=str(call.get("tool_name") or "unknown"),
                    command=args.get("command") if isinstance(args.get("command"), str) else None,
                    status="passed" if getattr(result, "ok", False) else "failed",
                    summary=str(getattr(result, "summary", "")),
                    error=getattr(result, "error", None),
                    data=(
                        getattr(result, "data", {})
                        if isinstance(getattr(result, "data", {}), dict)
                        else {}
                    ),
                    created_at=now_iso(),
                )
                store.append(path, validation.to_dict(), "validation_result")
                refs.append(validation.validation_result_id)
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "validation_results_recorded",
                self.actor,
                f"Recorded {len(refs)} validation result(s) for {task['task_id']}.",
                {"task_id": task["task_id"], "validation_refs": refs},
            )
        return refs

    def record_experiment(
        self,
        context: RuntimeContext,
        task: dict,
        action: dict,
        tool_results: list[Any],
        verification_results: list[Any],
        decision: str,
        reason: str,
        rollback_results: list[Any] | None = None,
        contract_check: dict | None = None,
        candidate_workspace: CandidateWorkspace | None = None,
        promoted_files: list[str] | None = None,
    ) -> None:
        if not context.run_dir:
            return
        if decision == "keep":
            self.record_artifacts(context, task, tool_results)
        path = context.run_dir / "experiments.jsonl"
        store = JsonlStore(self.validator)
        existing = store.read_all(path, "experiment") if path.exists() else []
        backup_ids = [
            result.data["backup_id"]
            for result in tool_results
            if result.ok and isinstance(result.data, dict) and result.data.get("backup_id")
        ]
        changed_files = self.changed_files(tool_results)
        verification_passed = len([result for result in verification_results if result.ok])
        experiment = {
            "schema_version": "0.1.0",
            "experiment_id": f"exp-{len(existing) + 1:04d}",
            "run_id": context.run_id,
            "task_id": task["task_id"],
            "idea": action["summary"],
            "baseline": {
                "task_status": task["status"],
                "acceptance_count": len(task.get("acceptance", [])),
            },
            "candidate": {
                "changed_files": sorted(set(changed_files)),
                "backup_ids": backup_ids,
                "rollback": self.rollback_summary(rollback_results or []),
                "workspace": str(candidate_workspace.root) if candidate_workspace else None,
                "candidate_id": (candidate_workspace.candidate_id if candidate_workspace else None),
                "strategy": candidate_workspace.strategy if candidate_workspace else None,
                "workspace_policy": (
                    candidate_workspace.workspace_policy if candidate_workspace else None
                ),
                "backend_reason": candidate_workspace.backend_reason
                if candidate_workspace
                else None,
                "branch_name": candidate_workspace.branch_name if candidate_workspace else None,
                "manifest_path": (
                    str(candidate_workspace.manifest_path)
                    if candidate_workspace and candidate_workspace.manifest_path
                    else None
                ),
                "promoted_files": sorted(set(promoted_files or [])),
            },
            "evaluator": {
                "commands": [
                    call.get("args", {}).get("command") for call in action.get("verification", [])
                ],
                "tool_count": len(action.get("tool_calls", [])),
            },
            "metrics_after": {
                "verification_total": len(verification_results),
                "verification_passed": verification_passed,
                "verification_pass_rate": (
                    verification_passed / len(verification_results) if verification_results else 1.0
                ),
            },
            "contract_check": contract_check or {},
            "decision": decision,
            "reason": reason,
        }
        store.append(path, experiment, "experiment")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "experiment_recorded",
                self.actor,
                f"{experiment['experiment_id']} -> {decision}",
                {
                    "experiment_id": experiment["experiment_id"],
                    "task_id": task["task_id"],
                    "decision": decision,
                    "backup_ids": backup_ids,
                },
            )

    def record_task_failure(
        self,
        context: RuntimeContext,
        task: dict,
        failure_type: str,
        summary: str,
        contract_check: dict | None = None,
        tool_results: list[Any] | None = None,
        verification_results: list[Any] | None = None,
        candidate: dict | None = None,
    ) -> None:
        if not context.run_dir:
            return
        evidence = TaskFailureRecorder(context.run_dir, self.validator).record(
            run_id=context.run_id,
            task=task,
            phase="execute",
            failure_type=failure_type,
            summary=summary,
            contract_check=contract_check,
            tool_results=tool_results,
            verification_results=verification_results,
            candidate=candidate,
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "task_failure_recorded",
                self.actor,
                summary,
                {
                    "evidence_id": evidence["evidence_id"],
                    "task_id": task["task_id"],
                    "failure_type": failure_type,
                },
            )

    def record_artifacts(
        self,
        context: RuntimeContext,
        task: dict,
        tool_results: list[Any],
    ) -> None:
        if not context.run_dir:
            return
        changed_files = self.changed_files(tool_results)
        if not changed_files:
            return

        path = context.run_dir / "artifacts.jsonl"
        store = JsonlStore(self.validator)
        existing = store.read_all(path, "artifact") if path.exists() else []
        known = {artifact["path"] for artifact in existing}
        next_index = len(existing) + 1
        for artifact_path in sorted(set(changed_files)):
            if artifact_path in known:
                continue
            artifact = {
                "schema_version": "0.1.0",
                "artifact_id": f"artifact-{next_index:04d}",
                "run_id": context.run_id,
                "task_id": task["task_id"],
                "type": self.artifact_type(artifact_path),
                "path": artifact_path,
                "created_by": "CoderAgent",
                "summary": f"Created or modified by {task['task_id']}: {task['title']}",
                "created_at": now_iso(),
            }
            store.append(path, artifact, "artifact")
            known.add(artifact_path)
            next_index += 1

    def changed_files(self, tool_results: list[Any]) -> list[str]:
        changed_files = []
        for result in tool_results:
            if not result.ok or not isinstance(result.data, dict):
                continue
            if result.data.get("path") and result.data.get("backup_id"):
                changed_files.append(result.data["path"])
            changed_files.extend(result.data.get("changed_files", []))
        return changed_files

    def rollback_summary(self, rollback_results: list[Any]) -> list[dict]:
        summary = []
        for result in rollback_results:
            item = {
                "ok": result.ok,
                "summary": result.summary,
                "warnings": result.warnings,
            }
            if isinstance(result.data, dict):
                item["backup_id"] = result.data.get("backup_id")
                item["restored"] = result.data.get("restored", [])
                item["skipped"] = result.data.get("skipped", [])
            summary.append(item)
        return summary

    def artifact_type(self, path: str) -> str:
        lowered = path.lower()
        if "test" in lowered or lowered.endswith((".spec.py", ".test.py")):
            return "test_file"
        if lowered.endswith((".md", ".txt", ".rst")):
            return "report"
        return "source_file"

    def artifact_refs(self, context: RuntimeContext, task_id: str) -> list[str]:
        if context.run_dir is None:
            return []
        path = context.run_dir / "artifacts.jsonl"
        if not path.exists():
            return []
        artifacts = JsonlStore(self.validator).read_all(path, "artifact")
        return [
            artifact["artifact_id"]
            for artifact in artifacts
            if artifact.get("task_id") == task_id and artifact.get("artifact_id")
        ]

    def task_failure_refs(self, context: RuntimeContext, task_id: str) -> list[str]:
        if context.run_dir is None:
            return []
        path = context.run_dir / "task_failures.jsonl"
        if not path.exists():
            return []
        failures = JsonlStore(self.validator).read_all(path, "task_failure_evidence")
        return [
            failure["evidence_id"]
            for failure in failures
            if failure.get("task_id") == task_id and failure.get("evidence_id")
        ]

    def decision_refs(self, context: RuntimeContext, task_id: str) -> list[str]:
        if context.run_dir is None:
            return []
        path = context.run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        decisions = JsonlStore(self.validator).read_all(path, "decision_point")
        refs = []
        for decision in decisions:
            metadata = decision.get("metadata") or {}
            if metadata.get("task_id") == task_id and decision.get("decision_id"):
                refs.append(decision["decision_id"])
        return refs

    def validation_refs(self, context: RuntimeContext, task_id: str) -> list[str]:
        if context.run_dir is None:
            return []
        path = context.run_dir / "validation_results.jsonl"
        if not path.exists():
            return []
        validations = JsonlStore(self.validator).read_all(path, "validation_result")
        return [
            validation["validation_result_id"]
            for validation in validations
            if validation.get("task_id") == task_id and validation.get("validation_result_id")
        ]

    def _jsonl_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
