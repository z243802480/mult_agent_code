from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.core.agent_role_policy import role_contract_for
from asteria_runtime.core.context_loader import ContextLoader
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class ChatResult:
    question: str
    answer: str
    root: Path
    mode: str = "chat"
    permission_level: str = "balanced"
    model_strategy: str = "auto"
    context_refs: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    session_context: dict | None = None
    execution_allowed: bool = False

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "control_surface": control_surface_contract(
                command="chat",
                audience="user_interaction",
                stable_fields=[
                    "schema_version",
                    "mode",
                    "question",
                    "answer",
                    "permission_level",
                    "model_strategy",
                    "context_refs",
                    "session_context",
                    "next_actions",
                    "execution_allowed",
                ],
            ),
            "mode": self.mode,
            "root": str(self.root),
            "question": self.question,
            "answer": self.answer,
            "permission_level": self.permission_level,
            "model_strategy": self.model_strategy,
            "context_refs": self.context_refs,
            "session_context": self.session_context,
            "next_actions": self.next_actions,
            "execution_allowed": self.execution_allowed,
        }

    def to_text(self) -> str:
        lines = [
            "Chat",
            f"Permission level: {self.permission_level}",
            f"Model strategy: {self.model_strategy}",
            "",
            self.answer,
        ]
        if self.context_refs:
            lines.extend(["", "Context refs:"])
            lines.extend(f"- {item}" for item in self.context_refs)
        if self.session_context:
            current = self.session_context.get("current_run") or {}
            workflow = self.session_context.get("workflow") or {}
            route_timeline = self.session_context.get("model_route_timeline") or []
            lines.extend(
                [
                    "",
                    "Current session:",
                    f"- run: {current.get('run_id') or 'none'}",
                    f"- state: {workflow.get('workflow_state') or 'unknown'}",
                    f"- next: {workflow.get('recommended_next_command') or 'none'}",
                ]
            )
            if route_timeline:
                latest = route_timeline[-1]
                lines.append(f"- model route decisions: {len(route_timeline)} recent")
                lines.append(
                    "- latest route: "
                    f"{latest.get('purpose', 'unknown')} -> "
                    f"{latest.get('selected_tier', 'unknown')} "
                    f"({latest.get('reason', 'no reason recorded')})"
                )
        if self.next_actions:
            lines.extend(["", "Next actions:"])
            lines.extend(f"- {item}" for item in self.next_actions)
        return "\n".join(lines)


class ChatCommand:
    def __init__(
        self,
        root: Path,
        question: str,
        *,
        permission_level: str = "balanced",
        model_strategy: str = "auto",
        model_client: ModelClient | None = None,
    ) -> None:
        self.root = root.resolve()
        self.question = question
        self.permission_level = permission_level
        self.model_strategy = model_strategy
        self.model_client = model_client
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")
        self.store = JsonStore(self.validator)

    def run(self) -> ChatResult:
        agent_dir = self.root / ".asteria"
        if not agent_dir.exists():
            return ChatResult(
                question=self.question,
                answer=(
                    "Workspace is not initialized yet. For daily Q&A I can still answer from "
                    "the question, but project-aware chat needs `asteria init` first."
                ),
                root=self.root,
                permission_level=self.permission_level,
                model_strategy=self.model_strategy,
                next_actions=["Run `asteria init --root .` for project-aware chat."],
                session_context={
                    "current_run": None,
                    "workflow": {
                        "workflow_state": "uninitialized",
                        "recommended_next_command": "init",
                    },
                },
            )
        context = self._safe_context(agent_dir)
        client = self.model_client or create_model_client(None, self.validator)
        role_contract = role_contract_for(
            role="ChatAgent",
            purpose="chat",
            policy=context.get("policy") if isinstance(context.get("policy"), dict) else None,
        )
        response = client.chat(
            ChatRequest(
                purpose="chat",
                model_tier=self._model_tier(role_contract.default_model_tier),
                messages=[
                    ChatMessage(role="system", content=self._system_prompt()),
                    ChatMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "question": self.question,
                                "permission_level": self.permission_level,
                                "model_strategy": self.model_strategy,
                                "safe_project_context": context,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    ),
                ],
                temperature=0.2,
                max_output_tokens=2500,
                metadata={
                    "agent_id": "ChatAgent",
                    "agent_role_contract": role_contract.to_dict(),
                },
            )
        )
        answer = self._clean_answer(response.content)
        return ChatResult(
            question=self.question,
            answer=answer,
            root=self.root,
            permission_level=self.permission_level,
            model_strategy=self.model_strategy,
            context_refs=list(context["refs"]),
            next_actions=self._next_actions(answer, context),
            session_context=context["session_context"],
        )

    def _safe_context(self, agent_dir: Path) -> dict:
        project = self.store.read(agent_dir / "project.json", "project_config")
        policy = load_policy_config(agent_dir, self.validator)
        run_store = RunStore(agent_dir, self.validator)
        current_run_id = run_store.current_session_id()
        current_run = run_store.load_run(current_run_id) if current_run_id else None
        runtime_context = ContextLoader(self.root, self.validator).load()
        session_context = self._session_context(agent_dir, current_run_id, current_run)
        return {
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
            },
            "current_run": {
                "run_id": current_run.get("run_id"),
                "status": current_run.get("status"),
                "current_phase": current_run.get("current_phase"),
                "summary": current_run.get("summary"),
            }
            if current_run
            else None,
            "session_context": session_context,
            "runtime_summary": {
                "important_paths": runtime_context.get("important_paths", [])[:10],
                "guidance": runtime_context.get("guidance", {}) != {},
            },
            "refs": [".asteria/project.json", ".asteria/policies.json"]
            + ([f".asteria/runs/{current_run_id}/run.json"] if current_run_id else []),
        }

    def _session_context(
        self,
        agent_dir: Path,
        current_run_id: str | None,
        current_run: dict | None,
    ) -> dict:
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
        }

    def _read_json(self, path: Path, schema_name: str) -> dict:
        if not path.exists():
            return {}
        return self.store.read(path, schema_name)

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _latest_model_selection(self, run_dir: Path) -> dict:
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

    def _model_route_timeline(self, run_dir: Path) -> list[dict]:
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

    def _workflow_state(self, run: dict) -> str:
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

    def _recommended_next_command(self, run: dict) -> str | None:
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

    def _model_tier(self, default_tier: str = "medium") -> str:
        if self.model_strategy == "economy":
            return "cheap"
        if self.model_strategy == "quality":
            return "strong"
        return default_tier

    def _next_actions(self, answer: str, context: dict) -> list[str]:
        actions: list[str] = []
        lowered = self.question.lower()
        execution_words = [
            "modify",
            "change files",
            "implement",
            "build",
            "fix",
            "execute",
            "run it",
            "apply change",
            "edit file",
            "repair",
            "write code",
        ]
        if any(word in lowered for word in execution_words):
            actions.append("Use `asteria plan` for read-only analysis or `asteria goal` to execute.")
        workflow = (context.get("session_context") or {}).get("workflow") or {}
        recommended = workflow.get("recommended_next_command")
        if recommended and recommended not in {"plan", "init"}:
            actions.append(f"Current session recommends `asteria {recommended}`.")
        return list(dict.fromkeys(actions))

    def _clean_answer(self, answer: str) -> str:
        cleaned = answer.strip()
        while True:
            lower = cleaned.lower()
            start = lower.find("<think>")
            end = lower.find("</think>", start + len("<think>")) if start != -1 else -1
            if start == -1 or end == -1:
                break
            cleaned = (cleaned[:start] + cleaned[end + len("</think>") :]).strip()
        return self._repair_mojibake(cleaned)

    def _repair_mojibake(self, text: str) -> str:
        if not text:
            return text
        suspicious = sum(text.count(ch) for ch in ("?", "?", "?", "?", "--"))
        if suspicious < 3:
            return text
        try:
            repaired = text.encode("latin1", errors="ignore").decode("utf-8", errors="ignore").strip()
        except UnicodeError:
            return text
        return repaired if len(repaired) >= max(20, len(text) * 0.35) else text

    def _system_prompt(self) -> str:
        return """You are Asteria in chat mode.

Chat mode is lightweight Q&A. Answer clearly and concisely.
Do not claim to have modified files or run state-changing commands.
If the user asks for implementation, suggest plan mode for read-only analysis or goal mode for execution.
Use safe_project_context to summarize current session state, blockers, latest evidence, and model route rationale when relevant.
When asked why a model route was used, answer from session_context.model_route_timeline before using general reasoning.
Respect protected paths and do not request secrets."""
