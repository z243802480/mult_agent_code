from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.agents.debug_agent import DebugAgent
from asteria_runtime.core.budget import BudgetController
from asteria_runtime.core.candidate_workspace import CandidateWorkspace
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.core.runtime_evidence import RuntimeEvidenceReader
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_contract import check_completion_contract
from asteria_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder
from asteria_runtime.core.task_failure import TaskFailureRecorder
from asteria_runtime.core.task_board import TaskBoard, TaskStateError
from asteria_runtime.models.base import ModelClient
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.models.metered import MeteredModelClient
from asteria_runtime.models.model_call_logger import ModelCallLogger
from asteria_runtime.storage.event_logger import EventLogger
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.tools.defaults import create_default_tool_registry
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class RepairSummary:
    task_id: str
    status: str
    summary: str
    repair_calls: int
    verification_calls: int
    evidence_path: Path | None = None


@dataclass(frozen=True)
class DebugResult:
    run_id: str
    repaired: int
    still_blocked: int
    repairs: list[RepairSummary] = field(default_factory=list)
    cost_report_path: Path | None = None

    def to_text(self) -> str:
        lines = [
            f"Debugged run: {self.run_id}",
            f"Repaired tasks: {self.repaired}",
            f"Still blocked: {self.still_blocked}",
        ]
        for repair in self.repairs:
            lines.append(
                f"- {repair.task_id}: {repair.status} ({repair.repair_calls} repair, {repair.verification_calls} verification)"
            )
            if repair.evidence_path:
                lines.append(f"  evidence: {repair.evidence_path}")
        if self.cost_report_path:
            lines.append(f"Cost report: {self.cost_report_path}")
        return "\n".join(lines)


class DebugCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        task_id: str | None = None,
        max_repairs: int = 1,
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.task_id = task_id
        self.max_repairs = max_repairs
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.registry = create_default_tool_registry()
        self.execution_evidence = TaskExecutionEvidenceRecorder(self.validator)
        self.runtime_evidence = RuntimeEvidenceReader(self.validator)

    def run(self) -> DebugResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")

        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `asteria plan` first.")
        run_dir = run_store.run_dir(run_id)
        run = run_store.load_run(run_id)
        policy = load_policy_config(agent_dir, self.validator)
        goal_spec = self.store.read(run_dir / "goal_spec.json", "goal_spec")
        cost_report_path = run_dir / "cost_report.json"
        budget = BudgetController.from_report(
            policy, self._read_cost(cost_report_path, run_id), run_id=run_id
        )
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)
        context = RuntimeContext(
            root=self.root,
            run_id=run_id,
            policy=policy,
            validator=self.validator,
            event_logger=event_logger,
            budget=budget,
        )
        debug_agent = DebugAgent(self._model_client(run_dir, budget), self.validator)
        task_board = TaskBoard(run_dir / "task_plan.json", self.validator)
        runtime_context = ContextLoader(self.root, self.validator).load(run_id)

        run["status"] = "running"
        run["current_phase"] = "DEBUG"
        run_store.update_run(run)
        event_logger.record(run_id, "phase_changed", "DebugCommand", "EXECUTE -> DEBUG")

        repairs: list[RepairSummary] = []
        for task in self._blocked_tasks(task_board)[: self.max_repairs]:
            repairs.append(
                self._repair_task(
                    task,
                    task_board,
                    context,
                    debug_agent,
                    goal_spec,
                    run_dir,
                    runtime_context,
                )
            )
            task_board.promote_unblocked()

        self._mirror_backlog(agent_dir, task_board)
        self.store.write(cost_report_path, budget.cost_report(), "cost_report")

        repaired = len([item for item in repairs if item.status == "done"])
        still_blocked = len([item for item in repairs if item.status == "blocked"])
        all_tasks = task_board.list_tasks()
        if all(task["status"] == "done" for task in all_tasks):
            run["status"] = "completed"
            run["current_phase"] = "DONE"
            run["ended_at"] = now_iso()
            run["summary"] = "Debug repaired all planned tasks."
            event_logger.record(run_id, "run_completed", "DebugCommand", run["summary"])
        elif still_blocked:
            run["status"] = "blocked"
            run["summary"] = "Debug attempted repair but work remains blocked."
            event_logger.record(run_id, "run_blocked", "DebugCommand", run["summary"])
        else:
            run["status"] = "running"
            run["summary"] = f"Debug repaired {repaired} task(s); more work remains."
        run_store.update_run(run)

        return DebugResult(
            run_id=run_id,
            repaired=repaired,
            still_blocked=still_blocked,
            repairs=repairs,
            cost_report_path=cost_report_path,
        )

    def _repair_task(
        self,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
        debug_agent: DebugAgent,
        goal_spec: dict,
        run_dir: Path,
        runtime_context: dict,
    ) -> RepairSummary:
        task_id = task["task_id"]
        if context.event_logger:
            context.event_logger.record(
                context.run_id, "repair_started", "DebugCommand", f"Started repair for {task_id}"
            )
        self._record_progress(
            context,
            task,
            channel="progress",
            event_type="start",
            phase="execute",
            status="running",
            title="Repair started",
            summary=f"Started repair loop for {task_id}.",
        )
        try:
            failure_evidence = self._failure_evidence(run_dir, task_board.get_task(task_id))
            self._record_progress(
                context,
                task,
                channel="evidence",
                event_type="evidence",
                phase="review",
                status="completed",
                title="Repair evidence loaded",
                summary=(
                    f"Loaded {len(failure_evidence.get('recent_task_execution_evidence') or [])} "
                    "recent task evidence item(s)."
                ),
                evidence_refs=self._run_refs(
                    "task_execution_evidence.jsonl",
                    "task_failures.jsonl",
                    "worker_results.jsonl",
                ),
                data={
                    "recent_task_execution_evidence": len(
                        failure_evidence.get("recent_task_execution_evidence") or []
                    ),
                    "recent_task_failures": len(failure_evidence.get("recent_task_failures") or []),
                    "recent_tool_failures": len(failure_evidence.get("recent_tool_failures") or []),
                },
            )
            skip_reason = self._skip_unpromoted_candidate_repair(failure_evidence)
            if skip_reason:
                self._block_task(task_board, task_id, skip_reason, context)
                evidence_path = self.execution_evidence.record(
                    context,
                    task,
                    {
                        "summary": "Skipped debug repair; replan is required.",
                        "tool_calls": [],
                        "verification": [],
                    },
                    [],
                    [],
                    "blocked",
                    skip_reason,
                    actor="DebugCommand",
                    failure_type="repair_skipped_replan_required",
                )
                self._record_task_failure(
                    context,
                    task,
                    "repair_skipped_replan_required",
                    skip_reason,
                )
                self._record_progress(
                    context,
                    task,
                    channel="evidence",
                    event_type="evidence",
                    phase="blocked",
                    status="blocked",
                    title="Repair skipped",
                    summary=skip_reason,
                    evidence_refs=self._refs(evidence_path),
                    data={"failure_type": "repair_skipped_replan_required"},
                )
                return RepairSummary(task_id, "blocked", skip_reason, 0, 0, evidence_path)
            if context.budget:
                context.budget.record_repair_attempt()
            task_board.update_status(task_id, "ready")
            task_board.update_status(task_id, "in_progress")
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="execute",
                status="running",
                title="Repair action requested",
                summary=f"Asked the debug model to propose a repair for {task_id}.",
                data={"available_tools": self.registry.names()},
            )
            action = debug_agent.propose_repair(
                task=task_board.get_task(task_id),
                goal_spec=goal_spec,
                failure_evidence=failure_evidence,
                available_tools=self.registry.names(),
                run_id=context.run_id or "",
                runtime_context=runtime_context,
            )
            self._require_non_empty_action(action)
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="execute",
                status="running",
                title="Repair action proposed",
                summary=(
                    f"Prepared {len(action.get('tool_calls') or [])} repair tool call(s) "
                    f"and {len(action.get('verification') or [])} verification step(s)."
                ),
                data={
                    "tool_call_count": len(action.get("tool_calls") or []),
                    "verification_count": len(action.get("verification") or []),
                    "summary": action.get("summary", ""),
                },
            )
            candidate = self._create_candidate_workspace(context, task)
            candidate_context = self._candidate_context(context, candidate)
            if context.event_logger:
                context.event_logger.record(
                    context.run_id,
                    "candidate_workspace_created",
                    "DebugCommand",
                    f"Created repair candidate workspace for {task_id}",
                    {
                        "task_id": task_id,
                        "candidate_id": candidate.candidate_id,
                        "workspace": str(candidate.root),
                    },
                )
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="execute",
                status="running",
                title="Repair candidate workspace created",
                summary=(
                    f"Created repair candidate {candidate.candidate_id} "
                    f"using {candidate.strategy}."
                ),
                artifact_refs=self._refs(candidate.manifest_path),
                data={
                    "candidate_id": candidate.candidate_id,
                    "strategy": candidate.strategy,
                    "workspace_policy": candidate.workspace_policy,
                    "backend_reason": candidate.backend_reason,
                    "branch_name": candidate.branch_name,
                },
            )
            tool_results = self._run_tool_calls(action["tool_calls"], task, candidate_context)
            task_board.update_status(task_id, "testing")
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="start",
                phase="review",
                status="running",
                title="Repair verification started",
                summary=f"Running {len(action.get('verification') or [])} repair verification step(s).",
                data={"verification_count": len(action.get("verification") or [])},
            )
            verification = self._run_tool_calls(
                action["verification"],
                task,
                candidate_context,
                stop_on_failure=False,
            )
            contract_check = check_completion_contract(
                task,
                self._changed_files(tool_results),
                verification,
                allow_verified_noop=True,
            )
            self._record_progress(
                context,
                task,
                channel="progress",
                event_type="message",
                phase="review",
                status="completed" if contract_check.ok else "blocked",
                title="Repair contract checked",
                summary=contract_check.summary(),
                data={"contract_check": contract_check.to_dict()},
            )
            if contract_check.ok:
                promoted_files = self._promote_candidate_changes(
                    context, candidate, contract_check.changed_files
                )
                self._record_repair_artifacts(context, task, promoted_files)
                self._record_progress(
                    context,
                    task,
                    channel="file",
                    event_type="file_modified",
                    phase="execute",
                    status="completed",
                    title="Repair candidate promoted",
                    summary=(
                        f"Promoted {len(promoted_files)} repaired file(s) from candidate workspace."
                    ),
                    artifact_refs=promoted_files,
                    file_changes=self._file_changes(promoted_files),
                    data={"promoted_files": promoted_files},
                )
                reason = "Repair verification passed."
                if not self._changed_files(tool_results):
                    reason = (
                        "Repair verification passed without changes; task was already satisfied."
                    )
                evidence_path = self.execution_evidence.record(
                    context,
                    task,
                    action,
                    tool_results,
                    verification,
                    "done",
                    reason,
                    actor="DebugCommand",
                    contract_check=contract_check.to_dict(),
                    candidate_workspace=candidate,
                    promoted_files=promoted_files,
                )
                self._record_repair_experiment(
                    context,
                    task,
                    action,
                    tool_results,
                    verification,
                    "keep",
                    reason,
                    contract_check=contract_check.to_dict(),
                    candidate_workspace=candidate,
                    promoted_files=promoted_files,
                )
                self._complete_task_after_candidate_promotion(
                    task_board,
                    task_id,
                    action.get("completion_notes") or action["summary"],
                )
                if context.event_logger:
                    context.event_logger.record(
                        context.run_id, "repair_completed", "DebugCommand", f"Repaired {task_id}"
                    )
                self._record_progress(
                    context,
                    task,
                    channel="evidence",
                    event_type="evidence",
                    phase="result",
                    status="completed",
                    title="Repair evidence recorded",
                    summary=reason,
                    artifact_refs=promoted_files,
                    evidence_refs=self._refs(evidence_path),
                    file_changes=self._file_changes(promoted_files),
                    data={"verification_passed": True},
                )
                return RepairSummary(
                    task_id,
                    "done",
                    action["summary"],
                    len(action["tool_calls"]),
                    len(action["verification"]),
                    evidence_path,
                )
            reason = contract_check.summary()
            self._block_task(task_board, task_id, reason, context)
            evidence_path = self.execution_evidence.record(
                context,
                task,
                action,
                tool_results,
                verification,
                "blocked",
                reason,
                actor="DebugCommand",
                contract_check=contract_check.to_dict(),
                candidate_workspace=candidate,
                failure_type="repair_contract_violation",
            )
            self._record_repair_experiment(
                context,
                task,
                action,
                tool_results,
                verification,
                "discard",
                f"{reason}; candidate kept isolated at {candidate.root}.",
                contract_check=contract_check.to_dict(),
                candidate_workspace=candidate,
            )
            self._record_task_failure(
                context,
                task,
                "repair_contract_violation",
                reason,
                contract_check=contract_check.to_dict(),
                tool_results=tool_results,
                verification_results=verification,
                candidate={
                    "summary": action["summary"],
                    "changed_files": contract_check.changed_files,
                },
            )
            self._record_progress(
                context,
                task,
                channel="evidence",
                event_type="evidence",
                phase="blocked",
                status="blocked",
                title="Repair evidence recorded",
                summary=reason,
                evidence_refs=self._refs(evidence_path),
                data={
                    "failure_type": "repair_contract_violation",
                    "contract_check": contract_check.to_dict(),
                },
            )
            return RepairSummary(
                task_id,
                "blocked",
                reason,
                len(action["tool_calls"]),
                len(action["verification"]),
                evidence_path,
            )
        except Exception as exc:  # noqa: BLE001 - repair loop must persist failures
            self._block_task(task_board, task_id, str(exc), context)
            failure_type = self._failure_type(exc)
            self._record_task_failure(context, task, failure_type, str(exc))
            evidence_path = self.execution_evidence.record(
                context,
                task,
                None,
                [],
                [],
                "blocked",
                str(exc),
                actor="DebugCommand",
                failure_type=failure_type,
            )
            self._record_progress(
                context,
                task,
                channel="evidence",
                event_type="evidence",
                phase="blocked",
                status="blocked",
                title="Repair failed before completion",
                summary=str(exc),
                evidence_refs=self._refs(evidence_path),
                data={"failure_type": failure_type, "error_type": type(exc).__name__},
            )
            return RepairSummary(task_id, "blocked", str(exc), 0, 0, evidence_path)

    def _require_non_empty_action(self, action: dict) -> None:
        if not action.get("tool_calls") and not action.get("verification"):
            raise RuntimeError("Repair action contained no tool calls or verification.")

    def _run_tool_calls(
        self,
        calls: list[dict],
        task: dict,
        context: RuntimeContext,
        stop_on_failure: bool = True,
    ) -> list:
        results = []
        allowed = set(task["allowed_tools"])
        for call in calls:
            tool_name = call["tool_name"]
            if tool_name not in allowed:
                raise PermissionError(f"Tool is not allowed for {task['task_id']}: {tool_name}")
            result = self.registry.call(
                tool_name,
                context,
                task_id=task["task_id"],
                agent_id="DebugAgent",
                **call["args"],
            )
            results.append(result)
            if stop_on_failure and not result.ok:
                raise RuntimeError(f"Tool failed: {tool_name}: {result.summary}")
        return results

    def _record_repair_artifacts(
        self,
        context: RuntimeContext,
        task: dict,
        changed_files: list[str],
    ) -> None:
        if not context.run_dir:
            return
        if not changed_files:
            return
        path = context.run_dir / "artifacts.jsonl"
        existing = self.jsonl.read_all(path, "artifact") if path.exists() else []
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
                "type": self._artifact_type(artifact_path),
                "path": artifact_path,
                "created_by": "DebugAgent",
                "summary": f"Repaired by DebugAgent for {task['task_id']}: {task['title']}",
                "created_at": now_iso(),
            }
            self.jsonl.append(path, artifact, "artifact")
            known.add(artifact_path)
            next_index += 1

    def _record_repair_experiment(
        self,
        context: RuntimeContext,
        task: dict,
        action: dict,
        tool_results: list,
        verification_results: list,
        decision: str,
        reason: str,
        rollback_results: list | None = None,
        contract_check: dict | None = None,
        candidate_workspace: CandidateWorkspace | None = None,
        promoted_files: list[str] | None = None,
    ) -> None:
        if not context.run_dir:
            return
        path = context.run_dir / "experiments.jsonl"
        existing = self.jsonl.read_all(path, "experiment") if path.exists() else []
        backup_ids = [
            result.data["backup_id"]
            for result in tool_results
            if result.ok and isinstance(result.data, dict) and result.data.get("backup_id")
        ]
        verification_passed = len([result for result in verification_results if result.ok])
        experiment = {
            "schema_version": "0.1.0",
            "experiment_id": f"exp-{len(existing) + 1:04d}",
            "run_id": context.run_id,
            "task_id": task["task_id"],
            "idea": action["summary"],
            "baseline": {
                "task_status": "blocked",
                "failure_evidence": "repair loop",
            },
            "candidate": {
                "changed_files": sorted(set(self._changed_files(tool_results))),
                "backup_ids": backup_ids,
                "rollback": self._rollback_summary(rollback_results or []),
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
        self.jsonl.append(path, experiment, "experiment")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "experiment_recorded",
                "DebugCommand",
                f"{experiment['experiment_id']} -> {decision}",
                {
                    "experiment_id": experiment["experiment_id"],
                    "task_id": task["task_id"],
                    "decision": decision,
                },
            )

    def _record_task_failure(
        self,
        context: RuntimeContext,
        task: dict,
        failure_type: str,
        summary: str,
        contract_check: dict | None = None,
        tool_results: list | None = None,
        verification_results: list | None = None,
        candidate: dict | None = None,
    ) -> None:
        if not context.run_dir:
            return
        evidence = TaskFailureRecorder(context.run_dir, self.validator).record(
            run_id=context.run_id,
            task=task,
            phase="debug",
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
                "DebugCommand",
                summary,
                {
                    "evidence_id": evidence["evidence_id"],
                    "task_id": task["task_id"],
                    "failure_type": failure_type,
                },
            )

    def _record_progress(
        self,
        context: RuntimeContext,
        task: dict,
        *,
        channel: str,
        event_type: str,
        phase: str,
        status: str,
        title: str,
        summary: str,
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        file_changes: list[dict] | None = None,
        data: dict | None = None,
    ) -> None:
        if context.run_id is None or context.run_dir is None:
            return
        logger = UserProgressLogger(context.run_dir / "user_progress.jsonl", context.validator)
        logger.record(
            run_id=context.run_id,
            channel=channel,
            event_type=event_type,
            phase=phase,
            status=status,
            title=title,
            summary=summary,
            artifact_refs=artifact_refs or [],
            evidence_refs=evidence_refs or [],
            file_changes=file_changes or [],
            data={
                "task_id": task.get("task_id"),
                "task_title": task.get("title"),
                **(data or {}),
            },
        )

    def _refs(self, value: Path | str | None) -> list[str]:
        if value is None:
            return []
        return [str(value)]

    def _run_refs(self, *names: str) -> list[str]:
        return [name for name in names]

    def _file_changes(self, paths: list[str]) -> list[dict]:
        return [
            {
                "path": path,
                "operation": "modified",
            }
            for path in sorted(set(paths))
        ]

    def _failure_type(self, exc: Exception) -> str:
        if isinstance(exc, PermissionError):
            return "tool_permission"
        message = str(exc).lower()
        if message.startswith("tool failed:"):
            return "tool_failure"
        if "no tool calls or verification" in message:
            return "empty_action"
        return "repair_exception"

    def _rollback_backups(
        self,
        context: RuntimeContext,
        task: dict,
        tool_results: list,
    ) -> list:
        backup_ids = [
            result.data["backup_id"]
            for result in tool_results
            if result.ok and isinstance(result.data, dict) and result.data.get("backup_id")
        ]
        rollback_results = []
        delete_created_files = bool(
            context.policy.get("permissions", {}).get("allow_restore_delete_created_files", False)
        )
        for backup_id in reversed(backup_ids):
            result = self.registry.call(
                "restore_backup",
                context,
                task_id=task["task_id"],
                agent_id="DebugCommand",
                backup_id=backup_id,
                delete_created_files=delete_created_files,
            )
            rollback_results.append(result)
        return rollback_results

    def _rollback_summary(self, rollback_results: list) -> list[dict]:
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

    def _changed_files(self, tool_results: list) -> list[str]:
        changed_files = []
        for result in tool_results:
            if not result.ok or not isinstance(result.data, dict):
                continue
            if result.data.get("path"):
                changed_files.append(result.data["path"])
            changed_files.extend(result.data.get("changed_files", []))
        return changed_files

    def _create_candidate_workspace(
        self,
        context: RuntimeContext,
        task: dict,
    ) -> CandidateWorkspace:
        if context.run_dir is None:
            raise RuntimeError("Cannot isolate repair candidate without a run directory.")
        return CandidateWorkspace.create(context.root, context.run_dir, task["task_id"], task=task)

    def _candidate_context(
        self,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
    ) -> RuntimeContext:
        return RuntimeContext(
            root=candidate.root,
            run_id=context.run_id,
            policy=context.policy,
            validator=context.validator,
            event_logger=context.event_logger,
            budget=context.budget,
            agent_dir_override=context.asteria_dir,
            run_dir_override=context.run_dir,
        )

    def _promote_candidate_changes(
        self,
        context: RuntimeContext,
        candidate: CandidateWorkspace,
        changed_files: list[str],
    ) -> list[str]:
        del context
        if not changed_files:
            return []
        return candidate.promote(changed_files)

    def _complete_task_after_candidate_promotion(
        self,
        task_board: TaskBoard,
        task_id: str,
        notes: str,
    ) -> None:
        try:
            task_board.complete_task(task_id, notes)
        except TaskStateError as exc:
            if not str(exc).startswith("Task not found:"):
                raise
            return

    def _artifact_type(self, path: str) -> str:
        lowered = path.lower()
        if "test" in lowered or lowered.endswith((".spec.py", ".test.py")):
            return "test_file"
        if lowered.endswith((".md", ".txt", ".rst")):
            return "report"
        return "source_file"

    def _failure_evidence(self, run_dir: Path, task: dict) -> dict:
        task_id = task["task_id"]
        runtime_os_evidence = self.runtime_evidence.task_evidence(run_dir, task_id)
        tool_calls = self._read_jsonl(run_dir / "tool_calls.jsonl", "tool_call")
        model_calls = self._read_jsonl(run_dir / "model_calls.jsonl", "model_call")
        events = self._read_jsonl(run_dir / "events.jsonl", "event")
        experiments = self._read_jsonl(run_dir / "experiments.jsonl", "experiment")
        task_failures = self._read_jsonl(run_dir / "task_failures.jsonl", "task_failure_evidence")
        return {
            "task_id": task_id,
            "runtime_os_evidence": runtime_os_evidence,
            "recent_task_execution_evidence": runtime_os_evidence["task_execution_evidence"][-5:],
            "recent_worker_results": runtime_os_evidence["worker_results"][-5:],
            "recent_merge_gate_evidence": runtime_os_evidence["merge_gate_evidence"][-5:],
            "recent_runtime_requests": runtime_os_evidence["runtime_requests"][-5:],
            "recent_tool_failures": [
                call
                for call in tool_calls
                if call.get("task_id") == task_id and call.get("status") != "success"
            ][-10:],
            "recent_model_failures": [
                call for call in model_calls if call.get("status") != "success"
            ][-5:],
            "recent_events": [
                event
                for event in events
                if event.get("type") in {"task_blocked", "tool_called", "run_blocked"}
            ][-20:],
            "task_contract": task.get("completion_contract") or {},
            "expected_changed_files": task.get("expected_changed_files") or [],
            "recent_contract_checks": [
                experiment.get("contract_check")
                for experiment in experiments
                if experiment.get("task_id") == task_id and experiment.get("contract_check")
            ][-5:],
            "recent_task_failures": [
                failure for failure in task_failures if failure.get("task_id") == task_id
            ][-5:],
        }

    def _skip_unpromoted_candidate_repair(self, failure_evidence: dict) -> str | None:
        recent = failure_evidence.get("recent_task_execution_evidence")
        recent = recent if isinstance(recent, list) else []
        latest = recent[-1] if recent and isinstance(recent[-1], dict) else {}
        candidate = latest.get("candidate") if isinstance(latest.get("candidate"), dict) else {}
        promoted_files = candidate.get("promoted_files") if isinstance(candidate, dict) else []
        if promoted_files:
            return None
        verification_results = latest.get("verification_results")
        verification_results = (
            verification_results if isinstance(verification_results, list) else []
        )
        if not any(self._fatal_verification_failure(result) for result in verification_results):
            return None
        return (
            "Repair skipped: previous candidate failed before promotion with a fatal syntax "
            "error; replan should create a fresh artifact instead of debugging missing files."
        )

    def _fatal_verification_failure(self, result: object) -> bool:
        if not isinstance(result, dict) or result.get("ok"):
            return False
        raw_data = result.get("data")
        data: dict = raw_data if isinstance(raw_data, dict) else {}
        text = "\n".join(
            [
                str(result.get("summary") or ""),
                str(data.get("stderr") or ""),
                str(data.get("stdout") or ""),
            ]
        )
        return any(signal in text for signal in ["SyntaxError", "IndentationError"])

    def _blocked_tasks(self, task_board: TaskBoard) -> list[dict]:
        tasks = task_board.list_tasks()
        if self.task_id:
            task = task_board.get_task(self.task_id)
            return [task] if task["status"] == "blocked" else []
        return [task for task in tasks if task["status"] == "blocked"]

    def _block_task(
        self, task_board: TaskBoard, task_id: str, reason: str, context: RuntimeContext
    ) -> None:
        try:
            current = task_board.get_task(task_id)
            if current["status"] not in {"blocked", "done", "discarded"}:
                task_board.update_status(task_id, "blocked")
            task_board.update_notes(task_id, reason)
        except TaskStateError:
            pass
        if context.event_logger:
            context.event_logger.record(context.run_id, "repair_blocked", "DebugCommand", reason)

    def _model_client(self, run_dir: Path, budget: BudgetController) -> ModelClient:
        if self.model_client:
            return MeteredModelClient(
                self.model_client,
                budget,
                ModelCallLogger(run_dir, self.validator),
            )
        return create_model_client(run_dir, self.validator, budget)

    def _read_cost(self, path: Path, run_id: str) -> dict:
        if path.exists():
            return self.store.read(path, "cost_report")
        return {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "model_calls": 0,
            "tool_calls": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "strong_model_calls": 0,
            "cheap_model_calls": 0,
            "repair_attempts": 0,
            "research_calls": 0,
            "context_compactions": 0,
            "user_decisions": 0,
            "status": "within_budget",
            "warnings": [],
        }

    def _read_jsonl(self, path: Path, schema_name: str) -> list[dict]:
        if not path.exists():
            return []
        return self.jsonl.read_all(path, schema_name)

    def _mirror_backlog(self, agent_dir: Path, task_board: TaskBoard) -> None:
        self.store.write(
            agent_dir / "tasks" / "backlog.json",
            {"schema_version": "0.1.0", "tasks": task_board.list_tasks()},
            "task_board",
        )

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted(
            [path for path in runs_dir.iterdir() if path.is_dir()], key=lambda item: item.name
        )
        return runs[-1].name if runs else None
