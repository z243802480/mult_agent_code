from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class RunsResult:
    action: str
    current_run_id: str | None
    runs: list[dict] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [f"Runs action: {self.action}", f"Current run: {self.current_run_id or 'none'}"]
        for run in self.runs:
            marker = "*" if run["run_id"] == self.current_run_id else "-"
            lines.append(
                (
                    f"{marker} {run['run_id']} [{run['status']}] "
                    f"{run['current_phase']} - {run.get('summary') or run['entry_command']}"
                )
            )
        return "\n".join(lines)


class RunsCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        set_current: bool = False,
        limit: int = 20,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.set_current = set_current
        self.limit = limit
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> RunsResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")
        run_store = RunStore(agent_dir, self.validator)
        if self.set_current:
            if not self.run_id:
                raise ValueError("run_id is required when setting current run")
            run_store.load_run(self.run_id)
            run_store.set_current_run(self.run_id, "user_selected")
            return RunsResult("set_current", self.run_id, [run_store.load_run(self.run_id)])
        current = run_store.current_run_id()
        if self.run_id:
            return RunsResult("show", current, [run_store.load_run(self.run_id)])
        runs = run_store.list_runs()
        if self.limit > 0:
            runs = runs[-self.limit :]
        return RunsResult("list", current, runs)
