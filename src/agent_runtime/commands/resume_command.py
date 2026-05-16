from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.commands.run_command import RunCommand, RunResult, RunStepSummary
from agent_runtime.core.runtime_evidence import RuntimeEvidenceReader
from agent_runtime.models.base import ModelClient
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ResumeResult:
    run_result: RunResult
    applied_decisions: int
    created_tasks: int

    @property
    def run_id(self) -> str:
        return self.run_result.run_id

    @property
    def status(self) -> str:
        return self.run_result.status

    def to_text(self) -> str:
        lines = [
            f"Resumed run: {self.run_id}",
            f"Status: {self.status}",
            f"Applied decisions: {self.applied_decisions}",
            f"Created tasks: {self.created_tasks}",
            f"Final report: {self.run_result.final_report_path}",
        ]
        return "\n".join(lines)


class ResumeCommand:
    _TASK_ACTIONS = {"create_task", "require_replan"}

    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        max_iterations: int | None = None,
        max_tasks_per_iteration: int = 1,
        model_client: ModelClient | None = None,
        execute_model_client: ModelClient | None = None,
        debug_model_client: ModelClient | None = None,
        review_model_client: ModelClient | None = None,
        parallel_writes: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.max_iterations = max_iterations
        self.max_tasks_per_iteration = max_tasks_per_iteration
        self.model_client = model_client
        self.execute_model_client = execute_model_client
        self.debug_model_client = debug_model_client
        self.review_model_client = review_model_client
        self.parallel_writes = parallel_writes
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)
        self.runtime_evidence = RuntimeEvidenceReader(self.validator)

    def run(self) -> ResumeResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")
        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `agent run` first.")
        run_dir = run_store.run_dir(run_id)
        pending = self._pending_decisions(run_dir)
        if pending:
            pending_ids = ", ".join(decision["decision_id"] for decision in pending)
            raise RuntimeError(f"Run still has pending decisions: {pending_ids}")

        applied_decisions, created_tasks = self._apply_resolved_decisions(
            agent_dir,
            run_dir,
            run_id,
        )
        run = run_store.load_run(run_id)
        task_plan_path = run_dir / "task_plan.json"
        task_plan = self.store.read(task_plan_path, "task_board") if task_plan_path.exists() else {"tasks": []}
        self._reconcile_with_runtime_evidence(run_dir, task_plan)

        if run["status"] == "completed" and applied_decisions == 0:
            return ResumeResult(
                RunResult(
                    run_id=run_id,
                    status="completed",
                    final_report_path=run_dir / "final_report.md",
                    steps=[
                        RunStepSummary(
                            "resume",
                            "completed",
                            "Run is already completed; no unapplied decisions found.",
                        )
                    ],
                ),
                applied_decisions=0,
                created_tasks=0,
            )
        if run["status"] == "paused":
            run["status"] = "running"
            run["current_phase"] = "RESUME"
            run["ended_at"] = None
            run["summary"] = f"Resumed after applying {applied_decisions} decision(s)."
            run_store.update_run(run)
        run_store.set_current_session(run_id, "run_resumed")

        steps = [
            RunStepSummary(
                "resume",
                "completed",
                f"Applied {applied_decisions} decision(s); created {created_tasks} task(s).",
            )
        ]
        result = RunCommand(
            self.root,
            goal="",
            max_iterations=self.max_iterations,
            max_tasks_per_iteration=self.max_tasks_per_iteration,
            model_client=self.model_client,
            execute_model_client=self.execute_model_client,
            debug_model_client=self.debug_model_client,
            review_model_client=self.review_model_client,
            enable_research=False,
            parallel_writes=self.parallel_writes,
        ).continue_run(run_id, steps)
        return ResumeResult(result, applied_decisions, created_tasks)

    def _apply_resolved_decisions(
        self,
        agent_dir: Path,
        run_dir: Path,
        run_id: str,
    ) -> tuple[int, int]:
        decisions = self._decisions(run_dir)
        applied_ids = self._applied_decision_ids(run_dir)
        resolved = [
            decision
            for decision in decisions
            if decision["status"] in {"resolved", "defaulted"}
            and decision["decision_id"] not in applied_ids
        ]
        if not resolved:
            return 0, 0

        task_plan_path = run_dir / "task_plan.json"
        task_plan = self.store.read(task_plan_path, "task_board")
        created_tasks = []
        for decision in resolved:
            option = self._selected_option(decision)
            effect = "recorded"
            if self._apply_execution_approval(decision, option, task_plan):
                effect = "execution_approval_applied"
                self._record_decision_applied(run_dir, run_id, decision, option, effect)
                self._record_decision_memory(agent_dir, run_id, decision, option, effect)
                continue
            runtime_request_result = self._apply_runtime_request_decision(
                run_dir,
                decision,
                option,
                task_plan,
            )
            if runtime_request_result:
                runtime_request_effect, runtime_request_evidence = runtime_request_result
                self._record_decision_applied(
                    run_dir=run_dir,
                    run_id=run_id,
                    decision=decision,
                    option=option,
                    effect=runtime_request_effect,
                    evidence=runtime_request_evidence,
                )
                self._record_decision_memory(
                    agent_dir,
                    run_id,
                    decision,
                    option,
                    runtime_request_effect,
                )
                continue
            quality_gate_task = self._apply_task_plan_quality_gate(
                decision,
                option,
                task_plan,
                run_id,
            )
            if quality_gate_task:
                created_tasks.append(quality_gate_task)
                effect = "task_plan_revision_task_created"
                self._record_decision_applied(run_dir, run_id, decision, option, effect)
                self._record_decision_memory(agent_dir, run_id, decision, option, effect)
                continue
            if self._records_task_plan_quality_bypass(decision, option):
                effect = "task_plan_quality_bypass_recorded"
                self._record_decision_applied(run_dir, run_id, decision, option, effect)
                self._record_decision_memory(agent_dir, run_id, decision, option, effect)
                continue
            if option and self._should_create_task(option):
                task = self._task_from_decision(decision, option, task_plan["tasks"], run_id)
                self.validator.validate("task", task)
                task_plan["tasks"].append(task)
                created_tasks.append(task)
                effect = (
                    "replan_task_created"
                    if self._option_action(option) == "require_replan"
                    else "task_created"
                )
            elif option and self._option_action(option) == "cancel_scope":
                effect = "scope_cancelled"
            elif option and self._option_action(option) == "record_constraint":
                effect = "constraint_recorded"
            self._record_decision_applied(run_dir, run_id, decision, option, effect)
            self._record_decision_memory(agent_dir, run_id, decision, option, effect)

        self._promote_ready_tasks(task_plan)
        self.store.write(task_plan_path, task_plan, "task_board")
        self.store.write(agent_dir / "tasks" / "backlog.json", task_plan, "task_board")
        return len(resolved), len(created_tasks)

    def _apply_task_plan_quality_gate(
        self,
        decision: dict,
        option: dict | None,
        task_plan: dict,
        run_id: str,
    ) -> dict | None:
        metadata = decision.get("metadata") or {}
        if metadata.get("kind") != "task_plan_quality_gate":
            return None
        if not option or self._option_action(option) != "require_replan":
            return None
        task = self._task_plan_revision_task(decision, option, task_plan["tasks"], run_id)
        self.validator.validate("task", task)
        self._sequence_active_tasks_after_quality_revision(task_plan["tasks"], task["task_id"])
        task_plan["tasks"].append(task)
        return task

    def _records_task_plan_quality_bypass(self, decision: dict, option: dict | None) -> bool:
        metadata = decision.get("metadata") or {}
        return (
            metadata.get("kind") == "task_plan_quality_gate"
            and option is not None
            and self._option_action(option) == "record_constraint"
        )

    def _task_plan_revision_task(
        self,
        decision: dict,
        option: dict,
        existing_tasks: list[dict],
        run_id: str,
    ) -> dict:
        next_index = self._next_task_index(existing_tasks)
        task_plan_path = f".agent/runs/{run_id}/task_plan.json"
        task_plan_eval_path = f".agent/runs/{run_id}/task_plan_eval.json"
        issue_codes = ", ".join(
            str(code) for code in (decision.get("metadata") or {}).get("issue_codes", [])
        )
        description = (
            f"Revise the task plan blocked by quality gate `{decision['decision_id']}`.\n"
            f"Question: {decision['question']}\n"
            f"Selected option: {option['label']}.\n"
            f"Quality issues: {issue_codes or 'see task_plan_eval.json'}.\n"
            "Update the task plan so work is concrete, sequenced, and verifiable before "
            "implementation tasks run."
        )
        return {
            "schema_version": "0.1.0",
            "task_id": f"task-{next_index:04d}",
            "title": "Revise failed task plan before execution",
            "description": description,
            "status": "ready",
            "priority": "high",
            "role": "PlannerAgent",
            "depends_on": [],
            "acceptance": [
                "task_plan.json is updated to address the recorded quality gate issues",
                "Implementation tasks have concrete expected artifacts and allowed write tools",
                "The updated plan can be re-evaluated to pass or warn before execution",
            ],
            "allowed_tools": [
                "read_file",
                "search_text",
                "write_file",
                "apply_patch",
                "restore_backup",
                "run_command",
                "run_tests",
            ],
            "expected_artifacts": [task_plan_path, task_plan_eval_path],
            "task_kind": "implementation",
            "expected_changed_files": [task_plan_path, task_plan_eval_path],
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": f"Generated from task plan quality decision {decision['decision_id']}",
            "completion_contract": {
                "requires_changed_artifact": True,
                "requires_verification": False,
                "allows_expected_failure": False,
            },
            "verification_policy": {
                "required": False,
                "allow_expected_failure": False,
                "commands": [],
            },
        }

    def _sequence_active_tasks_after_quality_revision(
        self,
        tasks: list[dict],
        revision_task_id: str,
    ) -> None:
        for task in tasks:
            if task["status"] not in {"ready", "backlog"}:
                continue
            depends_on = list(task.get("depends_on", []))
            if revision_task_id not in depends_on:
                depends_on.insert(0, revision_task_id)
            task["depends_on"] = depends_on
            if task["status"] == "ready":
                task["status"] = "backlog"
            task["updated_at"] = now_iso()

    def _apply_execution_approval(
        self,
        decision: dict,
        option: dict | None,
        task_plan: dict,
    ) -> bool:
        metadata = decision.get("metadata") or {}
        if metadata.get("kind") != "execution_policy_approval":
            return False
        if not option or option["option_id"] != "approve_once":
            return True
        task_id = str(metadata.get("task_id") or "")
        for task in task_plan["tasks"]:
            if task["task_id"] == task_id and task["status"] == "blocked":
                task["status"] = "ready"
                task["notes"] = f"Approved one-time execution via {decision['decision_id']}."
                task["updated_at"] = now_iso()
                return True
        return True

    def _apply_runtime_request_decision(
        self,
        run_dir: Path,
        decision: dict,
        option: dict | None,
        task_plan: dict,
    ) -> tuple[str, dict] | None:
        metadata = decision.get("metadata") or {}
        if metadata.get("kind") != "runtime_request":
            return None
        if not option or option["option_id"] == "reject_request":
            return "runtime_request_rejected", self._runtime_request_resume_evidence(run_dir, metadata)
        requests = self._runtime_requests_by_id(
            run_dir,
            [str(item) for item in metadata.get("runtime_request_ids", []) if item],
        )
        if not requests:
            return "runtime_request_missing", self._runtime_request_resume_evidence(run_dir, metadata)
        task_id = str(metadata.get("task_id") or "")
        task = self._find_task(task_plan, task_id)
        if task is None:
            return "runtime_request_task_missing", self._runtime_request_resume_evidence(run_dir, metadata)
        resume_evidence = self._runtime_request_resume_evidence(run_dir, metadata)
        applied_request_ids = []
        for request in requests:
            if self._apply_runtime_request_to_task(task, request):
                applied_request_ids.append(request["runtime_request_id"])
        if applied_request_ids and task["status"] == "blocked":
            task["status"] = "ready"
        if applied_request_ids:
            evidence_summary = resume_evidence.get("summary") or {}
            latest_worker = resume_evidence.get("latest_worker_result") or {}
            task["notes"] = (
                f"Runtime request approved via {decision['decision_id']}: "
                f"{', '.join(applied_request_ids)}. "
                "Recovered from Runtime OS evidence "
                f"(worker={latest_worker.get('worker_result_id') or 'none'}, "
                f"blocked={evidence_summary.get('blocked_execution_count', 0)}, "
                f"pending_requests={evidence_summary.get('pending_runtime_request_count', 0)})."
            )
            task["updated_at"] = now_iso()
            self.validator.validate("task", task)
            return "runtime_request_applied", resume_evidence
        return "runtime_request_recorded", resume_evidence

    def _runtime_request_resume_evidence(self, run_dir: Path, metadata: dict) -> dict:
        task_id = str(metadata.get("task_id") or "")
        evidence = self.runtime_evidence.task_evidence(run_dir, task_id) if task_id else {}
        request_ids = [str(item) for item in metadata.get("runtime_request_ids", []) if item]
        runtime_requests = [
            request
            for request in evidence.get("runtime_requests", [])
            if request.get("runtime_request_id") in request_ids
        ]
        worker_results = evidence.get("worker_results") or []
        task_execution = evidence.get("task_execution_evidence") or []
        return {
            "task_id": task_id,
            "runtime_request_ids": request_ids,
            "runtime_requests": runtime_requests[-5:],
            "latest_worker_result": worker_results[-1] if worker_results else {},
            "latest_task_execution_evidence": task_execution[-1] if task_execution else {},
            "summary": evidence.get("summary") or {},
        }

    def _runtime_requests_by_id(self, run_dir: Path, request_ids: list[str]) -> list[dict]:
        path = run_dir / "runtime_requests.jsonl"
        if not path.exists() or not request_ids:
            return []
        wanted = set(request_ids)
        return [
            request
            for request in self.jsonl.read_all(path, "runtime_request")
            if request["runtime_request_id"] in wanted
        ]

    def _find_task(self, task_plan: dict, task_id: str) -> dict | None:
        for task in task_plan["tasks"]:
            if task["task_id"] == task_id:
                return task
        return None

    def _apply_runtime_request_to_task(self, task: dict, request: dict) -> bool:
        request_type = request["request_type"]
        raw_details = request.get("details")
        details: dict = raw_details if isinstance(raw_details, dict) else {}
        if request_type == "scope_expansion":
            changed = False
            changed |= self._merge_list_field(
                task,
                "read_scope",
                self._detail_list(details, "read_scope", "requested_read_scope"),
            )
            changed |= self._merge_list_field(
                task,
                "write_scope",
                self._detail_list(details, "write_scope", "requested_write_scope"),
            )
            return changed
        if request_type == "context_request":
            changed = self._merge_list_field(
                task,
                "read_scope",
                self._detail_list(details, "read_scope", "requested_read_scope", "paths"),
            )
            context_requirements = dict(task.get("context_requirements") or {})
            requested = details.get("context_requirements") if isinstance(details, dict) else {}
            if not isinstance(requested, dict):
                requested = details
            if requested:
                context_requirements.update(requested)
                task["context_requirements"] = context_requirements
                changed = True
            return changed
        if request_type == "tool_request":
            tools = self._detail_list(details, "allowed_tools", "tools", "tool", "tool_name")
            return self._merge_list_field(task, "allowed_tools", tools)
        if request_type == "budget_request":
            hints = dict(task.get("runtime_profile_hints") or {})
            hints["budget"] = details
            task["runtime_profile_hints"] = hints
            return True
        if request_type == "model_upgrade_request":
            hints = dict(task.get("runtime_profile_hints") or {})
            hints["model"] = details
            task["runtime_profile_hints"] = hints
            return True
        if request_type == "decision_request":
            return False
        return False

    def _detail_list(self, details: dict, *keys: str) -> list[str]:
        values: list[str] = []
        for key in keys:
            value = details.get(key)
            if isinstance(value, list):
                values.extend(str(item) for item in value if item)
            elif value:
                values.append(str(value))
        return values

    def _merge_list_field(self, task: dict, field: str, values: list[str]) -> bool:
        if not values:
            return False
        existing = [str(item) for item in task.get(field, []) if item]
        merged = list(dict.fromkeys([*existing, *values]))
        if merged == existing:
            return False
        task[field] = merged
        return True

    def _task_from_decision(
        self,
        decision: dict,
        option: dict,
        existing_tasks: list[dict],
        run_id: str,
    ) -> dict:
        next_index = self._next_task_index(existing_tasks)
        dependency = self._last_active_task_id(existing_tasks)
        selected = decision["selected_option_id"] or decision["default_option_id"]
        description = (
            f"Implement accepted decision `{decision['decision_id']}`.\n"
            f"Question: {decision['question']}\n"
            f"Selected option: {option['label']} ({selected}).\n"
            f"Action: {self._option_action(option)}.\n"
            f"Tradeoff: {option['tradeoff']}"
        )
        role = "PlannerAgent" if self._option_action(option) == "require_replan" else "CoderAgent"
        expected_artifacts = self._decision_expected_artifacts(decision, option, run_id)
        expected_changed_files = [
            artifact
            for artifact in expected_artifacts
            if artifact and not artifact.startswith(".agent/")
        ]
        task_kind = "decision" if self._option_action(option) == "require_replan" else "implementation"
        return {
            "schema_version": "0.1.0",
            "task_id": f"task-{next_index:04d}",
            "title": self._title(self._task_title(option)),
            "description": description,
            "status": "ready" if dependency is None else "backlog",
            "priority": self._priority(decision["impact"]),
            "role": role,
            "depends_on": [] if dependency is None else [dependency],
            "acceptance": [
                f"Accepted decision is reflected in the implementation: {option['label']}"
            ],
            "allowed_tools": [
                "read_file",
                "search_text",
                "write_file",
                "apply_patch",
                "restore_backup",
                "run_command",
                "run_tests",
            ],
            "expected_artifacts": expected_artifacts,
            "task_kind": task_kind,
            "expected_changed_files": expected_changed_files,
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": f"Generated from resolved decision {decision['decision_id']}",
            "completion_contract": {
                "requires_changed_artifact": bool(expected_changed_files),
                "requires_verification": bool(expected_changed_files),
                "allows_expected_failure": False,
            },
            "verification_policy": {
                "required": bool(expected_changed_files),
                "allow_expected_failure": False,
                "commands": [],
            },
            "read_scope": list(dict.fromkeys(["AGENTS.md", *expected_artifacts])),
            "write_scope": expected_changed_files,
            "context_requirements": {
                "mount_type": "coding_context" if expected_changed_files else "summary_context",
                "include_artifacts": True,
                "include_failures": False,
                "include_decisions": True,
                "include_validation": False,
                "recent_event_count": 20,
            },
            "validation_commands": [],
            "failure_policy": "create_repair_task",
            "parallel_safety": "serial" if expected_changed_files else "readonly",
            "merge_strategy": "none",
        }

    def _decision_expected_artifacts(self, decision: dict, option: dict, run_id: str) -> list[str]:
        if self._option_action(option) == "require_replan":
            return [f".agent/runs/{run_id}/task_plan.json"]
        explicit = option.get("expected_artifacts")
        if isinstance(explicit, list):
            artifacts = [str(item) for item in explicit if item]
            if artifacts:
                return artifacts
        metadata = decision.get("metadata") or {}
        metadata_artifacts = metadata.get("expected_artifacts")
        if isinstance(metadata_artifacts, list):
            artifacts = [str(item) for item in metadata_artifacts if item]
            if artifacts:
                return artifacts
        text = " ".join(
            [
                str(decision.get("question") or ""),
                str(option.get("label") or ""),
                str(option.get("tradeoff") or ""),
                str(option.get("option_id") or ""),
            ]
        ).lower()
        if "web ui" in text or "web interface" in text:
            return ["WEB_UI.md"]
        if "readme" in text:
            return ["README.md"]
        return []

    def _should_create_task(self, option: dict) -> bool:
        return self._option_action(option) in self._TASK_ACTIONS

    def _task_title(self, option: dict) -> str:
        if self._option_action(option) == "require_replan":
            return f"Replan from decision: {option['label']}"
        return f"Implement decision: {option['label']}"

    def _option_action(self, option: dict) -> str:
        action = str(option.get("action") or "").strip()
        if action in {"create_task", "record_constraint", "cancel_scope", "require_replan"}:
            return action
        option_id = str(option.get("option_id") or "").lower()
        label = str(option.get("label") or "").lower()
        if any(term in option_id or term in label for term in ["defer", "skip", "local_only"]):
            return "record_constraint"
        if any(term in option_id or term in label for term in ["cancel", "reject"]):
            return "cancel_scope"
        if "replan" in option_id or "replan" in label:
            return "require_replan"
        return "create_task"

    def _selected_option(self, decision: dict) -> dict | None:
        selected = decision["selected_option_id"] or decision["default_option_id"]
        for option in decision["options"]:
            if option["option_id"] == selected:
                return option
        return None

    def _promote_ready_tasks(self, task_plan: dict) -> None:
        done = {task["task_id"] for task in task_plan["tasks"] if task["status"] == "done"}
        for task in task_plan["tasks"]:
            if task["status"] == "backlog" and all(dep in done for dep in task["depends_on"]):
                task["status"] = "ready"
                task["updated_at"] = now_iso()

    def _record_decision_applied(
        self,
        run_dir: Path,
        run_id: str,
        decision: dict,
        option: dict | None,
        effect: str,
        evidence: dict | None = None,
    ) -> None:
        selected = decision["selected_option_id"] or decision["default_option_id"]
        EventLogger(run_dir / "events.jsonl", self.validator).record(
            run_id,
            "decision_applied",
            "ResumeCommand",
            f"{decision['decision_id']} -> {selected} ({effect})",
            {
                "decision_id": decision["decision_id"],
                "selected_option_id": selected,
                "label": option["label"] if option else None,
                "action": self._option_action(option) if option else None,
                "effect": effect,
                "runtime_os_evidence": evidence or {},
            },
        )

    def _record_decision_memory(
        self,
        agent_dir: Path,
        run_id: str,
        decision: dict,
        option: dict | None,
        effect: str,
    ) -> None:
        path = agent_dir / "memory" / "decisions.jsonl"
        existing = self.jsonl.read_all(path, "memory_entry") if path.exists() else []
        selected = decision["selected_option_id"] or decision["default_option_id"]
        action = self._option_action(option) if option else "unknown"
        content = (
            f"Decision {decision['decision_id']} resolved with `{selected}`. "
            f"Question: {decision['question']} "
            f"Action: {action}. Effect: {effect}."
        )
        memory = {
            "schema_version": "0.1.0",
            "memory_id": f"memory-{len(existing) + 1:04d}",
            "type": "project_decision",
            "content": content,
            "source": {
                "run_id": run_id,
                "decision_id": decision["decision_id"],
                "selected_option_id": selected,
                "effect": effect,
            },
            "tags": ["decision", action, effect],
            "confidence": 1.0,
            "created_at": now_iso(),
        }
        self.jsonl.append(path, memory, "memory_entry")

    def _reconcile_with_runtime_evidence(self, run_dir: Path, task_plan: dict) -> dict:
        evidence = self.runtime_evidence.run_evidence(run_dir)
        worker_results = evidence.get("worker_results") or []
        task_execution_evidence = evidence.get("task_execution_evidence") or []
        if not worker_results and not task_execution_evidence:
            return {"reconciled": False, "reason": "no_runtime_os_evidence"}
        succeeded_workers = {
            item["task_id"]: item
            for item in worker_results
            if item.get("status") == "succeeded"
        }
        blocked_evidence = {
            item["task_id"]: item
            for item in task_execution_evidence
            if item.get("status") == "blocked"
        }
        tasks = task_plan.get("tasks") or []
        discrepancies = []
        for task in tasks:
            task_id = task["task_id"]
            plan_status = task.get("status")
            if task_id in succeeded_workers and plan_status != "done":
                discrepancies.append({"task_id": task_id, "plan_status": plan_status, "evidence_status": "done"})
            elif task_id in blocked_evidence and plan_status not in ("blocked", "discarded"):
                discrepancies.append({"task_id": task_id, "plan_status": plan_status, "evidence_status": "blocked"})
        return {
            "reconciled": True,
            "succeeded_worker_count": len(succeeded_workers),
            "blocked_evidence_count": len(blocked_evidence),
            "discrepancies": discrepancies,
            "summary": evidence.get("summary") or {},
        }

    def _pending_decisions(self, run_dir: Path) -> list[dict]:
        return [
            decision for decision in self._decisions(run_dir) if decision["status"] == "pending"
        ]

    def _decisions(self, run_dir: Path) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        return self.jsonl.read_all(path, "decision_point")

    def _applied_decision_ids(self, run_dir: Path) -> set[str]:
        path = run_dir / "events.jsonl"
        if not path.exists():
            return set()
        return {
            str(event.get("data", {}).get("decision_id"))
            for event in self.jsonl.read_all(path, "event")
            if event["type"] == "decision_applied"
        }

    def _latest_run_id(self, agent_dir: Path) -> str | None:
        runs_dir = agent_dir / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted(
            [path for path in runs_dir.iterdir() if path.is_dir()],
            key=lambda item: item.name,
        )
        return runs[-1].name if runs else None

    def _next_task_index(self, tasks: list[dict]) -> int:
        indexes = []
        for task in tasks:
            suffix = task["task_id"].rsplit("-", 1)[-1]
            if suffix.isdigit():
                indexes.append(int(suffix))
        return (max(indexes) + 1) if indexes else 1

    def _last_active_task_id(self, tasks: list[dict]) -> str | None:
        active = [task["task_id"] for task in tasks if task["status"] != "discarded"]
        return active[-1] if active else None

    def _priority(self, impact: dict) -> str:
        if "high" in impact.values():
            return "high"
        if "medium" in impact.values():
            return "medium"
        return "low"

    def _title(self, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) <= 60:
            return trimmed
        return trimmed[:57].rstrip() + "..."
