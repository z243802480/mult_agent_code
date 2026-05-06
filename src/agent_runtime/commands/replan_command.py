from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.commands.decide_command import DecideCommand
from agent_runtime.core.task_board import TaskBoard, TaskStateError
from agent_runtime.core.task_contract import completion_contract
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class ReplanResult:
    run_id: str
    created_tasks: int
    created_decisions: int
    superseded_tasks: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    decision_ids: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            f"Replanned run: {self.run_id}",
            f"Created tasks: {self.created_tasks}",
            f"Created decisions: {self.created_decisions}",
        ]
        if self.superseded_tasks:
            lines.append(f"Superseded tasks: {', '.join(self.superseded_tasks)}")
        if self.task_ids:
            lines.append(f"New tasks: {', '.join(self.task_ids)}")
        if self.decision_ids:
            lines.append(f"New decisions: {', '.join(self.decision_ids)}")
        return "\n".join(lines)


class ReplanCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        max_items: int = 2,
        max_replans_per_task: int = 2,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.max_items = max_items
        self.max_replans_per_task = max_replans_per_task
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> ReplanResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")
        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `agent plan` first.")
        run_dir = run_store.run_dir(run_id)
        task_board = TaskBoard(run_dir / "task_plan.json", self.validator)
        event_logger = EventLogger(run_dir / "events.jsonl", self.validator)

        created_task_ids: list[str] = []
        created_decision_ids: list[str] = []
        superseded: list[str] = []
        for evidence in self._candidate_failures(run_dir, task_board)[: self.max_items]:
            task = task_board.get_task(evidence["task_id"])
            if self._replan_count(task_board, task["task_id"]) >= self.max_replans_per_task:
                decision = self._create_decision(run_id, evidence, "repair_limit")
                if decision:
                    created_decision_ids.append(decision["decision_id"])
                continue

            if self._needs_decision(evidence):
                decision = self._create_decision(run_id, evidence, evidence["failure_type"])
                if decision:
                    created_decision_ids.append(decision["decision_id"])
                continue

            new_task = self._task_from_failure(task_board, task, evidence)
            if new_task is None:
                continue
            task_board.add_task(new_task)
            created_task_ids.append(new_task["task_id"])
            self._supersede_task(task_board, evidence["task_id"], new_task["task_id"])
            superseded.append(evidence["task_id"])
            self._rewire_dependents(task_board, evidence["task_id"], new_task["task_id"])
            event_logger.record(
                run_id,
                "task_replanned",
                "ReplanCommand",
                f"{evidence['task_id']} -> {new_task['task_id']}",
                {
                    "source_task_id": evidence["task_id"],
                    "new_task_id": new_task["task_id"],
                    "evidence_id": evidence["evidence_id"],
                    "failure_type": evidence["failure_type"],
                },
            )

        self._mirror_backlog(agent_dir, task_board)
        self._update_run_status(
            run_store, run_id, bool(created_task_ids), bool(created_decision_ids)
        )
        return ReplanResult(
            run_id=run_id,
            created_tasks=len(created_task_ids),
            created_decisions=len(created_decision_ids),
            superseded_tasks=superseded,
            task_ids=created_task_ids,
            decision_ids=created_decision_ids,
        )

    def _candidate_failures(self, run_dir: Path, task_board: TaskBoard) -> list[dict]:
        path = run_dir / "task_failures.jsonl"
        if not path.exists():
            return []
        tasks = {task["task_id"]: task for task in task_board.list_tasks()}
        handled = self._handled_evidence(task_board, run_dir)
        candidates = []
        seen_tasks: set[str] = set()
        for evidence in reversed(self.jsonl.read_all(path, "task_failure_evidence")):
            if evidence["evidence_id"] in handled:
                continue
            if evidence["task_id"] in seen_tasks:
                continue
            task = tasks.get(evidence["task_id"])
            if not task or task["status"] != "blocked":
                continue
            seen_tasks.add(evidence["task_id"])
            candidates.append(evidence)
        return candidates

    def _handled_evidence(self, task_board: TaskBoard, run_dir: Path) -> set[str]:
        handled = set()
        for task in task_board.list_tasks():
            raw_metadata = task.get("replan")
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            if metadata.get("source_evidence_id"):
                handled.add(str(metadata["source_evidence_id"]))
        decisions_path = run_dir / "decisions.jsonl"
        if decisions_path.exists():
            for decision in self.jsonl.read_all(decisions_path, "decision_point"):
                metadata = decision.get("metadata") or {}
                if metadata.get("source_evidence_id"):
                    handled.add(str(metadata["source_evidence_id"]))
        return handled

    def _replan_count(self, task_board: TaskBoard, task_id: str) -> int:
        count = 0
        for task in task_board.list_tasks():
            raw_metadata = task.get("replan")
            metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            if metadata.get("source_task_id") == task_id:
                count += 1
        return count

    def _needs_decision(self, evidence: dict) -> bool:
        return evidence["failure_type"] in {
            "policy_decision",
            "tool_permission",
            "repair_exception",
            "exception",
        }

    def _create_decision(self, run_id: str, evidence: dict, reason: str) -> dict | None:
        question = (
            f"Task {evidence['task_id']} is still blocked after {reason}. "
            "Should the runtime create another repair task or keep the task blocked for manual review?"
        )
        options = [
            {
                "option_id": "create_repair_task",
                "label": "Create repair task",
                "tradeoff": "Spend another small iteration to repair the blocked task.",
                "action": "require_replan",
            },
            {
                "option_id": "manual_review",
                "label": "Manual review",
                "tradeoff": "Stop automatic iteration and keep the current evidence for user inspection.",
                "action": "record_constraint",
            },
        ]
        result = DecideCommand(
            self.root,
            run_id=run_id,
            question=question,
            options_json=json.dumps(options, ensure_ascii=False),
            recommended_option_id="manual_review",
            default_option_id="manual_review",
            impact_json=json.dumps(
                {"scope": "medium", "budget": "medium", "risk": "medium", "quality": "high"},
                ensure_ascii=False,
            ),
            metadata={
                "kind": "replan_decision",
                "source_evidence_id": evidence["evidence_id"],
                "source_task_id": evidence["task_id"],
                "reason": reason,
            },
        ).run()
        return result.decisions[0] if result.decisions else None

    def _task_from_failure(
        self,
        task_board: TaskBoard,
        source_task: dict,
        evidence: dict,
    ) -> dict | None:
        task_id = self._next_task_id(task_board)
        contract_check = evidence.get("contract_check") or {}
        violations = [str(item) for item in contract_check.get("violations", [])]
        title = self._title(source_task, evidence, violations)
        description = self._description(source_task, evidence, violations)
        expected_artifacts = self._expected_artifacts(source_task, contract_check)
        task = {
            "schema_version": "0.1.0",
            "task_id": task_id,
            "title": title,
            "description": description,
            "status": "ready",
            "priority": source_task.get("priority", "high"),
            "role": "CoderAgent",
            "depends_on": self._done_dependencies(task_board),
            "acceptance": self._acceptance(evidence, violations),
            "allowed_tools": source_task["allowed_tools"],
            "expected_artifacts": expected_artifacts,
            "task_kind": "implementation",
            "expected_changed_files": contract_check.get("expected_changed_files", []),
            "assigned_agent_id": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "notes": (
                f"Replanned from {source_task['task_id']} using "
                f"{evidence['evidence_id']}: {evidence['summary']}"
            ),
            "replan": {
                "source_task_id": source_task["task_id"],
                "source_evidence_id": evidence["evidence_id"],
                "failure_type": evidence["failure_type"],
            },
        }
        task["completion_contract"] = completion_contract(task)
        task["verification_policy"] = {
            "required": True,
            "allow_expected_failure": False,
            "commands": [],
        }
        return task

    def _title(self, source_task: dict, evidence: dict, violations: list[str]) -> str:
        if "required verification was not provided" in violations:
            return f"Add verification for {source_task['task_id']}"
        if any(item.startswith("expected changed files were not modified") for item in violations):
            return f"Modify expected artifact for {source_task['task_id']}"
        return f"Repair replanned task for {source_task['task_id']}"

    def _description(self, source_task: dict, evidence: dict, violations: list[str]) -> str:
        recommendations = evidence.get("recommendations", [])
        parts = [
            f"Repair the blocked task '{source_task['title']}'.",
            f"Failure summary: {evidence['summary']}",
        ]
        if violations:
            parts.append("Contract violations: " + "; ".join(violations))
        if recommendations:
            parts.append(
                "Recommended repair: " + " ".join(str(item) for item in recommendations[:3])
            )
        return "\n".join(parts)

    def _expected_artifacts(self, source_task: dict, contract_check: dict) -> list[str]:
        expected_files = [
            str(item)
            for item in contract_check.get("expected_changed_files", [])
            if str(item).strip()
        ]
        if expected_files:
            return expected_files
        return [str(item) for item in source_task.get("expected_artifacts", [])]

    def _acceptance(self, evidence: dict, violations: list[str]) -> list[str]:
        acceptance = ["Original task acceptance criteria are satisfied"]
        if "required verification was not provided" in violations:
            acceptance.append("A verification command directly proves the repair")
        if "verification did not pass" in violations:
            acceptance.append("The previously failing verification passes")
        if "required changed artifact was not produced" in violations:
            acceptance.append("A concrete artifact is created or modified")
        if any(item.startswith("expected changed files were not modified") for item in violations):
            acceptance.append("At least one expected changed file is modified")
        return list(dict.fromkeys(acceptance))

    def _supersede_task(
        self, task_board: TaskBoard, task_id: str, replacement_task_id: str
    ) -> None:
        try:
            task_board.update_notes(task_id, f"Superseded by {replacement_task_id} during replan.")
            task_board.update_status(task_id, "discarded")
        except TaskStateError:
            return

    def _rewire_dependents(
        self,
        task_board: TaskBoard,
        source_task_id: str,
        replacement_task_id: str,
    ) -> None:
        data = task_board._load()  # noqa: SLF001 - replan must update dependency graph atomically
        changed = False
        for task in data["tasks"]:
            depends_on = task.get("depends_on", [])
            if source_task_id not in depends_on:
                continue
            task["depends_on"] = [
                replacement_task_id if dep == source_task_id else dep for dep in depends_on
            ]
            task["updated_at"] = now_iso()
            changed = True
        if changed:
            task_board._save(data)  # noqa: SLF001

    def _done_dependencies(self, task_board: TaskBoard) -> list[str]:
        tasks = task_board.list_tasks()
        done = [task["task_id"] for task in tasks if task["status"] == "done"]
        return done[-1:] if done else []

    def _next_task_id(self, task_board: TaskBoard) -> str:
        indexes = []
        for task in task_board.list_tasks():
            suffix = task["task_id"].rsplit("-", 1)[-1]
            if suffix.isdigit():
                indexes.append(int(suffix))
        return f"task-{(max(indexes) + 1) if indexes else 1:04d}"

    def _mirror_backlog(self, agent_dir: Path, task_board: TaskBoard) -> None:
        self.store.write(
            agent_dir / "tasks" / "backlog.json",
            {"schema_version": "0.1.0", "tasks": task_board.list_tasks()},
            "task_board",
        )

    def _update_run_status(
        self,
        run_store: RunStore,
        run_id: str,
        created_tasks: bool,
        created_decisions: bool,
    ) -> None:
        run = run_store.load_run(run_id)
        if created_decisions:
            run["status"] = "paused"
            run["current_phase"] = "DECISION"
            run["summary"] = "Replan paused for a user decision."
        elif created_tasks:
            run["status"] = "running"
            run["current_phase"] = "REPLAN"
            run["summary"] = "Replan created repair tasks."
        else:
            run["status"] = "blocked"
            run["summary"] = "Replan found no actionable task failure evidence."
        run_store.update_run(run)
