from __future__ import annotations

import json
from dataclasses import dataclass

from asteria_runtime.agents.execution_action import normalize_execution_action
from asteria_runtime.core.agent_loop_decision import (
    AgentLoopDecisionError,
    normalize_agent_loop_decision,
    validate_decision_matches_execution_action,
)
from asteria_runtime.core.context_prompt_view import context_prompt_view
from asteria_runtime.core.context_slimming import slim_execution_context
from asteria_runtime.core.worker_transport import (
    execution_action_from_tool_calls,
    extract_tool_calls,
    resolve_worker_transport,
    tool_definitions_for,
)
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class CoderAgentError(RuntimeError):
    pass


@dataclass
class CoderAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def propose_action(
        self,
        task: dict,
        goal_spec: dict,
        project_config: dict,
        available_tools: list[str],
        run_id: str,
        runtime_context: dict | None = None,
    ) -> dict:
        base_runtime_context = runtime_context or {}
        prompt_runtime_context = slim_execution_context(
            base_runtime_context,
            task=task,
            goal_spec=goal_spec,
        )
        transport = resolve_worker_transport(runtime_context=base_runtime_context)
        messages = [
            ChatMessage(role="system", content=self._system_prompt()),
            ChatMessage(
                role="user",
                content=self._user_prompt(
                    task,
                    goal_spec,
                    project_config,
                    available_tools,
                    prompt_runtime_context,
                ),
            ),
        ]
        last_error: Exception | None = None
        for attempt in range(2):
            request = ChatRequest(
                purpose="task_execution",
                model_tier="medium",
                messages=messages,
                response_format="json" if transport == "json" else None,
                temperature=0.2,
                max_output_tokens=5000,
                worker_transport=transport,
                tools=tool_definitions_for(available_tools) if transport == "tool_use" else None,
                metadata={
                    "run_id": run_id,
                    "agent_id": "CoderAgent",
                    "task_id": task["task_id"],
                    "attempt": attempt + 1,
                    "worker_transport": transport,
                    "runtime_profile_id": base_runtime_context.get("runtime_profile_id"),
                    "model_profile_id": base_runtime_context.get("model_profile_id"),
                    "agent_role_contract": base_runtime_context.get("agent_role_contract"),
                    **self._envelope_metadata(prompt_runtime_context),
                },
            )
            response = self.model_client.chat(request)
            try:
                if transport == "tool_use":
                    tool_calls = extract_tool_calls(response.raw_response)
                    action = self._validated_action_from_tool_calls(
                        tool_calls,
                        task,
                        run_id,
                        sequence=self._loop_sequence(runtime_context or {}),
                    )
                else:
                    action = self._validated_action(
                        response.content,
                        task,
                        run_id,
                        sequence=self._loop_sequence(runtime_context or {}),
                    )
            except CoderAgentError as exc:
                last_error = exc
                messages.extend(
                    [
                        ChatMessage(role="assistant", content=response.content[:4000]),
                        ChatMessage(
                            role="user",
                            content=(
                                "Your previous response could not be used: "
                                f"{exc}. Return only one valid JSON object matching the schema."
                            ),
                        ),
                    ]
                )
                continue
            return action
        raise CoderAgentError(
            str(last_error) if last_error else "ExecutionAction generation failed"
        )

    def _validated_action_from_tool_calls(
        self,
        tool_calls: list[dict],
        task: dict,
        run_id: str,
        *,
        sequence: int = 1,
    ) -> dict:
        if not tool_calls:
            raise CoderAgentError("tool_use transport returned no tool calls")
        action = execution_action_from_tool_calls(
            task=task,
            run_id=run_id,
            sequence=sequence,
            tool_calls=tool_calls,
        )
        action = normalize_execution_action(action, task)
        try:
            loop_decision = normalize_agent_loop_decision(
                action,
                task=task,
                run_id=run_id,
                sequence=sequence,
            )
            validate_decision_matches_execution_action(loop_decision, action)
        except AgentLoopDecisionError as exc:
            raise CoderAgentError(f"AgentLoopDecision failed validation: {exc}") from exc
        action["agent_loop_decision"] = loop_decision
        try:
            self.validator.validate("execution_action", action)
        except SchemaValidationError as exc:
            raise CoderAgentError(f"ExecutionAction failed schema validation: {exc}") from exc
        return action

    def _envelope_metadata(self, runtime_context: dict) -> dict:
        metadata: dict = {}
        envelope = runtime_context.get("prompt_envelope")
        if isinstance(envelope, dict):
            metadata.update(
                {
                    "prompt_envelope_hash": envelope.get("content_hash"),
                    "prompt_envelope_path": envelope.get("path"),
                    "capability_manifest_hash": envelope.get("capability_manifest_hash"),
                }
            )
        context_package = runtime_context.get("context_package")
        if isinstance(context_package, dict):
            context_envelope = context_package.get("context_envelope")
            if isinstance(context_envelope, dict):
                metadata["context_envelope_hash"] = context_envelope.get("payload_hash")
            metadata["context_envelope_path"] = context_package.get("context_envelope_path")
        context_policy = runtime_context.get("context_policy")
        if isinstance(context_policy, dict):
            metadata["context_mode"] = context_policy.get("mode")
            fast_path = context_policy.get("fast_path")
            if isinstance(fast_path, dict):
                metadata["fast_path_task_kind"] = fast_path.get("task_kind")
        return metadata

    def _validated_action(
        self,
        content: str,
        task: dict,
        run_id: str,
        *,
        sequence: int = 1,
    ) -> dict:
        action = self._parse_json(content)
        action = normalize_execution_action(action, task)
        try:
            loop_decision = normalize_agent_loop_decision(
                action,
                task=task,
                run_id=run_id,
                sequence=sequence,
            )
            validate_decision_matches_execution_action(loop_decision, action)
        except AgentLoopDecisionError as exc:
            raise CoderAgentError(f"AgentLoopDecision failed validation: {exc}") from exc
        action["agent_loop_decision"] = loop_decision
        if action.get("task_id") != task["task_id"]:
            raise CoderAgentError(
                f"ExecutionAction task_id mismatch: {action.get('task_id')} != {task['task_id']}"
            )
        next_action = loop_decision.get("next_action") or {}
        next_action_kind = str(next_action.get("action") or "")
        if (
            next_action_kind == "tool"
            and not action.get("tool_calls")
            and not action.get("verification")
            and not action.get("runtime_requests")
        ):
            raise CoderAgentError(
                "ExecutionAction must include at least one tool call, verification command, or runtime request"
            )
        try:
            self.validator.validate("execution_action", action)
        except SchemaValidationError as exc:
            raise CoderAgentError(f"ExecutionAction failed schema validation: {exc}") from exc
        return action

    def _loop_sequence(self, runtime_context: dict) -> int:
        raw = runtime_context.get("agent_loop_round")
        round_context = raw if isinstance(raw, dict) else {}
        try:
            return max(1, int(round_context.get("index") or 1))
        except (TypeError, ValueError):
            return 1

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = parse_json_object(content)
        except JsonExtractionError as exc:
            raise CoderAgentError(f"ExecutionAction response was not valid JSON: {exc}") from exc
        return parsed

    def _system_prompt(self) -> str:
        return """You are CoderAgent in a local-first autonomous development runtime.

Return only valid JSON matching the ExecutionAction schema. Do not wrap in markdown.

You must:
- Explicitly choose exactly one agent_loop_decision.next_action.action: tool, subagent, repair, replan, ask, or stop.
- Every next action must include reason, target_task_id, capability_ref, expected_observation, risk, budget_hint, and evidence_refs.
- Make a small, verifiable change for the assigned task.
- Use only tools from available_tools. These are model-facing primitives backed by runtime policy.
- Prefer edit_file for editing existing files and write_file for new files.
- Prefer grep/glob/read_file/list_files before shell, and prefer run_tests for verification.
- Include verification tool calls when possible.
- Use cross-platform Python commands for verification; do not rely on Unix-only commands like cat, wc, grep, or sed.
- Do not use shell control operators or redirection in verification commands: &&, ||, ;, |, <, >, 2>, 2>&1.
- Do not use destructive cleanup commands like rm -rf; use a Python command for temporary test cleanup.
- If a verification command is expected to return a non-zero code, pass expected_returncodes in run_command args.
- Avoid destructive commands, global installs, deployment, or network calls unless explicitly allowed.
- Keep the implementation practical and production-oriented; do not create placeholder-only files.
- If the task contract is too narrow, request a runtime change with runtime_requests instead of attempting an out-of-scope tool call.
- For a new documentation or text-only artifact with an explicit expected_artifacts/write_scope path, write the file directly. Do not request more context merely to create a standalone checklist, note, README, markdown, or text file.
- For documentation/text-only verification, prefer a simple Python existence-and-nonempty check for the expected file. Do not generate complex Python one-liners that inspect unrelated files.
"""

    def _user_prompt(
        self,
        task: dict,
        goal_spec: dict,
        project_config: dict,
        available_tools: list[str],
        runtime_context: dict,
    ) -> str:
        payload = {
            "task": task,
            "goal_spec": goal_spec,
            "task_contract": runtime_context.get("task_contract")
            or {
                "read_scope": task.get("read_scope", []),
                "write_scope": task.get("write_scope", []),
                "expected_artifacts": task.get("expected_artifacts", []),
                "validation_commands": task.get("validation_commands", []),
                "failure_policy": task.get("failure_policy"),
                "parallel_safety": task.get("parallel_safety"),
                "risk_tier": task.get("risk_tier"),
            },
            "project": project_config,
            "runtime_context": context_prompt_view(runtime_context),
            "available_tools": available_tools,
            "allowed_tools": task["allowed_tools"],
            "model_tool_surface": runtime_context.get("model_tool_surface", {}),
            "output_schema": {
                "schema_version": "0.1.0",
                "task_id": task["task_id"],
                "summary": "short execution summary",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "args": {"path": "example.txt", "content": "...", "overwrite": True},
                        "reason": "why this call is needed",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_tests",
                        "args": {
                            "command": "python -m pytest",
                            "expected_returncodes": [0],
                        },
                        "reason": "verify the change; use expected_returncodes for expected non-zero CLI usage checks",
                    }
                ],
                "runtime_requests": [
                    {
                        "request_type": "scope_expansion",
                        "risk": "medium",
                        "reason": "why the current task contract is insufficient",
                        "details": {"write_scope": ["path/to/requested_file.py"]},
                    }
                ],
                "agent_loop_decision": {
                    "next_action": {
                        "action": "tool",
                        "reason": "why this is the correct next runtime action",
                        "target_task_id": task["task_id"],
                        "capability_ref": {"type": "tool", "name": "write_file"},
                        "expected_observation": {
                            "summary": "what tool observation should prove"
                        },
                        "risk": "medium",
                        "budget_hint": {"model_calls": 1, "tool_budget_units": 1},
                        "evidence_refs": [],
                    }
                },
                "completion_notes": "what should be true after execution",
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
