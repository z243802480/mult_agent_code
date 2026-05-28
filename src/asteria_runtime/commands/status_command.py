from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.commands.sessions_command import SessionsCommand
from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.plugin_diagnostics import plugin_control_summary
from asteria_runtime.core.real_provider_matrix import (
    latest_real_provider_matrix,
    real_provider_matrix_text_lines,
)
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class StatusResult:
    root: Path
    initialized: bool
    current_session_id: str | None = None
    current_context: dict = field(default_factory=dict)
    recent_sessions: list[dict] = field(default_factory=list)
    plugin_control: dict = field(default_factory=dict)
    latest_real_provider_matrix: dict = field(default_factory=dict)
    active_goal_memory_path: Path | None = None
    active_goal_memory: str = ""
    active_goal_state: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        blockers = self.current_context.get("blockers") if self.current_context else []
        risks = self.current_context.get("risks") if self.current_context else []
        latest_failure = (
            self.current_context.get("latest_task_failure") if self.current_context else {}
        ) or {}
        candidate_promotions = (
            self.current_context.get("candidate_promotions") if self.current_context else {}
        ) or {}
        route_health = (
            self.current_context.get("route_health") if self.current_context else {}
        ) or {}
        model_selection = (
            self.current_context.get("model_selection") if self.current_context else {}
        ) or {}
        latest_model_progress = (
            self.current_context.get("latest_model_progress") if self.current_context else {}
        ) or {}
        workspace_envelope = (
            self.current_context.get("workspace_envelope") if self.current_context else {}
        ) or {}
        model_route_timeline = (
            self.current_context.get("model_route_timeline") if self.current_context else []
        ) or []
        run_loop_summary = (
            self.current_context.get("run_loop_summary") if self.current_context else {}
        ) or {}
        run_loop_summary_path = (
            self.current_context.get("run_loop_summary_path") if self.current_context else None
        )
        final_report_summary = (
            self.current_context.get("final_report_summary") if self.current_context else {}
        ) or {}
        final_report_summary_path = (
            self.current_context.get("final_report_summary_path") if self.current_context else None
        )
        goal_policy = self.current_context.get("goal_policy") if self.current_context else {}
        goal_policy = goal_policy or {}
        recommended = (
            self.current_context.get("recommended_next_command") if self.current_context else None
        )
        current_phase = self._current_phase()
        current_blocker = self._current_blocker()
        can_review = self._can_review(recommended)
        can_accept = self._can_accept(recommended)
        workflow_state = self._workflow_state(
            recommended=recommended,
            current_blocker=current_blocker,
            can_review=can_review,
            can_accept=can_accept,
        )
        return {
            "schema_version": "0.1.0",
            "control_surface": control_surface_contract(
                command="status",
                audience="user_workflow",
                stable_fields=[
                    "schema_version",
                    "root",
                    "initialized",
                    "status",
                    "summary",
                    "conclusion",
                    "workflow_state",
                    "current_phase",
                    "current_blocker",
                    "can_review",
                    "can_accept",
                    "current_session_id",
                    "blockers",
                    "risks",
                    "pending_decision_count",
                    "candidate_promotions",
                    "model_selection",
                    "latest_model_progress",
                    "model_route_timeline",
                    "route_health",
                    "run_loop_summary_path",
                    "run_loop_summary",
                    "final_report_summary_path",
                    "final_report_summary",
                    "goal_policy",
                    "workspace_envelope",
                    "active_goal_memory_path",
                    "active_goal_memory",
                    "active_goal_state",
                    "latest_real_provider_matrix",
                    "plugin_control",
                    "latest_failure",
                    "recommended_next_command",
                    "next_actions",
                    "recent_sessions",
                ],
            ),
            "root": str(self.root),
            "initialized": self.initialized,
            "status": self._status(),
            "summary": self._summary(),
            "conclusion": self._conclusion(),
            "workflow_state": workflow_state,
            "current_phase": current_phase,
            "current_blocker": current_blocker,
            "can_review": can_review,
            "can_accept": can_accept,
            "evidence_chain": self._evidence_chain(),
            "current_session_id": self.current_session_id,
            "current_context": self.current_context,
            "blockers": blockers or [],
            "risks": risks or [],
            "pending_decision_count": int(
                self.current_context.get("pending_decision_count", 0) if self.current_context else 0
            ),
            "candidate_promotions": candidate_promotions,
            "model_selection": model_selection,
            "latest_model_progress": latest_model_progress,
            "model_route_timeline": model_route_timeline,
            "route_health": route_health,
            "run_loop_summary_path": run_loop_summary_path,
            "run_loop_summary": run_loop_summary,
            "final_report_summary_path": final_report_summary_path,
            "final_report_summary": final_report_summary,
            "goal_policy": goal_policy,
            "workspace_envelope": workspace_envelope,
            "active_goal_memory_path": str(self.active_goal_memory_path)
            if self.active_goal_memory_path
            else None,
            "active_goal_memory": self.active_goal_memory,
            "active_goal_state": self.active_goal_state,
            "latest_real_provider_matrix": self.latest_real_provider_matrix,
            "plugin_control": self.plugin_control,
            "latest_failure": latest_failure,
            "recommended_next_command": recommended,
            "next_actions": self._next_actions(recommended),
            "recent_sessions": self.recent_sessions,
        }

    def _status(self) -> str:
        if not self.initialized:
            return "uninitialized"
        if self.plugin_control.get("ok") is False:
            return "blocked"
        run_status = self.current_context.get("run_status") or {}
        task_summary = self.current_context.get("task_summary") or {}
        if (
            run_status.get("status") == "completed"
            and int(task_summary.get("remaining", 0) or 0) == 0
        ):
            return "completed"
        if self.current_context.get("pending_decision_count"):
            return "blocked"
        blockers = self.current_context.get("blockers") or []
        if blockers:
            return "blocked"
        if self.current_session_id:
            return "active"
        return "idle"

    def _conclusion(self) -> str:
        status = self._status()
        if status == "uninitialized":
            return "Workspace is not initialized."
        if status == "blocked":
            return "Current work is blocked and needs an explicit next action."
        if status == "completed":
            return "Current session is complete; review the evidence chain and accept if satisfied."
        if status == "active":
            return "Current session is active and can continue."
        return "Workspace is idle."

    def _current_phase(self) -> str:
        if not self.initialized:
            return "UNINITIALIZED"
        run_status = self.current_context.get("run_status") if self.current_context else {}
        phase = str((run_status or {}).get("current_phase") or "").strip()
        if phase:
            return phase
        return "IDLE" if not self.current_session_id else "UNKNOWN"

    def _current_blocker(self) -> str | None:
        if not self.initialized:
            return "Workspace is not initialized; run `asteria /init --root .` first."
        if self.plugin_control.get("ok") is False:
            return str(
                self.plugin_control.get("summary")
                or "Plugin control preflight failed; inspect plugin configuration."
            )
        blockers = [str(item) for item in self.current_context.get("blockers") or [] if item]
        route_health = self.current_context.get("route_health") or {}
        route_blocker = route_health.get("current_blocker")
        if route_health.get("status") == "blocked" and route_blocker:
            return str(route_blocker)
        task_summary = self.current_context.get("task_summary") or {}
        run_status = self.current_context.get("run_status") or {}
        remaining = int(task_summary.get("remaining", 0) or 0)
        completed = run_status.get("status") == "completed" and remaining == 0
        if blockers and not completed:
            return blockers[0]
        pending = int(self.current_context.get("pending_decision_count", 0) or 0)
        if pending:
            return f"{pending} pending decision(s); run the recommended decide command."
        latest_failure = (self.current_context.get("latest_task_failure") or {}).get("summary")
        if latest_failure and not completed:
            return str(latest_failure)
        return None

    def _can_review(self, recommended: str | None) -> bool:
        if not self.initialized or not self.current_session_id:
            return False
        if self.plugin_control.get("ok") is False:
            return False
        phase = self._current_phase()
        if phase in {"REVIEW", "REVIEWED", "ACCEPT", "ACCEPTED"}:
            return False
        task_summary = self.current_context.get("task_summary") or {}
        run_status = self.current_context.get("run_status") or {}
        remaining = int(task_summary.get("remaining", 0) or 0)
        return recommended == "review" or (
            run_status.get("status") == "completed" and remaining == 0
        )

    def _can_accept(self, recommended: str | None) -> bool:
        if not self.initialized or not self.current_session_id:
            return False
        if self.plugin_control.get("ok") is False:
            return False
        if self._current_phase() == "ACCEPTED":
            return False
        return recommended == "accept"

    def _workflow_state(
        self,
        *,
        recommended: str | None,
        current_blocker: str | None,
        can_review: bool,
        can_accept: bool,
    ) -> str:
        if not self.initialized:
            return "needs_init"
        if self._current_phase() == "ACCEPTED":
            return "accepted"
        if can_accept:
            return "ready_for_accept"
        if can_review:
            return "ready_for_review"
        if current_blocker:
            return "blocked"
        if recommended:
            return "needs_action"
        if self.current_session_id:
            return "in_progress"
        return "idle"

    def _evidence_chain(self) -> list[str]:
        evidence: list[str] = []
        if not self.current_context:
            if self.latest_real_provider_matrix:
                evidence.append(
                    "real_provider_matrix="
                    f"{self.latest_real_provider_matrix.get('passed', 0)}/"
                    f"{self.latest_real_provider_matrix.get('case_count', 0)} "
                    f"route={self.latest_real_provider_matrix.get('latest_route', 'unknown')}"
                )
            return evidence
        run_status = self.current_context.get("run_status") or {}
        if run_status:
            evidence.append(
                f"run={run_status.get('status', 'unknown')} phase={run_status.get('current_phase', 'unknown')}"
            )
        task_summary = self.current_context.get("task_summary") or {}
        if task_summary:
            evidence.append(
                f"tasks remaining={task_summary.get('remaining', 0)} total={task_summary.get('total', 0)}"
            )
        cost = self.current_context.get("cost_summary") or {}
        if cost:
            evidence.append(
                f"cost={cost.get('status', 'unknown')} model_calls={cost.get('model_calls', 0)} tool_calls={cost.get('tool_calls', 0)}"
            )
            latest_execution = self.current_context.get("latest_execution_evidence") or {}
            if latest_execution:
                evidence.append(
                    f"latest_execution={latest_execution.get('task_id')} {latest_execution.get('status')}"
                )
        route_health = self.current_context.get("route_health") or {}
        if route_health:
            evidence.append(f"routes={route_health.get('status', 'unknown')}")
        latest_model_progress = self.current_context.get("latest_model_progress") or {}
        if latest_model_progress:
            evidence.append(
                "latest_model="
                f"{latest_model_progress.get('event_type', 'unknown')} "
                f"{latest_model_progress.get('role', 'unknown')} "
                f"{latest_model_progress.get('model_provider', 'unknown')}/"
                f"{latest_model_progress.get('model_name', 'unknown')}"
            )
        if self.latest_real_provider_matrix:
            evidence.append(
                "real_provider_matrix="
                f"{self.latest_real_provider_matrix.get('passed', 0)}/"
                f"{self.latest_real_provider_matrix.get('case_count', 0)} "
                f"route={self.latest_real_provider_matrix.get('latest_route', 'unknown')}"
            )
        latest_plan = self.current_context.get("latest_observation_plan") or {}
        if latest_plan:
            evidence.append(
                "latest_next_action="
                f"{latest_plan.get('recommended_route', 'unknown')} "
                f"plan={latest_plan.get('observation_plan_id', 'unknown')}"
            )
        promotions = self.current_context.get("candidate_promotions") or {}
        if promotions.get("total"):
            evidence.append(
                f"candidate_promotions total={promotions.get('total', 0)} pending={len(promotions.get('pending') or [])}"
            )
        return evidence

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
        route_health = self.current_context.get("route_health") if self.current_context else {}
        if (route_health or {}).get("status") == "blocked":
            return ["Run `asteria model-check --json` and configure the missing model route."]
        run_status = self.current_context.get("run_status") if self.current_context else {}
        if str((run_status or {}).get("current_phase") or "") == "ACCEPTED":
            return []
        if not self.current_session_id:
            return ['Run `asteria /new "<goal>" --root .`.']
        return ["Run `asteria /sessions --context --root .` to inspect current state."]

    def to_text(self, *, debug: bool = False) -> str:
        if (self.active_goal_state or self.active_goal_memory) and not debug:
            return self._user_text()
        return self._debug_text()

    def _user_text(self) -> str:
        workspace = self.current_context.get("workspace_envelope") or {}
        workspace_lines = []
        if workspace:
            workspace_lines = [
                "Workspace:",
                f"- root: {workspace.get('workspace_root') or self.root}",
                f"- output: {workspace.get('output_root') or workspace.get('workspace_root') or self.root}",
                f"- artifacts: {workspace.get('artifact_root') or 'unknown'}",
                f"- permission: {workspace.get('permission_mode') or 'unknown'}",
                "",
            ]
        if self.active_goal_state:
            lines = [
                "Asteria progress",
                "",
                *workspace_lines,
                "Current goal:",
                f"- {self.active_goal_state.get('current_goal') or 'No goal recorded.'}",
                "",
                "Completed:",
                *self._status_card_lines(
                    self.active_goal_state.get("completed_work"),
                    fallback="- No completed work has been recorded yet.",
                ),
                "",
                "Current status:",
                f"- State: {(self.active_goal_state.get('current_result') or {}).get('state', 'unknown')}",
                f"- Review: {(self.active_goal_state.get('current_result') or {}).get('review', 'unknown')}",
                "",
                "Needs you:",
                *self._status_card_lines(
                    self.active_goal_state.get("questions_for_user")
                    or self.active_goal_state.get("current_blockers"),
                    fallback="- Nothing needed from you right now.",
                ),
                "",
                "Next step:",
                *self._status_card_lines(
                    self.active_goal_state.get("next_task"),
                    fallback="- Choose the next goal to work on.",
                ),
                "",
                "Runtime details: use `asteria status --debug` or `asteria status --json`.",
            ]
            return "\n".join(lines)
        lines = [
            "Asteria progress",
            f"Memory: {self.active_goal_memory_path}",
            "",
            *workspace_lines,
            self.active_goal_memory.strip(),
            "",
            "Runtime details: use `asteria status --debug` or `asteria status --json`.",
        ]
        return "\n".join(lines)

    def _status_card_lines(self, values: object, *, fallback: str) -> list[str]:
        if not isinstance(values, list) or not values:
            return [fallback]
        lines = []
        for value in values[:6]:
            if isinstance(value, dict):
                text = str(value.get("title") or value.get("summary") or value)
            else:
                text = str(value)
            text = text.strip()
            if not text:
                continue
            lines.append(text if text.startswith("- ") else f"- {text}")
        return lines or [fallback]

    def _debug_text(self) -> str:
        lines = [
            "Agent status",
            f"Root: {self.root}",
            f"Initialized: {'yes' if self.initialized else 'no'}",
            f"Conclusion: {self._conclusion()}",
        ]
        if not self.initialized:
            lines.append(
                f"Workflow: {self._workflow_state(recommended=None, current_blocker=self._current_blocker(), can_review=False, can_accept=False)}"
            )
            lines.append(f"Current phase: {self._current_phase()}")
            lines.append(f"Current blocker: {self._current_blocker()}")
            lines.append("Next: asteria init")
            return "\n".join(lines)
        lines.append(f"Current session: {self.current_session_id or 'none'}")
        workspace = self.current_context.get("workspace_envelope") if self.current_context else {}
        if workspace:
            lines.append("Workspace envelope:")
            lines.append(f"- id: {workspace.get('workspace_id') or 'unknown'}")
            lines.append(f"- root: {workspace.get('workspace_root') or 'unknown'}")
            lines.append(f"- output: {workspace.get('output_root') or 'unknown'}")
            lines.append(f"- artifact root: {workspace.get('artifact_root') or 'unknown'}")
            lines.append(f"- permission: {workspace.get('permission_mode') or 'unknown'}")
            lines.append(
                f"- candidate policy: {workspace.get('candidate_workspace_policy') or 'unknown'}"
            )
            lines.append(f"- worktree policy: {workspace.get('worktree_policy') or 'unknown'}")
        recommended = (
            self.current_context.get("recommended_next_command") if self.current_context else None
        )
        current_blocker = self._current_blocker()
        can_review = self._can_review(recommended)
        can_accept = self._can_accept(recommended)
        lines.append(
            "Workflow: "
            f"{self._workflow_state(recommended=recommended, current_blocker=current_blocker, can_review=can_review, can_accept=can_accept)}"
        )
        lines.append(f"Current phase: {self._current_phase()}")
        lines.append(f"Can review: {'yes' if can_review else 'no'}")
        lines.append(f"Can accept: {'yes' if can_accept else 'no'}")
        if current_blocker:
            lines.append(f"Current blocker: {current_blocker}")
        if self.plugin_control:
            lines.append(f"Plugin control: {self.plugin_control.get('summary')}")
            warnings = self.plugin_control.get("warnings") or []
            for warning in list(warnings)[:3]:
                lines.append(f"  - {warning}")
        lines.extend(real_provider_matrix_text_lines(self.latest_real_provider_matrix))
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
            route_health = context.get("route_health") or {}
            if route_health:
                lines.append(
                    "Model routes: "
                    f"{route_health.get('status', 'unknown')} - "
                    f"{route_health.get('summary', 'no route summary')}"
                )
                for route in list(route_health.get("routes") or [])[:3]:
                    lines.append(
                        "  - "
                        f"{route.get('tier', 'unknown')}: "
                        f"{route.get('provider', 'unknown')}/"
                        f"{route.get('model_name', 'unknown')} "
                        f"configured={route.get('configured', False)}"
                    )
                if route_health.get("current_blocker"):
                    lines.append(f"  next: {route_health['current_blocker']}")
            model_selection = context.get("model_selection") or {}
            if model_selection:
                lines.extend(self._model_selection_lines(model_selection))
            latest_model_progress = context.get("latest_model_progress") or {}
            if latest_model_progress:
                lines.extend(self._latest_model_progress_lines(latest_model_progress))
            model_route_timeline = context.get("model_route_timeline") or []
            if model_route_timeline:
                timeline_path = context.get("model_route_timeline_path")
                suffix = f" (full: {timeline_path})" if timeline_path else ""
                lines.append(
                    f"Model route timeline: {len(model_route_timeline)} recent decision(s){suffix}"
                )
                for item in model_route_timeline[-3:]:
                    lines.append(
                        "  - "
                        f"{item.get('task_id', 'unknown')}: "
                        f"{item.get('purpose', 'unknown')} -> "
                        f"{item.get('selected_tier', 'unknown')} "
                        f"({item.get('reason', 'no reason recorded')})"
                    )
            goal_policy = context.get("goal_policy") or {}
            if goal_policy:
                lines.append(
                    "Goal policy: "
                    f"{goal_policy.get('category', 'unknown')} -> "
                    f"{goal_policy.get('recommended_command', 'unknown')} "
                    f"({goal_policy.get('reason', 'no reason recorded')})"
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
            remaining = int((task_summary or {}).get("remaining", 0) or 0)
            active_blockers = bool(blockers) and not (
                run_status.get("status") == "completed" and remaining == 0
            )
            if active_blockers:
                lines.append("Blockers:")
                lines.extend(f"  - {item}" for item in blockers[:5])
            elif blockers:
                lines.append("Resolved blockers:")
                lines.extend(f"  - {item}" for item in blockers[:5])
            latest_execution = context.get("latest_execution_evidence") or {}
            if latest_execution:
                lines.append(
                    "Latest execution: "
                    f"{latest_execution.get('task_id')} "
                    f"{latest_execution.get('status')} - "
                    f"{latest_execution.get('summary')}"
                )
            latest_plan = context.get("latest_observation_plan") or {}
            if latest_plan:
                lines.append(
                    "Latest agent next action: "
                    f"{latest_plan.get('recommended_route', 'unknown')} - "
                    f"{latest_plan.get('reason', 'No reason recorded.')}"
                )
                evidence_refs = latest_plan.get("evidence_refs") or []
                if evidence_refs:
                    lines.append(f"  evidence: {', '.join(str(ref) for ref in evidence_refs[:3])}")
            evidence_chain = self._evidence_chain()
            if evidence_chain:
                lines.append("Evidence chain:")
                lines.extend(f"  - {item}" for item in evidence_chain[:6])
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

    def _model_selection_lines(self, model_selection: dict) -> list[str]:
        lines = [
            (
                "Model selection: "
                f"{model_selection.get('selected_tier', 'unknown')} "
                f"for {model_selection.get('purpose', 'unknown')} "
                f"({model_selection.get('reason', 'no reason recorded')})"
            )
        ]
        pressure = model_selection.get("tier_pressure") or {}
        if pressure:
            direction = str(pressure.get("direction", "unknown"))
            if direction == "up":
                pressure_label = "stronger route selected"
            elif direction == "down":
                pressure_label = "cheaper route selected"
            else:
                pressure_label = "default route kept"
            lines.append(
                "  pressure: "
                f"{pressure.get('default_tier', 'unknown')} -> "
                f"{pressure.get('selected_tier', 'unknown')} "
                f"({pressure_label}, direction={direction}) "
                f"delta={pressure.get('delta', 0)}"
            )
        feedback = model_selection.get("capability_feedback") or {}
        if feedback:
            lines.append(
                "  capability feedback: "
                f"{feedback.get('status', 'unknown')} "
                f"({feedback.get('decision', 'no decision')}; "
                f"blocking={feedback.get('blocking_count', 0)}, "
                f"review={feedback.get('review_count', 0)})"
            )
            matched = feedback.get("matched_route") or {}
            if matched:
                lines.append(
                    "  matched route: "
                    f"{matched.get('purpose', 'unknown')}/"
                    f"{matched.get('model_tier', 'unknown')} "
                    f"action={matched.get('recommended_action', 'unknown')}"
                )
            actions = feedback.get("recommended_actions") or []
            if actions:
                lines.append(f"  recommended: {actions[0]}")
        return lines

    def _latest_model_progress_lines(self, progress: dict) -> list[str]:
        role = progress.get("role") or "unknown-role"
        tier = progress.get("model_tier") or "unknown-tier"
        provider = progress.get("model_provider") or "unknown-provider"
        model = progress.get("model_name") or "unknown-model"
        event_type = progress.get("event_type") or "unknown"
        status = progress.get("status") or "unknown"
        deadline = progress.get("deadline_remaining_ms")
        deadline_part = (
            f", deadline_remaining_ms={deadline}" if deadline is not None else ""
        )
        lines = [
            (
                "Model progress: "
                f"{role}/{tier} {provider}/{model} "
                f"{event_type} {status}{deadline_part}"
            )
        ]
        profile = progress.get("deadline_profile")
        task_id = progress.get("task_id")
        runtime_profile_id = progress.get("runtime_profile_id")
        details = []
        if profile:
            details.append(f"deadline_profile={profile}")
        if task_id:
            details.append(f"task={task_id}")
        if runtime_profile_id:
            details.append(f"runtime_profile={runtime_profile_id}")
        if details:
            lines.append(f"  {'; '.join(str(item) for item in details)}")
        return lines


class StatusCommand:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> StatusResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            return StatusResult(
                root=self.root,
                initialized=False,
                plugin_control=plugin_control_summary(self.root, self.validator),
            )
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
        active_goal_memory = ActiveGoalMemory(self.root)
        active_goal_text = active_goal_memory.read()
        active_goal_state = active_goal_memory.read_structured()
        return StatusResult(
            root=self.root,
            initialized=True,
            current_session_id=sessions.current_session_id,
            current_context=current_context or {},
            recent_sessions=sessions.sessions,
            plugin_control=plugin_control_summary(self.root, self.validator),
            latest_real_provider_matrix=latest_real_provider_matrix(agent_dir),
            active_goal_memory_path=active_goal_memory.path if active_goal_text else None,
            active_goal_memory=active_goal_text,
            active_goal_state=active_goal_state,
        )
