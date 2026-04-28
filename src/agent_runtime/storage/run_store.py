from __future__ import annotations

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


class RunStore:
    def __init__(self, agent_dir: Path, validator: SchemaValidator | None = None) -> None:
        self.agent_dir = agent_dir
        self.runs_dir = self.agent_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.store = JsonStore(validator)

    def create_run(self, entry_command: str, goal_id: str | None = None) -> dict:
        run_id = self._next_run_id()
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        run = {
            "schema_version": "0.1.0",
            "run_id": run_id,
            "goal_id": goal_id,
            "status": "running",
            "started_at": now_iso(),
            "ended_at": None,
            "entry_command": entry_command,
            "current_phase": "INIT",
            "workspace": {
                "mode": "single_workspace",
                "path": "."
            },
            "summary": "",
        }
        self.store.write(run_dir / "run.json", run, "run")
        return run

    def load_run(self, run_id: str) -> dict:
        return self.store.read(self.run_dir(run_id) / "run.json", "run")

    def update_run(self, run: dict) -> None:
        self.store.write(self.run_dir(run["run_id"]) / "run.json", run, "run")

    def set_current_session(self, session_id: str, reason: str) -> dict:
        current = {
            "schema_version": "0.1.0",
            "session_id": session_id,
            "set_at": now_iso(),
            "reason": reason,
        }
        self.store.write(self.agent_dir / "current_session.json", current, "current_session")
        return current

    def set_current_run(self, run_id: str, reason: str) -> dict:
        return self.set_current_session(run_id, reason)

    def current_session_id(self) -> str | None:
        path = self.agent_dir / "current_session.json"
        if path.exists():
            current = self.store.read(path, "current_session")
            session_id = str(current["session_id"])
            if (self.run_dir(session_id) / "run.json").exists():
                return session_id
            return self.latest_run_id()
        legacy_path = self.agent_dir / "current_run.json"
        if legacy_path.exists():
            current = self.store.read(legacy_path, "current_run")
            run_id = str(current["run_id"])
            if (self.run_dir(run_id) / "run.json").exists():
                return run_id
            return self.latest_run_id()
        return self.latest_run_id()

    def current_run_id(self) -> str | None:
        return self.current_session_id()

    def current_session_path(self) -> Path:
        return self.agent_dir / "current_session.json"

    def current_run_path(self) -> Path:
        return self.current_session_path()

    def latest_session_id(self) -> str | None:
        return self.latest_run_id()

    def list_sessions(self) -> list[dict]:
        return self.list_runs()

    def session_dir(self, session_id: str) -> Path:
        return self.run_dir(session_id)

    def latest_run_id(self) -> str | None:
        runs = self.list_runs()
        return runs[-1]["run_id"] if runs else None

    def list_runs(self) -> list[dict]:
        if not self.runs_dir.exists():
            return []
        runs = []
        for path in sorted(self.runs_dir.iterdir(), key=lambda item: item.name):
            if path.is_dir() and (path / "run.json").exists():
                runs.append(self.store.read(path / "run.json", "run"))
        return runs

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def _next_run_id(self) -> str:
        date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        existing = []
        for path in self.runs_dir.glob(f"run-{date}-*"):
            suffix = path.name.rsplit("-", 1)[-1]
            if suffix.isdigit():
                existing.append(int(suffix))
        return f"run-{date}-{(max(existing) + 1 if existing else 1):04d}"
