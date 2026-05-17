from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.sessions_command import SessionsCommand


@dataclass(frozen=True)
class StatusResult:
    root: Path
    initialized: bool
    current_session_id: str | None = None
    current_context: dict = field(default_factory=dict)
    recent_sessions: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        blockers = self.current_context.get("blockers") if self.current_context else []
        risks = self.current_context.get("risks") if self.current_context else []
        latest_failure = (
            self.current_context.get("latest_task_failure") if self.current_context else {}
        ) or {}
        candidate_promotions = (
            self.current_context.get("candidate_promotions") if self.current_context else {}
        ) or {}
        recommended = (
            self.current_context.get("recommended_next_command") if self.current_context else None
        )
        return {
            "schema_version": "0.1.0",
            "root": str(self.root),
            "initialized": self.initialized,
            "status": self._status(),
            "summary": self._summary(),
            "current_session_id": self.current_session_id,
            "current_context": self.current_context,
            "blockers": blockers or [],
            "risks": risks or [],
            "pending_decision_count": int(
                self.current_context.get("pending_decision_count", 0) if self.current_context else 0
            ),
            "candidate_promotions": candidate_promotions,
            "latest_failure": latest_failure,
            "recommended_next_command": recommended,
            "next_actions": self._next_actions(recommended),
            "recent_sessions": self.recent_sessions,
        }

    def _status(self) -> str:
        if not self.initialized:
            return "uninitialized"
        if self.current_context.get("pending_decision_count"):
            return "blocked"
        blockers = self.current_context.get("blockers") or []
        if blockers:
            return "blocked"
        if self.current_session_id:
            return "active"
        return "idle"

    def _summary(self) -> str:
        if not self.initialized:
            return "Workspace is not initialized."
        if not self.current_session_id:
            return "Workspace is initialized with no current session."
        run_status = self.current_context.get("run_status") or {}
        return str(run_status.get("summary") or "Current session is available.")

    def _next_actions(self, recommended: str | None) -> list[str]:
        if not self.initialized:
            return ["Run `asteria /init --root .`."]
        if recommended:
            return [f"Run `asteria {recommended}`."]
        if not self.current_session_id:
            return ['Run `asteria /new "<goal>" --root .`.']
        return ["Run `asteria /sessions --context --root .` to inspect current state."]

    def to_text(self) -> str:
        lines = [
            "Agent status",
            f"Root: {self.root}",
            f"Initialized: {'yes' if self.initialized else 'no'}",
        ]
        if not self.initialized:
            lines.append("Next: asteria init")
            return "\n".join(lines)
        lines.append(f"Current session: {self.current_session_id or 'none'}")
        context = self.current_context
        if context:
            run_status = context.get("run_status") or {}
            task_summary = context.get("task_summary") or {}
            cost = context.get("cost_summary") or {}
            if context.get("goal_summary"):
                lines.append(f"Goal: {context['goal_summary']}")
            if run_status:
                lines.append(
                    "Run: "
                    f"{run_status.get('status', 'unknown')} / "
                    f"{run_status.get('current_phase', 'unknown')} - "
                    f"{run_status.get('summary') or 'no summary'}"
                )
            if task_summary:
                lines.append(
                    "Tasks: "
                    f"{task_summary.get('remaining', 0)} remaining / "
                    f"{task_summary.get('total', 0)} total"
                )
            if cost:
                lines.append(
                    "Cost: "
                    f"{cost.get('status', 'unknown')} "
                    f"({cost.get('model_calls', 0)} model, {cost.get('tool_calls', 0)} tool)"
                )
            worker_tree = context.get("worker_tree") or {}
            if worker_tree.get("total_workers"):
                graph = worker_tree.get("agent_run_graph") or {}
                collaboration = worker_tree.get("collaboration_summary") or {}
                modes = collaboration.get("strategy_modes") or []
                lines.append(
                    "Workers: "
                    f"{worker_tree.get('successful_workers', 0)} succeeded / "
                    f"{worker_tree.get('total_workers', 0)} total "
                    f"({worker_tree.get('parallel_batches', 0)} parallel batch, "
                    f"graph={graph.get('status', 'unknown')})"
                )
                if modes:
                    lines.append(f"Worker strategy: {', '.join(str(mode) for mode in modes)}")
            pending = int(context.get("pending_decision_count", 0))
            if pending:
                lines.append(f"Pending decisions: {pending}")
            candidate_promotions = context.get("candidate_promotions") or {}
            if candidate_promotions.get("total"):
                counts = candidate_promotions.get("status_counts") or {}
                lines.append(
                    "Candidate promotions: "
                    f"{candidate_promotions.get('total', 0)} total "
                    f"(pending={len(candidate_promotions.get('pending') or [])}, "
                    f"blocked={len(candidate_promotions.get('blocked') or [])}, "
                    f"promoted={counts.get('promoted', 0)})"
                )
            blockers = context.get("blockers") or []
            if blockers:
                lines.append("Blockers:")
                lines.extend(f"  - {item}" for item in blockers[:5])
            latest_execution = context.get("latest_execution_evidence") or {}
            if latest_execution:
                lines.append(
                    "Latest execution: "
                    f"{latest_execution.get('task_id')} "
                    f"{latest_execution.get('status')} - "
                    f"{latest_execution.get('summary')}"
                )
            if context.get("recommended_next_command"):
                lines.append(f"Next: asteria {context['recommended_next_command']}")
        elif self.recent_sessions:
            lines.append("Recent sessions:")
            for session in self.recent_sessions[-5:]:
                marker = "*" if session["run_id"] == self.current_session_id else "-"
                lines.append(
                    f"{marker} {session['run_id']} [{session['status']}] {session['current_phase']}"
                )
        else:
            lines.append("No sessions yet.")
        return "\n".join(lines)


class StatusCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self) -> StatusResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            return StatusResult(root=self.root, initialized=False)
        sessions = SessionsCommand(
            self.root,
            limit=5,
            include_context=True,
        ).run()
        current_context = (
            sessions.context.get(sessions.current_session_id)
            if sessions.current_session_id
            else None
        )
        return StatusResult(
            root=self.root,
            initialized=True,
            current_session_id=sessions.current_session_id,
            current_context=current_context or {},
            recent_sessions=sessions.sessions,
        )
