from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_runtime.commands.compact_command import CompactCommand
from agent_runtime.storage.event_logger import EventLogger
from agent_runtime.storage.json_store import JsonStore
from agent_runtime.storage.run_store import RunStore
from agent_runtime.storage.schema_validator import SchemaValidator
from agent_runtime.utils.time import now_iso


@dataclass(frozen=True)
class HandoffResult:
    run_id: str
    handoff_path: Path
    snapshot_path: Path
    to_role: str
    recommended_next_command: str

    def to_text(self) -> str:
        return "\n".join(
            [
                f"Created handoff package: {self.handoff_path}",
                f"Run: {self.run_id}",
                f"Target role: {self.to_role}",
                f"Snapshot: {self.snapshot_path}",
                f"Recommended next command: {self.recommended_next_command}",
            ]
        )


class HandoffCommand:
    def __init__(
        self,
        root: Path,
        run_id: str | None = None,
        to_role: str = "FutureRun",
        from_agent_id: str | None = None,
        recommended_next_command: str | None = None,
        focus: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.run_id = run_id
        self.to_role = to_role
        self.from_agent_id = from_agent_id
        self.recommended_next_command = recommended_next_command
        self.focus = focus
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> HandoffResult:
        agent_dir = self.root / ".agent"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `agent init` first.")

        run_store = RunStore(agent_dir, self.validator)
        run_id = self.run_id or run_store.current_session_id()
        if not run_id:
            raise RuntimeError("No run found. Run `agent run` first.")
        run_dir = run_store.run_dir(run_id)
        if not run_dir.exists():
            raise RuntimeError(f"Run not found: {run_id}")

        focus = self.focus or f"handoff for {self.to_role}"
        compact = CompactCommand(self.root, run_id=run_id, focus=focus).run()
        snapshot = self.store.read(compact.snapshot_path, "context_snapshot")
        handoff = self._build_handoff(run_dir, snapshot)

        handoffs_dir = agent_dir / "context" / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        handoff_path = handoffs_dir / f"{handoff['handoff_id']}.json"
        self.store.write(handoff_path, handoff, "handoff_package")

        EventLogger(run_dir / "events.jsonl", self.validator).record(
            run_id,
            "artifact_created",
            "HandoffCommand",
            f"Created handoff package for {self.to_role}",
            {
                "path": str(handoff_path.relative_to(self.root)),
                "snapshot_id": snapshot["snapshot_id"],
                "to_role": self.to_role,
            },
        )
        return HandoffResult(
            run_id=run_id,
            handoff_path=handoff_path,
            snapshot_path=compact.snapshot_path,
            to_role=self.to_role,
            recommended_next_command=handoff["recommended_next_command"],
        )

    def _build_handoff(self, run_dir: Path, snapshot: dict) -> dict:
        handoff_id = f"handoff-{now_iso().replace(':', '').replace('-', '').replace('+', '-')}"
        return {
            "schema_version": "0.1.0",
            "handoff_id": handoff_id,
            "from_agent_id": self.from_agent_id,
            "to_role": self.to_role,
            "snapshot_id": snapshot["snapshot_id"],
            "current_task_ids": snapshot.get("active_tasks", []),
            "recent_artifacts": self._recent_artifacts(run_dir, snapshot),
            "known_risks": snapshot.get("open_risks", []),
            "run_status": snapshot.get("run_status", {}),
            "task_summary": snapshot.get("task_summary", {}),
            "pending_decisions": snapshot.get("pending_decisions", []),
            "verification_summary": snapshot.get("verification_summary", {}),
            "acceptance_failures": snapshot.get("acceptance_failures", []),
            "report_summaries": snapshot.get("report_summaries", {}),
            "recommended_next_command": self._recommended_next_command(snapshot),
            "created_at": now_iso(),
        }

    def _recent_artifacts(self, run_dir: Path, snapshot: dict) -> list[str]:
        artifacts: list[str] = []
        for item in snapshot.get("recent_artifacts", []):
            artifact_path = str(item.get("path") or "").strip()
            if artifact_path and artifact_path not in artifacts:
                artifacts.append(artifact_path)
        for item in snapshot.get("modified_files", []):
            artifact_path = str(item.get("path") or "").strip()
            if artifact_path and artifact_path not in artifacts:
                artifacts.append(artifact_path)
        for item in snapshot.get("acceptance_failures", []):
            artifact_path = str(item.get("evidence_path") or "").strip()
            if artifact_path and artifact_path not in artifacts:
                artifacts.append(artifact_path)
        for filename in ("goal_spec.json", "task_plan.json", "review_report.md", "final_report.md"):
            file_path = run_dir / filename
            if file_path.exists():
                relative = str(file_path.relative_to(self.root))
                if relative not in artifacts:
                    artifacts.append(relative)
        return artifacts[:20]

    def _recommended_next_command(self, snapshot: dict) -> str:
        if self.recommended_next_command:
            return self.recommended_next_command
        pending = snapshot.get("pending_decisions") or []
        if pending:
            return f"decide --decision-id {pending[0]['decision_id']}"
        if snapshot.get("acceptance_failures"):
            return "debug"
        if snapshot.get("failures"):
            return "debug"
        task_summary = snapshot.get("task_summary") or {}
        by_status = task_summary.get("by_status") or {}
        if int(by_status.get("blocked", 0)):
            return "debug"
        if int(by_status.get("ready", 0)) or int(by_status.get("in_progress", 0)):
            return "execute"
        if task_summary.get("total") and not int(task_summary.get("remaining", 0)):
            return "review"
        return "review"
