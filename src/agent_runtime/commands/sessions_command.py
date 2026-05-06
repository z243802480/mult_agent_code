from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.storage.jsonl_store import JsonlStore
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class SessionsResult:
    action: str
    current_session_id: str | None
    sessions: list[dict] = field(default_factory=list)
    context: dict[str, dict] = field(default_factory=dict)

    @property
    def current_run_id(self) -> str | None:
        return self.current_session_id

    @property
    def runs(self) -> list[dict]:
        return self.sessions

    def to_text(self) -> str:
        lines = [
            f"Sessions action: {self.action}",
            f"Current session: {self.current_session_id or 'none'}",
        ]
        for session in self.sessions:
            marker = "*" if session["run_id"] == self.current_session_id else "-"
            lines.append(
                (
                    f"{marker} {session['run_id']} [{session['status']}] "
                    f"{session['current_phase']} - "
                    f"{session.get('summary') or session['entry_command']}"
                )
            )
            context = self.context.get(session["run_id"])
            if context:
                lines.extend(self._context_lines(context))
        return "\n".join(lines)

    def _context_lines(self, context: dict) -> list[str]:
        lines = []
        if context.get("goal_summary"):
            lines.append(f"  goal: {context['goal_summary']}")
        run_status = context.get("run_status") or {}
        if run_status:
            status = run_status.get("status") or "unknown"
            phase = run_status.get("current_phase") or "unknown"
            summary = run_status.get("summary") or "no summary"
            lines.append(f"  status: {status} / {phase} - {summary}")
        if context.get("snapshot_path"):
            lines.append(f"  snapshot: {context['snapshot_path']}")
        if context.get("handoff_path"):
            lines.append(f"  handoff: {context['handoff_path']}")
        if context.get("recommended_next_command"):
            lines.append(f"  next: {context['recommended_next_command']}")
        verification = context.get("verification")
        if verification:
            lines.append(
                (
                    f"  verification: {verification['status']} "
                    f"({verification['platform']}, {verification['created_at']})"
                )
            )
        pending = context.get("pending_decision_count", 0)
        if pending:
            lines.append(f"  pending decisions: {pending}")
        task_summary = context.get("task_summary") or {}
        if task_summary:
            lines.append(
                (
                    f"  tasks: {task_summary.get('remaining', 0)} remaining / "
                    f"{task_summary.get('total', 0)} total"
                )
            )
        cost = context.get("cost_summary") or {}
        if cost:
            lines.append(
                (
                    f"  cost: {cost.get('status', 'unknown')} "
                    f"({cost.get('model_calls', 0)} model, {cost.get('tool_calls', 0)} tool)"
                )
            )
        latest_failure = context.get("latest_task_failure") or {}
        if latest_failure:
            lines.append(
                (
                    f"  latest failure: {latest_failure.get('task_id')} "
                    f"{latest_failure.get('failure_type')} - {latest_failure.get('summary')}"
                )
            )
        blockers = context.get("blockers") or []
        if blockers:
            lines.append(f"  blockers: {'; '.join(blockers[:3])}")
        risks = context.get("risks") or []
        if risks:
            lines.append(f"  risks: {'; '.join(risks[:3])}")
        acceptance_failure_count = int(context.get("acceptance_failure_count", 0))
        if acceptance_failure_count:
            latest = context.get("latest_acceptance_failure") or {}
            scenario = latest.get("scenario") or "unknown"
            lines.append(f"  acceptance failures: {acceptance_failure_count} (latest: {scenario})")
        return lines


class SessionsCommand:
    def __init__(
        self,
        root: Path,
        session_id: str | None = None,
        set_current: bool = False,
        limit: int = 20,
        include_context: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.session_id = session_id
        self.set_current = set_current
        self.limit = limit
        self.include_context = include_context
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)
        self.jsonl = JsonlStore(self.validator)

    def run(self) -> SessionsResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")
        run_store = RunStore(agent_dir, self.validator)
        if self.set_current:
            if not self.session_id:
                raise ValueError("session_id is required when setting current session")
            session = run_store.load_run(self.session_id)
            run_store.set_current_session(self.session_id, "user_selected")
            return SessionsResult(
                "set_current",
                self.session_id,
                [session],
                self._context_for_sessions(agent_dir, [session]),
            )
        current = run_store.current_session_id()
        if self.session_id:
            sessions = [run_store.load_run(self.session_id)]
            return SessionsResult(
                "show",
                current,
                sessions,
                self._context_for_sessions(agent_dir, sessions),
            )
        sessions = run_store.list_sessions()
        if self.limit > 0:
            sessions = sessions[-self.limit :]
        return SessionsResult(
            "list",
            current,
            sessions,
            self._context_for_sessions(agent_dir, sessions),
        )

    def _context_for_sessions(self, agent_dir: Path, sessions: list[dict]) -> dict[str, dict]:
        if not self.include_context:
            return {}
        return {
            session["run_id"]: self._context_for_session(agent_dir, str(session["run_id"]))
            for session in sessions
        }

    def _context_for_session(self, agent_dir: Path, run_id: str) -> dict:
        run_dir = agent_dir / "runs" / run_id
        snapshot = self._latest_snapshot(agent_dir, run_id)
        handoff = self._latest_handoff(agent_dir, snapshot.get("snapshot_id") if snapshot else None)
        snapshot_rel = self._relative_path(snapshot.get("_path")) if snapshot else None
        handoff_rel = self._relative_path(handoff.get("_path")) if handoff else None
        verification = self._latest_verification(agent_dir)
        acceptance_failures = self._acceptance_failures(snapshot, handoff)
        run_status = (snapshot or {}).get("run_status") or self._run_status(run_dir)
        task_summary = (snapshot or {}).get("task_summary") or self._task_summary(run_dir)
        pending_decisions = (snapshot or {}).get("pending_decisions") or self._pending_decisions(
            run_dir
        )
        task_failures = (snapshot or {}).get("task_failures") or self._task_failures(run_dir)
        blockers = self._blockers(run_dir, pending_decisions, task_failures, acceptance_failures)
        risks = (snapshot or {}).get("open_risks") or self._risks(
            run_dir, task_failures, acceptance_failures
        )
        recommended_next_command = (
            (handoff or {}).get("recommended_next_command")
            or self._first_next_action(snapshot)
            or self._recommended_next_command(run_dir, pending_decisions, task_failures, blockers)
        )
        return {
            "goal_summary": (snapshot or {}).get("goal_summary") or self._goal_summary(run_dir),
            "run_status": run_status,
            "snapshot_path": snapshot_rel,
            "handoff_path": handoff_rel,
            "recommended_next_command": recommended_next_command,
            "cost_summary": self._cost_summary(run_dir),
            "verification": verification,
            "pending_decision_count": len(pending_decisions),
            "pending_decisions": pending_decisions,
            "task_summary": task_summary,
            "latest_task_failure": task_failures[-1] if task_failures else None,
            "task_failures": task_failures[-3:],
            "blockers": blockers,
            "risks": risks,
            "acceptance_failure_count": len(acceptance_failures),
            "latest_acceptance_failure": acceptance_failures[-1] if acceptance_failures else None,
            "acceptance_failures": acceptance_failures[-3:],
        }

    def _acceptance_failures(
        self,
        snapshot: dict | None,
        handoff: dict | None,
    ) -> list[dict]:
        failures = []
        if snapshot:
            failures.extend(snapshot.get("acceptance_failures", []))
        if handoff:
            for failure in handoff.get("acceptance_failures", []):
                key = (
                    failure.get("suite"),
                    failure.get("scenario"),
                    failure.get("evidence_path"),
                )
                existing = {
                    (item.get("suite"), item.get("scenario"), item.get("evidence_path"))
                    for item in failures
                }
                if key not in existing:
                    failures.append(failure)
        failures.sort(key=lambda item: str(item.get("created_at") or ""))
        return failures

    def _latest_verification(self, agent_dir: Path) -> dict | None:
        path = agent_dir / "verification" / "latest.json"
        if not path.exists():
            return None
        summary = self.store.read(path, "verification_summary")
        return {
            "status": summary["status"],
            "platform": summary["platform"],
            "created_at": summary["created_at"],
        }

    def _goal_summary(self, run_dir: Path) -> str | None:
        goal_spec = self._read_json(run_dir / "goal_spec.json", "goal_spec")
        if not goal_spec:
            return None
        return str(goal_spec.get("normalized_goal") or goal_spec.get("original_goal") or "")

    def _run_status(self, run_dir: Path) -> dict:
        run = self._read_json(run_dir / "run.json", "run")
        if not run:
            return {}
        return {
            "status": run.get("status"),
            "current_phase": run.get("current_phase"),
            "summary": run.get("summary"),
        }

    def _task_summary(self, run_dir: Path) -> dict:
        task_plan = self._read_json(run_dir / "task_plan.json", "task_board")
        tasks = task_plan.get("tasks", []) if task_plan else []
        by_status: dict[str, int] = {}
        for task in tasks:
            status = str(task.get("status") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "total": len(tasks),
            "by_status": by_status,
            "remaining": sum(
                count for status, count in by_status.items() if status not in {"done", "discarded"}
            ),
        }

    def _cost_summary(self, run_dir: Path) -> dict:
        cost = self._read_json(run_dir / "cost_report.json", "cost_report")
        if not cost:
            return {}
        return {
            "status": cost.get("status", "within_budget"),
            "model_calls": cost.get("model_calls", 0),
            "tool_calls": cost.get("tool_calls", 0),
            "repair_attempts": cost.get("repair_attempts", 0),
            "warnings": cost.get("warnings", []),
        }

    def _pending_decisions(self, run_dir: Path) -> list[dict]:
        decisions = self._read_jsonl(run_dir / "decisions.jsonl", "decision_point")
        return [
            {
                "decision_id": decision["decision_id"],
                "question": decision["question"],
                "recommended_option_id": decision["recommended_option_id"],
            }
            for decision in decisions
            if decision["status"] == "pending"
        ]

    def _task_failures(self, run_dir: Path) -> list[dict]:
        failures = self._read_jsonl(run_dir / "task_failures.jsonl", "task_failure_evidence")
        return [
            {
                "evidence_id": failure["evidence_id"],
                "task_id": failure["task_id"],
                "phase": failure["phase"],
                "failure_type": failure["failure_type"],
                "summary": failure["summary"],
                "recommendations": failure.get("recommendations", [])[:3],
                "evidence_path": (run_dir / "task_failures.jsonl")
                .relative_to(self.root)
                .as_posix(),
                "created_at": failure.get("created_at"),
            }
            for failure in failures[-10:]
        ]

    def _blockers(
        self,
        run_dir: Path,
        pending_decisions: list[dict],
        task_failures: list[dict],
        acceptance_failures: list[dict],
    ) -> list[str]:
        blockers = []
        for decision in pending_decisions[:3]:
            blockers.append(f"pending decision {decision['decision_id']}")
        task_plan = self._read_json(run_dir / "task_plan.json", "task_board")
        blocked_tasks = (
            [task for task in task_plan.get("tasks", []) if str(task.get("status")) == "blocked"]
            if task_plan
            else []
        )
        for task in blocked_tasks[:3]:
            blockers.append(f"blocked task {task['task_id']}: {task['title']}")
        if task_failures:
            latest = task_failures[-1]
            blockers.append(f"latest failure {latest['task_id']}: {latest['failure_type']}")
        if acceptance_failures:
            blockers.append(f"acceptance failure {acceptance_failures[-1]['scenario']}")
        return blockers

    def _risks(
        self,
        run_dir: Path,
        task_failures: list[dict],
        acceptance_failures: list[dict],
    ) -> list[str]:
        risks = []
        cost = self._cost_summary(run_dir)
        if cost and cost.get("status") in {"near_limit", "exceeded", "stopped"}:
            risks.append(f"cost status is {cost['status']}")
        if task_failures:
            risks.append(f"{len(task_failures)} task failure evidence item(s)")
        if acceptance_failures:
            risks.append(f"{len(acceptance_failures)} acceptance failure evidence item(s)")
        warnings = cost.get("warnings", []) if cost else []
        risks.extend(str(warning) for warning in warnings[:2])
        return risks

    def _recommended_next_command(
        self,
        run_dir: Path,
        pending_decisions: list[dict],
        task_failures: list[dict],
        blockers: list[str],
    ) -> str | None:
        if pending_decisions:
            return f"decide --decision-id {pending_decisions[0]['decision_id']}"
        if task_failures or blockers:
            return "debug"
        task_plan = self._read_json(run_dir / "task_plan.json", "task_board")
        tasks = task_plan.get("tasks", []) if task_plan else []
        if any(task.get("status") == "ready" for task in tasks):
            return "execute"
        if tasks and all(task.get("status") in {"done", "discarded"} for task in tasks):
            return "review"
        return None

    def _read_json(self, path: Path, schema_name: str) -> dict:
        if not path.exists():
            return {}
        return self.store.read(path, schema_name)

    def _read_jsonl(self, path: Path, schema_name: str) -> list[dict]:
        if not path.exists():
            return []
        return self.jsonl.read_all(path, schema_name)

    def _latest_snapshot(self, agent_dir: Path, run_id: str) -> dict | None:
        snapshots_dir = agent_dir / "context" / "snapshots"
        matches = []
        for path in self._json_files(snapshots_dir):
            snapshot = self.store.read(path, "context_snapshot")
            if snapshot.get("run_id") == run_id:
                snapshot["_path"] = path
                matches.append(snapshot)
        return self._latest_by_created_at(matches)

    def _latest_handoff(self, agent_dir: Path, snapshot_id: str | None) -> dict | None:
        if not snapshot_id:
            return None
        handoffs_dir = agent_dir / "context" / "handoffs"
        matches = []
        for path in self._json_files(handoffs_dir):
            handoff = self.store.read(path, "handoff_package")
            if handoff.get("snapshot_id") == snapshot_id:
                handoff["_path"] = path
                matches.append(handoff)
        return self._latest_by_created_at(matches)

    def _json_files(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(path for path in directory.glob("*.json") if path.is_file())

    def _latest_by_created_at(self, records: list[dict]) -> dict | None:
        if not records:
            return None
        return sorted(records, key=lambda item: str(item.get("created_at") or ""))[-1]

    def _first_next_action(self, snapshot: dict | None) -> str | None:
        if not snapshot:
            return None
        actions = snapshot.get("next_actions") or []
        return str(actions[0]) if actions else None

    def _relative_path(self, path: Path | None) -> str | None:
        if not path:
            return None
        return path.relative_to(self.root).as_posix()
