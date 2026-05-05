from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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
        snapshot = self._latest_snapshot(agent_dir, run_id)
        handoff = self._latest_handoff(agent_dir, snapshot.get("snapshot_id") if snapshot else None)
        snapshot_rel = self._relative_path(snapshot.get("_path")) if snapshot else None
        handoff_rel = self._relative_path(handoff.get("_path")) if handoff else None
        verification = self._latest_verification(agent_dir)
        acceptance_failures = self._acceptance_failures(snapshot, handoff)
        return {
            "snapshot_path": snapshot_rel,
            "handoff_path": handoff_rel,
            "recommended_next_command": (handoff or {}).get("recommended_next_command")
            or self._first_next_action(snapshot),
            "verification": verification,
            "pending_decision_count": len((snapshot or {}).get("pending_decisions", [])),
            "task_summary": (snapshot or {}).get("task_summary", {}),
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
