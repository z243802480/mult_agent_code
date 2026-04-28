from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class SessionsResult:
    action: str
    current_session_id: str | None
    sessions: list[dict] = field(default_factory=list)

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
        return "\n".join(lines)


class SessionsCommand:
    def __init__(
        self,
        root: Path,
        session_id: str | None = None,
        set_current: bool = False,
        limit: int = 20,
    ) -> None:
        self.root = root.resolve()
        self.session_id = session_id
        self.set_current = set_current
        self.limit = limit
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

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
            return SessionsResult("set_current", self.session_id, [session])
        current = run_store.current_session_id()
        if self.session_id:
            return SessionsResult("show", current, [run_store.load_run(self.session_id)])
        sessions = run_store.list_sessions()
        if self.limit > 0:
            sessions = sessions[-self.limit :]
        return SessionsResult("list", current, sessions)
