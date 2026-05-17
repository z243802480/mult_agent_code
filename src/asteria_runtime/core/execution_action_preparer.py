from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Callable

from asteria_runtime.core.task_contract import validation_commands


ShellDenial = Callable[[dict, str], str | None]


@dataclass(frozen=True)
class ExecutionActionPreparer:
    shell_denial: ShellDenial

    def prepare(self, action: dict, task: dict, policy: dict) -> dict:
        prepared = self._normalize_inline_verification(action, task)
        prepared = self._ensure_planned_verification(prepared, task)
        prepared = self._replace_unsafe_verification(prepared, task, policy)
        prepared = self._stabilize_text_artifact_verification(prepared, task)
        prepared = self._prepend_python_compile_verification(prepared, task)
        self.require_non_empty(prepared)
        return prepared

    def require_non_empty(self, action: dict) -> None:
        if (
            not action.get("tool_calls")
            and not action.get("verification")
            and not action.get("runtime_requests")
        ):
            raise RuntimeError(
                "ExecutionAction contained no tool calls, verification, or runtime requests."
            )

    def _normalize_inline_verification(self, action: dict, task: dict) -> dict:
        if action.get("verification") or not task.get("verification_policy", {}).get("required"):
            return action
        tool_calls = list(action.get("tool_calls") or [])
        verification = [
            call for call in tool_calls if call.get("tool_name") in {"run_command", "run_tests"}
        ]
        if not verification:
            return action
        normalized = dict(action)
        normalized["tool_calls"] = [
            call for call in tool_calls if call.get("tool_name") not in {"run_command", "run_tests"}
        ]
        normalized["verification"] = verification
        return normalized

    def _replace_unsafe_verification(self, action: dict, task: dict, policy: dict) -> dict:
        verification = list(action.get("verification") or [])
        if not verification:
            return action
        safe_verification = []
        replaced = False
        for call in verification:
            if call.get("tool_name") not in {"run_command", "run_tests"}:
                safe_verification.append(call)
                continue
            command = str(call.get("args", {}).get("command") or "")
            denial = self.shell_denial(policy, command) if command else None
            if not command or denial is None:
                safe_verification.append(call)
                continue
            if not self._can_replace_verification_denial(denial):
                safe_verification.append(call)
                continue
            replaced = True
        if not replaced:
            return action
        replacement = self._planned_verification_calls(task) or self._default_verification_calls(
            task, action
        )
        normalized = dict(action)
        normalized["verification"] = [
            *safe_verification,
            *replacement,
        ]
        normalized["verification"] = self._dedupe_tool_calls(normalized["verification"])
        return normalized

    def _can_replace_verification_denial(self, denial: str) -> bool:
        return any(
            denial.endswith(f": {operator}")
            for operator in {"|", ">", ">>", "<", "2>", "2>>", "&&"}
        )

    def _ensure_planned_verification(self, action: dict, task: dict) -> dict:
        if action.get("verification") or not task.get("verification_policy", {}).get("required"):
            return action
        planned = self._planned_verification_calls(task)
        if not planned:
            return action
        normalized = dict(action)
        normalized["verification"] = planned
        return normalized

    def _planned_verification_calls(self, task: dict) -> list[dict]:
        if "run_command" not in set(task.get("allowed_tools", [])):
            return []
        calls = []
        for item in validation_commands(task):
            command = self._extract_safe_planned_command(item)
            if command:
                calls.append(
                    {
                        "tool_name": "run_command",
                        "args": {"command": command, "expected_returncodes": [0]},
                        "reason": "planned task verification",
                    }
                )
        return self._dedupe_tool_calls(calls)

    def _extract_safe_planned_command(self, text: str) -> str | None:
        candidates: list[str] = []
        if "`" in text:
            parts = text.split("`")
            candidates.extend(parts[index] for index in range(1, len(parts), 2))
        candidates.extend(
            match.group(1)
            for match in re.finditer(
                r"['\"]((?:python|pytest|ruff|mypy)\s+[^'\"]+)['\"]",
                text,
                flags=re.I,
            )
        )
        stripped = text.strip()
        candidates.append(stripped)
        for candidate in candidates:
            command = candidate.strip()
            if command.startswith(("python ", "pytest ", "ruff ", "mypy ")):
                return command
        return None

    def _default_verification_calls(self, task: dict, action: dict) -> list[dict]:
        calls = []
        artifacts = [
            *[
                str(call.get("args", {}).get("path"))
                for call in action.get("tool_calls", [])
                if call.get("tool_name") == "write_file" and call.get("args", {}).get("path")
            ],
            *[
                str(artifact)
                for artifact in task.get("expected_artifacts", [])
                if isinstance(artifact, str)
            ],
        ]
        for artifact in dict.fromkeys(artifacts):
            if not isinstance(artifact, str) or not artifact.endswith(".py"):
                continue
            calls.append(
                {
                    "tool_name": "run_command",
                    "args": {
                        "command": f"python -m py_compile {artifact}",
                        "expected_returncodes": [0],
                    },
                    "reason": "safe fallback verification for Python artifact",
                }
            )
        return calls or [
            {
                "tool_name": "run_command",
                "args": {
                    "command": "python -c \"print('verification placeholder')\"",
                    "expected_returncodes": [0],
                },
                "reason": "safe fallback verification",
            }
        ]

    def _stabilize_text_artifact_verification(self, action: dict, task: dict) -> dict:
        artifacts = self._text_only_artifacts(task)
        if not artifacts or "run_command" not in set(task.get("allowed_tools", [])):
            return action
        if action.get("verification") and not self._has_broken_text_verification(action):
            return action
        normalized = dict(action)
        normalized["verification"] = [
            {
                "tool_name": "run_command",
                "args": {
                    "command": self._text_artifact_verification_command(artifacts),
                    "expected_returncodes": [0],
                },
                "reason": "stable verification for text-only artifact task",
            }
        ]
        return normalized

    def _has_broken_text_verification(self, action: dict) -> bool:
        for call in action.get("verification") or []:
            if call.get("tool_name") != "run_command":
                continue
            command = str(call.get("args", {}).get("command") or "")
            code = self._python_c_code(command)
            if code is None:
                continue
            if '"' in code:
                return True
            try:
                ast.parse(code)
            except SyntaxError:
                return True
        return False

    def _python_c_code(self, command: str) -> str | None:
        stripped = command.strip()
        marker = ' -c "'
        if not stripped.lower().startswith(("python -c ", "python3 -c ")) or marker not in stripped:
            return None
        if not stripped.endswith('"'):
            return None
        return stripped.split(marker, 1)[1][:-1]

    def _text_only_artifacts(self, task: dict) -> list[str]:
        artifacts = [
            str(path).replace("\\", "/")
            for path in [
                *task.get("expected_changed_files", []),
                *task.get("expected_artifacts", []),
            ]
            if isinstance(path, str) and str(path).strip()
        ]
        artifacts = list(dict.fromkeys(artifacts))
        if not artifacts:
            return []
        text_suffixes = {".md", ".txt", ".rst"}
        if not all(any(path.lower().endswith(suffix) for suffix in text_suffixes) for path in artifacts):
            return []
        return artifacts

    def _text_artifact_verification_command(self, artifacts: list[str]) -> str:
        encoded = repr(artifacts)
        code = (
            "from pathlib import Path; "
            f"paths={encoded}; "
            "missing=[p for p in paths if not Path(p).exists() or not Path(p).read_text(encoding='utf-8').strip()]; "
            "raise SystemExit(('missing or empty: '+', '.join(missing)) if missing else 0)"
        )
        return f'python -c "{code}"'

    def _prepend_python_compile_verification(self, action: dict, task: dict) -> dict:
        if not action.get("verification"):
            return action
        artifacts = [
            str(path)
            for path in [
                *task.get("expected_changed_files", []),
                *task.get("expected_artifacts", []),
            ]
            if str(path).endswith(".py")
        ]
        if not artifacts or "run_command" not in set(task.get("allowed_tools", [])):
            return action
        compile_calls = [
            {
                "tool_name": "run_command",
                "args": {"command": f"python -m py_compile {artifact}"},
                "reason": "fail fast on Python syntax errors before behavior checks",
            }
            for artifact in sorted(set(artifacts))
        ]
        normalized = dict(action)
        normalized["verification"] = self._dedupe_tool_calls(
            [*compile_calls, *list(action.get("verification") or [])]
        )
        return normalized

    def _dedupe_tool_calls(self, calls: list[dict]) -> list[dict]:
        deduped = []
        seen = set()
        for call in calls:
            key = json.dumps(call, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(call)
        return deduped
