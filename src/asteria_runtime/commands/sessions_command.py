from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.core.agent_loop_decision import (
    latest_agent_loop_decision,
    recommended_command_for_next_action,
)
from asteria_runtime.core.agent_loop_executor import latest_agent_loop_execution_result
from asteria_runtime.core.agent_loop_observation import latest_agent_loop_observation
from asteria_runtime.core.candidate_promotion_queue import CandidatePromotionQueue
from asteria_runtime.core.worker_tree import WorkerTreeBuilder
from asteria_runtime.models.route_resolver import (
    route_health_for_tiers,
    route_health_from_records,
)
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


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
        if context.get("run_loop_summary_path"):
            lines.append(f"  run loop summary: {context['run_loop_summary_path']}")
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
        latest_execution = context.get("latest_execution_evidence") or {}
        if latest_execution:
            lines.append(
                (
                    f"  latest execution: {latest_execution.get('task_id')} "
                    f"{latest_execution.get('status')} - {latest_execution.get('summary')}"
                )
            )
        progress_timeline = context.get("progress_timeline") or []
        if progress_timeline:
            latest = progress_timeline[-1]
            lines.append(
                (
                    f"  latest progress: {latest.get('title') or latest.get('event_type')} - "
                    f"{latest.get('summary') or latest.get('status')}"
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
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            raise RuntimeError("Workspace is not initialized. Run `asteria init` first.")
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
        execution_evidence = self._task_execution_evidence(run_dir)
        task_failures = self._active_task_failures(
            (snapshot or {}).get("task_failures") or self._task_failures(run_dir),
            execution_evidence,
        )
        model_selection = self._latest_model_selection(execution_evidence)
        model_route_timeline = self._model_route_timeline(execution_evidence)
        model_route_timeline_path = self._model_route_timeline_path(run_dir)
        latest_model_progress = self._latest_model_progress(run_dir)
        progress_timeline = self._progress_timeline(run_dir, execution_evidence)
        latest_observation_plan = self._latest_observation_plan(run_dir)
        latest_loop_decision = latest_agent_loop_decision(run_dir, self.validator) or {}
        latest_loop_execution = latest_agent_loop_execution_result(run_dir, self.validator) or {}
        latest_loop_observation = latest_agent_loop_observation(run_dir, self.validator) or {}
        workspace_envelope = self._workspace_envelope(run_dir)
        route_health = self._route_health(run_dir)
        run_loop_summary = self._run_loop_summary(run_dir)
        final_report_summary = self._final_report_summary(run_dir)
        latest_review = self._latest_review_report(run_dir)
        goal_policy = (final_report_summary.get("goal_policy") or {}) if final_report_summary else {}
        if not goal_policy:
            marker = self._read_unvalidated_json(run_dir / "goal_policy.json")
            goal_policy = marker.get("goal_policy") or {}
        if not goal_policy:
            goal_policy = self._goal_policy_from_pending_decisions(pending_decisions)
        if not goal_policy:
            goal_policy = (latest_review.get("trajectory_eval") or {}).get(
                "failure_classification"
            ) or {}
        worker_tree = WorkerTreeBuilder(self.validator).build(run_dir)
        promotion_summary = CandidatePromotionQueue(self.validator).summary(run_dir)
        blockers = self._blockers(
            run_dir,
            pending_decisions,
            task_failures,
            acceptance_failures,
            route_health,
        )
        risks = (snapshot or {}).get("open_risks") or self._risks(
            run_dir, task_failures, acceptance_failures
        )
        recommended_next_command = self._recommended_next_command(
            run_dir,
            run_status,
            task_summary,
            pending_decisions,
            task_failures,
            blockers,
        )
        if (
            str(run_status.get("status") or "") != "completed"
            and str(run_status.get("current_phase") or "") != "ACCEPTED"
        ):
            next_action_command = recommended_command_for_next_action(
                latest_loop_decision.get("next_action", {})
            )
            if next_action_command in {"debug", "replan", "decide --list", "status --debug"} and (
                recommended_next_command is None or recommended_next_command == "debug"
            ):
                recommended_next_command = next_action_command
        if (
            recommended_next_command is None
            and str(run_status.get("status") or "") != "completed"
            and str(run_status.get("current_phase") or "") != "ACCEPTED"
        ):
            recommended_next_command = (handoff or {}).get(
                "recommended_next_command"
            ) or self._first_next_action(snapshot)
        return {
            "goal_summary": (snapshot or {}).get("goal_summary") or self._goal_summary(run_dir),
            "run_status": run_status,
            "snapshot_path": snapshot_rel,
            "handoff_path": handoff_rel,
            "recommended_next_command": recommended_next_command,
            "run_loop_summary_path": self._relative_path(run_dir / "run_loop_summary.json")
            if run_loop_summary
            else None,
            "run_loop_summary": run_loop_summary,
            "final_report_summary_path": self._relative_path(run_dir / "final_report_summary.json")
            if final_report_summary
            else None,
            "final_report_summary": final_report_summary,
            "cost_summary": self._cost_summary(run_dir),
            "verification": verification,
            "pending_decision_count": len(pending_decisions),
            "pending_decisions": pending_decisions,
            "task_summary": task_summary,
            "latest_task_failure": task_failures[-1] if task_failures else None,
            "task_failures": task_failures[-3:],
            "latest_execution_evidence": execution_evidence[-1] if execution_evidence else None,
            "task_execution_evidence": execution_evidence[-3:],
            "model_selection": model_selection,
            "latest_model_progress": latest_model_progress,
            "progress_timeline_source": progress_timeline["source"],
            "progress_timeline": progress_timeline["events"],
            "model_route_timeline_path": model_route_timeline_path,
            "model_route_timeline": model_route_timeline,
            "goal_policy": goal_policy,
            "route_health": route_health,
            "latest_observation_plan": latest_observation_plan,
            "latest_agent_loop_decision": latest_loop_decision,
            "latest_agent_loop_execution_result": latest_loop_execution,
            "latest_agent_loop_observation": latest_loop_observation,
            "workspace_envelope": workspace_envelope,
            "worker_tree": worker_tree,
            "candidate_promotions": promotion_summary,
            "blockers": blockers,
            "risks": risks,
            "acceptance_failure_count": len(acceptance_failures),
            "latest_acceptance_failure": acceptance_failures[-1] if acceptance_failures else None,
            "acceptance_failures": acceptance_failures[-3:],
        }

    def _workspace_envelope(self, run_dir: Path) -> dict:
        envelope = self._read_json(run_dir / "workspace_envelope.json", "workspace_envelope")
        if envelope:
            return envelope
        run = self._read_json(run_dir / "run.json", "run")
        workspace = (run or {}).get("workspace") or {}
        if not workspace:
            return {}
        return {
            "schema_version": "legacy",
            "workspace_id": workspace.get("workspace_id"),
            "workspace_root": workspace.get("workspace_root") or workspace.get("path"),
            "output_root": workspace.get("output_root") or workspace.get("path"),
            "artifact_root": workspace.get("artifact_root"),
            "permission_mode": workspace.get("permission_mode"),
            "candidate_workspace_policy": workspace.get("candidate_workspace_policy"),
            "worktree_policy": workspace.get("worktree_policy")
            or workspace.get("candidate_workspace_policy"),
            "git_policy": workspace.get("git_policy"),
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
                "metadata": decision.get("metadata", {}),
            }
            for decision in decisions
            if decision["status"] == "pending"
        ]

    def _goal_policy_from_pending_decisions(self, pending_decisions: list[dict]) -> dict:
        if not pending_decisions:
            return {}
        decision = pending_decisions[0]
        metadata = decision.get("metadata") or {}
        kind = str(metadata.get("kind") or "")
        question = str(decision.get("question") or "")
        decision_text = f"{kind} {question}".lower()
        if "budget" in decision_text or "cost" in decision_text:
            category = "budget_guard"
        elif any(
            term in decision_text
            for term in ("permission", "policy", "runtime_request", "tool")
        ):
            category = "permission_guard"
        else:
            category = "decision_required"
        decision_id = str(decision["decision_id"])
        return {
            "category": category,
            "recommended_command": f"decide --decision-id {decision_id}",
            "reason": f"DecisionPoint is pending: {question}",
            "decision_id": decision_id,
        }

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

    def _task_execution_evidence(self, run_dir: Path) -> list[dict]:
        evidence_items = self._read_jsonl(
            run_dir / "task_execution_evidence.jsonl",
            "task_execution_evidence",
        )
        return [
            {
                "evidence_id": evidence["evidence_id"],
                "task_id": evidence["task_id"],
                "status": evidence["status"],
                "summary": evidence["summary"],
                "failure_type": evidence.get("failure_type"),
                "contract_ok": (evidence.get("contract_check") or {}).get("ok"),
                "promoted_files": (evidence.get("candidate") or {}).get("promoted_files", []),
                "model_selection": (evidence.get("action") or {}).get("model_selection"),
                "evidence_path": (run_dir / "task_execution_evidence.jsonl")
                .relative_to(self.root)
                .as_posix(),
                "created_at": evidence.get("created_at"),
            }
            for evidence in evidence_items[-10:]
        ]

    def _active_task_failures(
        self,
        task_failures: list[dict],
        execution_evidence: list[dict],
    ) -> list[dict]:
        latest_done_at_by_task: dict[str, str] = {}
        for evidence in execution_evidence:
            if evidence.get("status") not in {"done", "succeeded"}:
                continue
            task_id = str(evidence.get("task_id") or "")
            if not task_id:
                continue
            latest_done_at_by_task[task_id] = str(evidence.get("created_at") or "")
        if not latest_done_at_by_task:
            return task_failures
        active = []
        for failure in task_failures:
            task_id = str(failure.get("task_id") or "")
            if not task_id:
                active.append(failure)
                continue
            done_at = latest_done_at_by_task.get(task_id)
            failed_at = str(failure.get("created_at") or "")
            if done_at and (not failed_at or done_at >= failed_at):
                continue
            active.append(failure)
        return active

    def _latest_model_selection(self, execution_evidence: list[dict]) -> dict:
        for evidence in reversed(execution_evidence):
            selection = evidence.get("model_selection")
            if isinstance(selection, dict) and selection:
                return selection
        return {}

    def _model_route_timeline(self, execution_evidence: list[dict]) -> list[dict]:
        timeline = []
        for evidence in execution_evidence:
            selection = evidence.get("model_selection")
            if not isinstance(selection, dict) or not selection:
                continue
            timeline.append(
                {
                    "task_id": evidence.get("task_id"),
                    "purpose": selection.get("purpose"),
                    "task_kind": selection.get("task_kind"),
                    "selected_tier": selection.get("selected_tier"),
                    "default_tier": selection.get("default_tier"),
                    "strategy_tier": selection.get("strategy_tier"),
                    "strategy": selection.get("strategy"),
                    "reason": selection.get("reason"),
                    "tier_pressure": selection.get("tier_pressure") or {},
                    "capability_feedback": selection.get("capability_feedback") or {},
                    "evidence_path": evidence.get("evidence_path"),
                    "created_at": evidence.get("created_at"),
                }
            )
        return timeline[-20:]

    def _model_route_timeline_path(self, run_dir: Path) -> str | None:
        path = run_dir / "model_route_timeline.json"
        if not path.exists():
            return None
        return self._relative_path(path)

    def _latest_model_progress(self, run_dir: Path) -> dict:
        events = self._read_jsonl(run_dir / "user_progress.jsonl", "user_progress_event")
        model_events = [event for event in events if event.get("channel") == "model"]
        if not model_events:
            return {}
        latest = model_events[-1]
        telemetry_value = latest.get("telemetry")
        telemetry: dict = telemetry_value if isinstance(telemetry_value, dict) else {}
        data_value = latest.get("data")
        data: dict = data_value if isinstance(data_value, dict) else {}
        contract_value = data.get("agent_role_contract")
        contract: dict = contract_value if isinstance(contract_value, dict) else {}
        return {
            "event_id": latest.get("event_id"),
            "event_type": latest.get("event_type"),
            "status": latest.get("status"),
            "phase": latest.get("phase"),
            "summary": latest.get("summary"),
            "created_at": latest.get("created_at"),
            "model_provider": latest.get("model_provider"),
            "model_name": latest.get("model_name"),
            "role": telemetry.get("role") or contract.get("role"),
            "role_purpose": telemetry.get("role_purpose") or contract.get("purpose"),
            "model_tier": telemetry.get("model_tier"),
            "deadline_profile": telemetry.get("deadline_profile") or contract.get("deadline_profile"),
            "deadline_ms": telemetry.get("deadline_ms"),
            "deadline_remaining_ms": telemetry.get("deadline_remaining_ms"),
            "provider_call_seconds": telemetry.get("provider_call_seconds")
            or contract.get("provider_call_seconds"),
            "stream_idle_timeout_seconds": telemetry.get("stream_idle_timeout_seconds")
            or contract.get("stream_idle_timeout_seconds"),
            "runtime_profile_id": telemetry.get("runtime_profile_id"),
            "model_profile_id": telemetry.get("model_profile_id"),
            "task_id": telemetry.get("task_id"),
            "attempt": telemetry.get("attempt"),
            "model_route": telemetry.get("model_route"),
            "progress_path": self._relative_path(run_dir / "user_progress.jsonl"),
        }

    def _progress_timeline(self, run_dir: Path, execution_evidence: list[dict]) -> dict:
        user_progress = self._read_jsonl(run_dir / "user_progress.jsonl", "user_progress_event")
        if user_progress:
            return {
                "source": "user_progress",
                "events": [
                    {
                        "event_id": event.get("event_id"),
                        "channel": event.get("channel"),
                        "event_type": event.get("event_type"),
                        "phase": event.get("phase"),
                        "status": event.get("status"),
                        "title": event.get("title"),
                        "summary": event.get("summary"),
                        "display_level": event.get("display_level"),
                        "artifact_refs": event.get("artifact_refs", []),
                        "evidence_refs": event.get("evidence_refs", []),
                        "created_at": event.get("created_at"),
                        "source": "user_progress",
                    }
                    for event in user_progress[-20:]
                ],
            }
        legacy_events = self._read_jsonl(run_dir / "events.jsonl", "event")
        if legacy_events:
            return {
                "source": "events",
                "events": [
                    {
                        "event_id": event.get("event_id"),
                        "channel": "diagnostic",
                        "event_type": event.get("type"),
                        "phase": "",
                        "status": event.get("status") or "recorded",
                        "title": event.get("actor") or event.get("type"),
                        "summary": event.get("summary"),
                        "display_level": "inspector",
                        "artifact_refs": [],
                        "evidence_refs": [self._relative_path(run_dir / "events.jsonl")],
                        "created_at": event.get("created_at"),
                        "source": "events",
                    }
                    for event in legacy_events[-20:]
                ],
            }
        return {
            "source": "task_execution_evidence" if execution_evidence else "none",
            "events": [
                {
                    "event_id": item.get("evidence_id"),
                    "channel": "evidence",
                    "event_type": "evidence",
                    "phase": "execute",
                    "status": item.get("status"),
                    "title": item.get("task_id"),
                    "summary": item.get("summary"),
                    "display_level": "inspector",
                    "artifact_refs": [],
                    "evidence_refs": [item.get("evidence_path")],
                    "created_at": item.get("created_at"),
                    "source": "task_execution_evidence",
                }
                for item in execution_evidence[-20:]
            ],
        }

    def _latest_observation_plan(self, run_dir: Path) -> dict | None:
        plans = self._read_jsonl(run_dir / "observation_plans.jsonl", "observation_plan")
        if not plans:
            return None
        latest = plans[-1]
        return {
            "observation_plan_id": latest["observation_plan_id"],
            "task_id": latest.get("task_id"),
            "trigger": latest["trigger"],
            "failed_observation_count": latest["failed_observation_count"],
            "recommended_route": latest.get("recommended_route"),
            "reason": latest.get("reason"),
            "actions": latest.get("actions", [])[:5],
            "blockers": latest.get("blockers", [])[:5],
            "evidence_refs": latest.get("evidence_refs", [])[:5],
            "created_at": latest.get("created_at"),
        }

    def _blockers(
        self,
        run_dir: Path,
        pending_decisions: list[dict],
        task_failures: list[dict],
        acceptance_failures: list[dict],
        route_health: dict,
    ) -> list[str]:
        blockers = []
        route_blocker = route_health.get("current_blocker") if route_health else None
        if route_blocker:
            blockers.append(str(route_blocker))
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

    def _route_health(self, run_dir: Path) -> dict:
        model_profiles = self._read_jsonl(run_dir / "model_profiles.jsonl", "model_profile")
        if not model_profiles:
            route_records = self._read_jsonl(
                run_dir / "model_route_resolutions.jsonl",
                schema_name=None,
            )
            if route_records:
                return route_health_from_records(route_records)
        if not model_profiles:
            return {
                "status": "unknown",
                "summary": "No model profile has been mounted for this run yet.",
                "routes": [],
                "current_blocker": None,
                "recommended_next_command": None,
            }
        latest_by_tier: dict[str, dict] = {}
        for profile in model_profiles:
            tier = str(profile.get("model_tier") or "unknown")
            latest_by_tier[tier] = profile
        return route_health_for_tiers(tuple(latest_by_tier))

    def _run_loop_summary(self, run_dir: Path) -> dict:
        return self._read_json(run_dir / "run_loop_summary.json", "run_loop_summary")

    def _final_report_summary(self, run_dir: Path) -> dict:
        return self._read_json(run_dir / "final_report_summary.json", "final_report_summary")

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
        run_status: dict,
        task_summary: dict,
        pending_decisions: list[dict],
        task_failures: list[dict],
        blockers: list[str],
    ) -> str | None:
        status = str(run_status.get("status") or "")
        phase = str(run_status.get("current_phase") or "")
        remaining = int(task_summary.get("remaining", 0) or 0)
        if phase == "ACCEPTED":
            return None
        latest_review = self._latest_review_report(run_dir)
        review_status = str((latest_review.get("overall") or {}).get("status") or "")
        failure_classification = (latest_review.get("trajectory_eval") or {}).get(
            "failure_classification"
        ) or {}
        classified_command = str(failure_classification.get("recommended_command") or "")
        if review_status in {"partial", "fail"}:
            if classified_command in {"debug", "replan", "decide --list"}:
                return classified_command
            return "debug"
        if phase == "REVIEWED" and review_status == "pass":
            return "accept"
        if status == "completed" and remaining == 0:
            if phase == "REVIEWED":
                return "accept"
            return "review"
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

    def _latest_review_report(self, run_dir: Path) -> dict:
        return self._read_json(run_dir / "eval_report.json", "eval_report")

    def _read_json(self, path: Path, schema_name: str) -> dict:
        if not path.exists():
            return {}
        return self.store.read(path, schema_name)

    def _read_unvalidated_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_jsonl(self, path: Path, schema_name: str | None) -> list[dict]:
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

