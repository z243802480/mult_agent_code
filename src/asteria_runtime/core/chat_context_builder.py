from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asteria_runtime.core.active_goal_memory import ActiveGoalMemory
from asteria_runtime.core.capability_invocation_policy import CapabilityInvocationPolicy
from asteria_runtime.core.context_envelope import ContextEnvelope
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.permission_policy import permission_policy_profile
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class ChatContextBuilder:
    root: Path
    validator: SchemaValidator
    permission_level: str = "balanced"

    def build(
        self,
        *,
        intent: str,
    ) -> ContextEnvelope:
        context = self.context(intent=intent)
        return ContextEnvelope.from_payload(
            audience="user_interaction",
            mode="chat",
            intent=intent,
            root=self.root,
            run_id=self._run_id(context),
            refs=[str(item) for item in context.get("refs", []) if item],
            payload=context,
            sections=self._sections(context),
        )

    def build_and_persist(self, *, intent: str) -> tuple[dict[str, Any], ContextEnvelope, Path]:
        envelope = self.build(intent=intent)
        path = self.envelope_path(envelope)
        JsonStore(self.validator).write(path, envelope.to_dict(), "context_envelope")
        return envelope.payload, envelope, path

    def envelope_path(self, envelope: ContextEnvelope) -> Path:
        if envelope.run_id:
            return (
                self.root
                / ".asteria"
                / "runs"
                / envelope.run_id
                / "context_envelope_chat.json"
            )
        return self.root / ".asteria" / "context" / "context_envelope_chat.json"

    def context(self, *, intent: str) -> dict[str, Any]:
        agent_dir = self.root / ".asteria"
        store = JsonStore(self.validator)
        project = store.read(agent_dir / "project.json", "project_config")
        policy = load_policy_config(agent_dir, self.validator)
        run_store = RunStore(agent_dir, self.validator)
        current_run_id = run_store.current_session_id()
        current_run = run_store.load_run(current_run_id) if current_run_id else None
        runtime_context = ContextLoader(self.root, self.validator).load()
        session_context = self._session_context(agent_dir, current_run_id, current_run)
        include_active_goal_memory = intent in {
            "progress_question",
            "status_question",
            "plan_question",
            "next_step_question",
        }
        active_goal_memory = (
            ActiveGoalMemory(self.root).read() if include_active_goal_memory else ""
        )
        raw_workspace_envelope = session_context.get("workspace_envelope")
        workspace_envelope: dict[str, Any] = (
            raw_workspace_envelope if isinstance(raw_workspace_envelope, dict) else {}
        )
        raw_permission_policy = policy.get("permission_policy")
        if isinstance(raw_permission_policy, dict):
            permission_policy: dict[str, Any] = raw_permission_policy
        else:
            permission_policy = permission_policy_profile(
                str(workspace_envelope.get("permission_mode") or self.permission_level)
            )
        permission_mode = str(
            workspace_envelope.get("permission_mode") or permission_policy.get("mode")
        )
        capability_invocation_policy = CapabilityInvocationPolicy().for_intent(
            intent,
            permission_mode=permission_mode,
        )
        return {
            "chat_intent": intent,
            "capability_invocation_policy": capability_invocation_policy,
            "context_policy": {
                "active_goal_memory_included": include_active_goal_memory,
                "backend_fields_allowed": intent == "debug_question",
            },
            "project": {
                "name": project.get("name"),
                "workspace_type": project.get("workspace_type"),
                "languages": project.get("languages", []),
                "frameworks": project.get("frameworks", []),
                "commands": project.get("commands", {}),
            },
            "policy": {
                "decision_granularity": policy.get("decision_granularity"),
                "permissions": policy.get("permissions", {}),
                "permission_mode": permission_mode,
                "permission_policy": permission_policy,
            },
            "workspace_envelope": workspace_envelope,
            "current_run": {
                "run_id": current_run.get("run_id"),
                "status": current_run.get("status"),
                "current_phase": current_run.get("current_phase"),
                "summary": current_run.get("summary"),
            }
            if current_run
            else None,
            "session_context": session_context,
            "agent_loop_dispatch": session_context.get("agent_loop_dispatch") or {},
            "active_goal_memory": active_goal_memory,
            "runtime_summary": {
                "important_paths": runtime_context.get("important_paths", [])[:10],
                "guidance": runtime_context.get("guidance", {}) != {},
            },
            "refs": [".asteria/project.json", ".asteria/policies.json"]
            + ([".asteria/memory/active_goal.md"] if active_goal_memory else [])
            + (
                [
                    f".asteria/runs/{current_run_id}/run.json",
                    f".asteria/runs/{current_run_id}/workspace_envelope.json",
                ]
                if current_run_id
                else []
            ),
        }

    def _session_context(
        self,
        agent_dir: Path,
        current_run_id: str | None,
        current_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not current_run_id or not current_run:
            return {
                "current_run": None,
                "workflow": {
                    "workflow_state": "initialized",
                    "recommended_next_command": "plan",
                    "current_blocker": None,
                },
                "latest_evidence": None,
                "model_selection": {},
            }
        run_dir = agent_dir / "runs" / current_run_id
        run_loop_summary = self._read_json(run_dir / "run_loop_summary.json", "run_loop_summary")
        final_summary = self._read_json(
            run_dir / "final_report_summary.json", "final_report_summary"
        )
        workflow_source = final_summary or run_loop_summary
        latest_evidence = (
            run_loop_summary.get("latest_evidence")
            if isinstance(run_loop_summary, dict)
            else workflow_source.get("latest_evidence")
            if isinstance(workflow_source, dict)
            else None
        )
        model_selection = final_summary.get("model_selection") or self._latest_model_selection(
            run_dir
        )
        model_route_timeline = final_summary.get("model_route_timeline") or self._model_route_timeline(
            run_dir
        )
        model_route_timeline_path = final_summary.get("model_route_timeline_path")
        if not model_route_timeline_path and (run_dir / "model_route_timeline.json").exists():
            model_route_timeline_path = self._relative_path(run_dir / "model_route_timeline.json")
        workspace_envelope = self._read_json(run_dir / "workspace_envelope.json", "workspace_envelope")
        agent_loop_dispatch = self._agent_loop_dispatch_summary(run_dir)
        return {
            "current_run": {
                "run_id": current_run.get("run_id"),
                "status": current_run.get("status"),
                "current_phase": current_run.get("current_phase"),
                "summary": current_run.get("summary"),
            },
            "workflow": {
                "workflow_state": workflow_source.get("workflow_state")
                or self._workflow_state(current_run),
                "current_blocker": workflow_source.get("current_blocker"),
                "recommended_next_command": workflow_source.get("recommended_next_command")
                or self._recommended_next_command(current_run),
                "run_loop_summary_path": self._relative_path(run_dir / "run_loop_summary.json")
                if run_loop_summary
                else None,
                "final_report_summary_path": self._relative_path(
                    run_dir / "final_report_summary.json"
                )
                if final_summary
                else None,
            },
            "latest_evidence": latest_evidence,
            "model_selection": model_selection,
            "model_route_timeline_path": model_route_timeline_path,
            "model_route_timeline": model_route_timeline,
            "workspace_envelope": workspace_envelope,
            "agent_loop_dispatch": agent_loop_dispatch,
        }

    def _read_json(self, path: Path, schema_name: str) -> dict[str, Any]:
        if not path.exists():
            return {}
        return JsonStore(self.validator).read(path, schema_name)

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _latest_model_selection(self, run_dir: Path) -> dict[str, Any]:
        path = run_dir / "task_execution_evidence.jsonl"
        if not path.exists():
            return {}
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            evidence = json.loads(line)
            selection = (
                evidence.get("model_selection")
                or (evidence.get("action") or {}).get("model_selection")
            )
            if isinstance(selection, dict) and selection:
                return selection
        return {}

    def _model_route_timeline(self, run_dir: Path) -> list[dict[str, Any]]:
        path = run_dir / "task_execution_evidence.jsonl"
        if not path.exists():
            return []
        timeline = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            evidence = json.loads(line)
            selection = (
                evidence.get("model_selection")
                or (evidence.get("action") or {}).get("model_selection")
            )
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
                    "evidence_path": path.relative_to(self.root).as_posix(),
                    "created_at": evidence.get("created_at"),
                }
            )
        return timeline[-20:]

    def _workflow_state(self, run: dict[str, Any]) -> str:
        phase = str(run.get("current_phase") or "")
        status = str(run.get("status") or "")
        if phase == "ACCEPTED":
            return "accepted"
        if phase == "REVIEWED":
            return "ready_for_accept"
        if status == "completed":
            return "ready_for_review"
        if status == "failed":
            return "needs_action"
        return status or "unknown"

    def _recommended_next_command(self, run: dict[str, Any]) -> str | None:
        phase = str(run.get("current_phase") or "")
        status = str(run.get("status") or "")
        if phase == "ACCEPTED":
            return None
        if phase == "REVIEWED":
            return "accept"
        if status == "completed":
            return "review"
        if status == "failed":
            return "debug"
        return None

    def _run_id(self, context: dict[str, Any]) -> str | None:
        current_run = context.get("current_run")
        if isinstance(current_run, dict) and current_run.get("run_id"):
            return str(current_run["run_id"])
        session = context.get("session_context")
        if isinstance(session, dict):
            session_run = session.get("current_run")
            if isinstance(session_run, dict) and session_run.get("run_id"):
                return str(session_run["run_id"])
        return None

    def _sections(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        section_names = [
            "project",
            "policy",
            "capability_invocation_policy",
            "workspace_envelope",
            "agent_loop_dispatch",
            "session_context",
            "active_goal_memory",
            "runtime_summary",
        ]
        sections = []
        for name in section_names:
            value = context.get(name)
            included = bool(value)
            sections.append(
                {
                    "name": name,
                    "included": included,
                    "summary": self._summary(name, value) if included else "not mounted",
                }
            )
        return sections

    def _summary(self, name: str, value: object) -> str:
        if name == "active_goal_memory":
            return "mounted" if value else "not mounted"
        if isinstance(value, dict):
            return f"{len(value)} field(s)"
        if isinstance(value, list):
            return f"{len(value)} item(s)"
        return "mounted"

    def _agent_loop_dispatch_summary(self, run_dir: Path) -> dict[str, Any]:
        path = run_dir / "agent_loop_dispatch.json"
        if not path.exists():
            return {}
        try:
            dispatch = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        task_dispatch = dispatch.get("task_dispatch")
        if not isinstance(task_dispatch, list):
            task_dispatch = []
        return {
            "path": self._relative_path(path),
            "primary_loop_profile_id": dispatch.get("primary_loop_profile_id"),
            "profile_counts": dispatch.get("profile_counts") or {},
            "task_dispatch": [
                {
                    "task_id": item.get("task_id"),
                    "loop_profile_id": item.get("loop_profile_id"),
                    "dispatch_reason": item.get("dispatch_reason"),
                    "output_contract": item.get("output_contract") or {},
                    "validation_contract": item.get("validation_contract") or {},
                }
                for item in task_dispatch[:10]
                if isinstance(item, dict)
            ],
        }
