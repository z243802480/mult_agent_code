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
