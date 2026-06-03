from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from asteria_runtime.commands.control_surface_contract import control_surface_contract
from asteria_runtime.core.agent_role_policy import role_contract_for
from asteria_runtime.core.chat_context_builder import ChatContextBuilder
from asteria_runtime.core.chat_intent_policy import ChatIntentPolicy
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.factory import create_model_client
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
    debug_details: bool = False

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
                    "debug_details",
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
            "debug_details": self.debug_details,
        }

    def to_text(self) -> str:
        lines = ["Asteria", "", self.answer]
        if self.debug_details:
            lines[1:1] = [
                f"Permission level: {self.permission_level}",
                f"Model strategy: {self.model_strategy}",
                "",
            ]
        if self.debug_details and self.context_refs:
            lines.extend(["", "Context refs:"])
            lines.extend(f"- {item}" for item in self.context_refs)
        if self.debug_details and self.session_context:
            current = self.session_context.get("current_run") or {}
            workflow = self.session_context.get("workflow") or {}
            main_path = self.session_context.get("main_path") or {}
            route_timeline = self.session_context.get("model_route_timeline") or []
            lines.extend(
                [
                    "",
                    "Current session:",
                    f"- run: {current.get('run_id') or 'none'}",
                    f"- state: {workflow.get('workflow_state') or 'unknown'}",
                    f"- next: {workflow.get('recommended_next_command') or 'none'}",
                    f"- main path: {main_path.get('current_step') or 'unknown'}",
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
        chat_intent = ChatIntentPolicy().classify(self.question)
        context, context_envelope, context_envelope_path = ChatContextBuilder(
            self.root,
            self.validator,
            permission_level=self.permission_level,
        ).build_and_persist(
            intent=chat_intent,
        )
        context_envelope_payload = context_envelope.to_dict()
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
                                "context": context_envelope_payload,
                                "context_envelope": context_envelope_payload,
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
                    "context_envelope_id": context_envelope.envelope_id,
                    "context_envelope_hash": context_envelope.payload_hash,
                    "context_envelope_path": context_envelope_path.relative_to(
                        self.root
                    ).as_posix(),
                    "context_envelope_refs": context_envelope.refs,
                },
            )
        )
        debug_details = chat_intent == "debug_question"
        answer = self._clean_answer(response.content)
        if not debug_details:
            answer = self._user_facing_answer(answer, context)
        return ChatResult(
            question=self.question,
            answer=answer,
            root=self.root,
            permission_level=self.permission_level,
            model_strategy=self.model_strategy,
            context_refs=list(context["refs"]),
            next_actions=self._next_actions(answer, context),
            session_context=context["session_context"],
            debug_details=debug_details,
        )

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
        if (
            context.get("chat_intent") != "ordinary_chat"
            and recommended
            and recommended not in {"plan", "init"}
        ):
            actions.append(f"Current session recommends `asteria {recommended}`.")
        return list(dict.fromkeys(actions))

    def _user_facing_answer(self, answer: str, context: dict) -> str:
        if not self._contains_backend_terms(answer):
            return answer
        session = context.get("session_context") or {}
        memory = str(context.get("active_goal_memory") or "").strip()
        context_policy = context.get("context_policy") or {}
        if memory and context_policy.get("active_goal_memory_included"):
            return memory
        workflow = session.get("workflow") or {}
        current = session.get("current_run") or {}
        state = str(workflow.get("workflow_state") or current.get("status") or "unknown")
        next_command = workflow.get("recommended_next_command")
        summary = str(current.get("summary") or "当前项目会话已有可用进展。")
        if next_command:
            return f"{summary}\n\n当前状态：{state}。建议下一步运行 `asteria {next_command}`。"
        return f"{summary}\n\n当前状态：{state}。目前没有需要你立即处理的下一步。"

    def _contains_backend_terms(self, answer: str) -> bool:
        lowered = answer.lower()
        return any(
            term in lowered
            for term in (
                "run_id",
                "current run",
                "latest evidence",
                ".asteria/",
                "model_route",
                "model route",
                "evidence is",
            )
        )

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
Use context_envelope.payload to summarize current session state, blockers, latest evidence, and model route rationale when relevant.
When asked why a model route was used, answer from session_context.model_route_timeline before using general reasoning.
context_envelope.intent tells you why context was mounted.
active_goal_memory is mounted only for progress, status, plan, and next-step questions. Prefer it when it is available.
For ordinary user questions, do not infer from long-running task memory and do not turn the answer into a project status report.
Do not expose backend fields such as run_id, evidence paths, or model_route unless the user explicitly asks for debug details.
Respect protected paths and do not request secrets."""
