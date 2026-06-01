from __future__ import annotations

import json
import re
from dataclasses import dataclass

from asteria_runtime.agents.execution_action import normalize_execution_action
from asteria_runtime.core.context_prompt_view import context_prompt_view
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from asteria_runtime.storage.schema_validator import SchemaValidationError, SchemaValidator


class DebugAgentError(RuntimeError):
    pass


@dataclass
class DebugAgent:
    model_client: ModelClient
    validator: SchemaValidator

    def propose_repair(
        self,
        task: dict,
        goal_spec: dict,
        failure_evidence: dict,
        available_tools: list[str],
        run_id: str,
        runtime_context: dict | None = None,
    ) -> dict:
        messages = [
            ChatMessage(role="system", content=self._system_prompt()),
            ChatMessage(
                role="user",
                content=self._user_prompt(
                    task,
                    goal_spec,
                    failure_evidence,
                    available_tools,
                    runtime_context or {},
                ),
            ),
        ]
        last_error: Exception | None = None
        for attempt in range(2):
            request = ChatRequest(
                purpose="task_repair",
                model_tier="medium",
                messages=messages,
                response_format="json",
                temperature=0.15,
                max_output_tokens=5000,
                metadata={
                    "run_id": run_id,
                    "agent_id": "DebugAgent",
                    "task_id": task["task_id"],
                    "attempt": attempt + 1,
                    "runtime_profile_id": (runtime_context or {}).get("runtime_profile_id"),
                    "model_profile_id": (runtime_context or {}).get("model_profile_id"),
                    "agent_role_contract": (runtime_context or {}).get("agent_role_contract"),
                    **self._envelope_metadata(runtime_context or {}),
                },
            )
            response = self.model_client.chat(request)
            try:
                action = self._validated_action(response.content, task)
            except DebugAgentError as exc:
                last_error = exc
                messages.extend(
                    [
                        ChatMessage(role="assistant", content=response.content[:4000]),
                        ChatMessage(
                            role="user",
                            content=(
                                "Your previous repair response could not be used: "
                                f"{exc}. Return only one valid JSON object matching the schema."
                            ),
                        ),
                    ]
                )
                continue
            return action
        fallback = self._heuristic_repair_action(task, failure_evidence)
        if fallback:
            return fallback
        raise DebugAgentError(str(last_error) if last_error else "Repair action generation failed")

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
        return metadata

    def _validated_action(self, content: str, task: dict) -> dict:
        action = self._parse_json(content)
        action = self._unwrap_action(action)
        action = normalize_execution_action(action, task)
        if action.get("task_id") != task["task_id"]:
            raise DebugAgentError(f"Repair task_id mismatch: {action.get('task_id')} != {task['task_id']}")
        try:
            self.validator.validate("execution_action", action)
        except SchemaValidationError as exc:
            raise DebugAgentError(f"Repair action failed schema validation: {exc}") from exc
        return action

    def _parse_json(self, content: str) -> dict:
        try:
            parsed = parse_json_object(content)
        except JsonExtractionError as exc:
            raise DebugAgentError(f"Repair response was not valid JSON: {exc}") from exc
        return parsed

    def _unwrap_action(self, parsed: dict) -> dict:
        if self._looks_like_action(parsed):
            return parsed
        for key in (
            "execution_action",
            "repair_action",
            "action",
            "repair",
            "result",
            "response",
        ):
            value = parsed.get(key)
            if isinstance(value, dict) and self._looks_like_action(value):
                return value
        actions = parsed.get("actions")
        if isinstance(actions, list):
            for item in actions:
                if isinstance(item, dict) and self._looks_like_action(item):
                    return item
        return parsed

    def _looks_like_action(self, value: dict) -> bool:
        return any(
            key in value
            for key in (
                "tool_calls",
                "verification",
                "runtime_requests",
                "completion_notes",
                "summary",
            )
        )

    def _heuristic_repair_action(self, task: dict, failure_evidence: dict) -> dict:
        evidence_text = json.dumps(failure_evidence, ensure_ascii=False)
        match = re.search(r"NameError:\s+name '([A-Za-z_][A-Za-z0-9_]*)' is not defined", evidence_text)
        if not match:
            return {}
        undefined = match.group(1)
        replacement = _collapsed_duplicate_identifier(undefined)
        if not replacement or replacement == undefined:
            return {}
        path = _path_from_traceback_or_scope(evidence_text, task, undefined)
        if not path or "apply_patch" not in task.get("allowed_tools", []):
            return {}
        old_line = _line_with_identifier(evidence_text, undefined)
        new_line = old_line.replace(undefined, replacement, 1) if old_line else ""
        if not old_line or not new_line or old_line == new_line:
            return {}
        verification = _verification_from_failure(failure_evidence)
        action = {
            "schema_version": "0.1.0",
            "task_id": task["task_id"],
            "summary": f"Repair undefined identifier {undefined} by replacing it with {replacement}.",
            "tool_calls": [
                {
                    "tool_name": "apply_patch",
                    "args": {
                        "patch": (
                            f"--- a/{path}\n"
                            f"+++ b/{path}\n"
                            "@@\n"
                            f"-{old_line}\n"
                            f"+{new_line}\n"
                        )
                    },
                    "reason": "Apply a minimal deterministic repair for a repeated-name typo.",
                }
            ],
            "verification": verification,
            "completion_notes": f"Replaced {undefined} with {replacement} in {path}.",
        }
        self.validator.validate("execution_action", action)
        return action

    def _system_prompt(self) -> str:
        return """You are DebugAgent in a local-first autonomous development runtime.

Return only valid JSON matching the ExecutionAction schema. Do not wrap in markdown.

You must:
- Diagnose the blocked task using the supplied failure evidence.
- Propose the smallest repair that can plausibly satisfy the task acceptance criteria.
- Use only tools from allowed_tools and available_tools.
- Prefer editing the existing broken artifact instead of rewriting unrelated files.
- Include verification calls that directly prove the repair.
- Use cross-platform Python commands for verification; do not rely on Unix-only commands like cat, wc, grep, or sed.
- Do not use shell control operators or redirection in verification commands: &&, ||, ;, |, <, >, 2>, 2>&1.
- Do not use destructive cleanup commands like rm -rf; use a Python command for temporary test cleanup.
- If a verification command is expected to return a non-zero code, pass expected_returncodes in run_command args.
- When runtime_context.tool_observation_actions is present, choose one explicit action
  (diagnose, repair, replan, ask, or stop) and make the repair JSON reflect that choice.
- Avoid destructive commands, network calls, deployment, or secret access.
- For a documentation or text-only artifact repair, write the expected file directly when it is in scope. Do not request more context just to create a standalone checklist, note, README, markdown, or text file.
- For documentation/text-only verification, prefer a simple Python existence-and-nonempty check for the expected file. Do not generate complex Python one-liners that inspect unrelated files.
"""

    def _user_prompt(
        self,
        task: dict,
        goal_spec: dict,
        failure_evidence: dict,
        available_tools: list[str],
        runtime_context: dict,
    ) -> str:
        payload = {
            "task": task,
            "goal_spec": goal_spec,
            "failure_evidence": failure_evidence,
            "runtime_context": context_prompt_view(runtime_context),
            "available_tools": available_tools,
            "allowed_tools": task["allowed_tools"],
            "output_schema": {
                "schema_version": "0.1.0",
                "task_id": task["task_id"],
                "summary": "short repair summary",
                "tool_calls": [
                    {
                        "tool_name": "apply_patch",
                        "args": {"patch": "--- a/file.py\n+++ b/file.py\n..."},
                        "reason": "minimal repair",
                    }
                ],
                "verification": [
                    {
                        "tool_name": "run_command",
                        "args": {
                            "command": "python -m pytest",
                            "expected_returncodes": [0],
                        },
                        "reason": "verify repair; use expected_returncodes for expected non-zero CLI usage checks",
                    }
                ],
                "completion_notes": "what was repaired",
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


def _collapsed_duplicate_identifier(identifier: str) -> str:
    if len(identifier) % 2:
        return ""
    half = identifier[: len(identifier) // 2]
    return half if half and half + half == identifier else ""


def _path_from_traceback_or_scope(evidence_text: str, task: dict, identifier: str) -> str:
    normalized_evidence = re.sub(r"/+", "/", evidence_text.replace("\\", "/"))
    scope_paths = [
        re.sub(r"/+", "/", str(path).replace("\\", "/"))
        for path in [
            *list(task.get("expected_changed_files") or []),
            *list(task.get("expected_artifacts") or []),
        ]
    ]
    for path in scope_paths:
        if path and path in normalized_evidence:
            return path
    traceback_paths = re.findall(r'File "([^"]+)"', evidence_text)
    for raw_path in reversed(traceback_paths):
        path = raw_path.replace("\\", "/")
        for candidate in scope_paths:
            if candidate and path.endswith(candidate):
                return candidate
    if len(scope_paths) == 1 and identifier:
        return scope_paths[0]
    return ""


def _line_with_identifier(evidence_text: str, identifier: str) -> str:
    decoded = evidence_text.replace("\\n", "\n")
    for line in decoded.splitlines():
        stripped = line.rstrip()
        if identifier in stripped and not stripped.lstrip().startswith(("File ", "NameError:")):
            return stripped
    return ""


def _verification_from_failure(failure_evidence: dict) -> list[dict]:
    verification: list[dict] = []
    for failure in failure_evidence.get("verification_failures") or []:
        data = failure.get("data") if isinstance(failure, dict) else {}
        data = data if isinstance(data, dict) else {}
        command = data.get("requested_command") or data.get("command")
        if isinstance(command, str) and command:
            verification.append(
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": command,
                        "expected_returncodes": data.get("expected_returncodes") or [0],
                    },
                    "reason": "Rerun the failed verification after the deterministic repair.",
                }
            )
    if verification:
        return verification[:3]
    return []
