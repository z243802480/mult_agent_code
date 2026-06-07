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
        if self._runtime_managed_action(action):
            self.require_non_empty(action)
            return action
        prepared = self._normalize_structured_patches(action)
        prepared = self._normalize_inline_verification(prepared, task)
        prepared = self._ensure_planned_verification(prepared, task)
        prepared = self._replace_unsafe_verification(prepared, task, policy)
        prepared = self._stabilize_text_artifact_verification(prepared, task)
        prepared = self._drop_parent_list_for_text_artifact_write(prepared, task)
        prepared = self._drop_redundant_root_list_for_standalone_artifact(prepared, task)
        self.require_non_empty(prepared)
        return prepared

    def require_non_empty(self, action: dict) -> None:
        if self._runtime_managed_action(action):
            return
        if (
            not action.get("tool_calls")
            and not action.get("verification")
            and not action.get("runtime_requests")
        ):
            raise RuntimeError(
                "ExecutionAction contained no tool calls, verification, or runtime requests."
            )

    def _runtime_managed_action(self, action: dict) -> bool:
        decision = action.get("agent_loop_decision")
        next_action = decision.get("next_action") if isinstance(decision, dict) else None
        kind = str((next_action or {}).get("action") or "")
        return kind in {"subagent", "repair", "replan", "stop"}

    def _normalize_structured_patches(self, action: dict) -> dict:
        tool_calls = list(action.get("tool_calls") or [])
        normalized_calls = []
        changed = False
        for call in tool_calls:
            if call.get("tool_name") != "apply_patch":
                normalized_calls.append(call)
                continue
            args = dict(call.get("args") or {})
            patch_value = args.get("patch") if args.get("patch") is not None else args.get("diff")
            if isinstance(patch_value, str):
                normalized_calls.append(call)
                continue
            patch_text = self._structured_patch_to_unified_diff(patch_value)
            if not patch_text:
                patch_text = self._path_replace_args_to_unified_diff(args)
            if not patch_text:
                normalized_calls.append(call)
                continue
            args["patch"] = patch_text
            args.pop("diff", None)
            args.pop("path", None)
            args.pop("old_text", None)
            args.pop("new_text", None)
            updated = dict(call)
            updated["args"] = args
            normalized_calls.append(updated)
            changed = True
        if not changed:
            return action
        normalized = dict(action)
        normalized["tool_calls"] = normalized_calls
        return normalized

    def _structured_patch_to_unified_diff(self, patch_value: object) -> str | None:
        if not isinstance(patch_value, list):
            return None
        chunks: list[str] = []
        for file_patch in patch_value:
            if not isinstance(file_patch, dict):
                return None
            path = str(file_patch.get("path") or "").replace("\\", "/").strip()
            operations = file_patch.get("operations")
            if not path or not isinstance(operations, list):
                return None
            hunks: list[str] = []
            for operation in operations:
                if not isinstance(operation, dict) or operation.get("op") != "replace":
                    return None
                old_text = operation.get("old_text")
                new_text = operation.get("new_text")
                if not isinstance(old_text, str) or not isinstance(new_text, str):
                    return None
                hunks.append(self._replace_hunk(old_text, new_text))
            chunks.append(f"--- a/{path}\n+++ b/{path}\n" + "".join(hunks))
        return "".join(chunks) if chunks else None

    def _path_replace_args_to_unified_diff(self, args: dict) -> str | None:
        path = str(args.get("path") or "").replace("\\", "/").strip()
        old_text = args.get("old_text")
        new_text = args.get("new_text")
        if not path or not isinstance(old_text, str) or not isinstance(new_text, str):
            return None
        return f"--- a/{path}\n+++ b/{path}\n{self._replace_hunk(old_text, new_text)}"

    def _replace_hunk(self, old_text: str, new_text: str) -> str:
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        old_count = max(1, len(old_lines))
        new_count = max(1, len(new_lines))
        lines = [f"@@ -1,{old_count} +1,{new_count} @@\n"]
        lines.extend(f"-{line}\n" for line in old_lines)
        lines.extend(f"+{line}\n" for line in new_lines)
        return "".join(lines)

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
        replacement = self._planned_verification_calls(task)
        if not replacement:
            normalized = dict(action)
            normalized["verification"] = safe_verification
            normalized["verification"] = self._dedupe_tool_calls(normalized["verification"])
            return normalized
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
        text_suffixes = {".md", ".txt", ".rst", ".html", ".css", ".htm"}
        if not all(
            any(path.lower().endswith(suffix) for suffix in text_suffixes) for path in artifacts
        ):
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

    def _drop_redundant_root_list_for_standalone_artifact(self, action: dict, task: dict) -> dict:
        """Avoid broad root listings after a standalone artifact is already produced.

        Real model actions sometimes append ``list_files`` at ``.`` as a final sanity check after
        writing and verifying an explicit file artifact. In a sliced runtime, that broad read is not
        needed for completion and can incorrectly turn an otherwise verified task into a context
        request. Keep scoped directory listings and actions without verification intact.
        """
        if not action.get("verification") or not self._has_explicit_expected_artifacts(task):
            return action
        tool_calls = list(action.get("tool_calls") or [])
        if not any(call.get("tool_name") in {"write_file", "apply_patch"} for call in tool_calls):
            return action
        filtered = [
            call
            for call in tool_calls
            if not (
                call.get("tool_name") == "list_files"
                and str((call.get("args") or {}).get("path") or ".").strip() in {"", "."}
            )
        ]
        if len(filtered) == len(tool_calls):
            return action
        normalized = dict(action)
        normalized["tool_calls"] = filtered
        return normalized

    def _drop_parent_list_for_text_artifact_write(self, action: dict, task: dict) -> dict:
        """Avoid probing a parent directory that a scoped text artifact write may create.

        Real models often list ``docs`` before writing ``docs/foo.md``. In an empty smoke workspace
        that read fails before the write gets a chance to create the artifact, causing an otherwise
        deterministic low-risk task to enter repair. If the task has explicit text artifacts and the
        same action writes one of them, the parent listing is not needed for safety or verification.
        """
        artifacts = self._text_only_artifacts(task)
        if not artifacts:
            return action
        tool_calls = list(action.get("tool_calls") or [])
        write_paths = {
            str((call.get("args") or {}).get("path") or "").replace("\\", "/").strip()
            for call in tool_calls
            if call.get("tool_name") in {"write_file", "apply_patch"}
        }
        if not write_paths:
            return action
        parent_dirs = {
            path.rsplit("/", 1)[0]
            for path in artifacts
            if "/" in path and path in write_paths
        }
        if not parent_dirs:
            return action
        filtered = [
            call
            for call in tool_calls
            if not (
                call.get("tool_name") == "list_files"
                and str((call.get("args") or {}).get("path") or ".")
                .replace("\\", "/")
                .strip()
                .rstrip("/")
                in parent_dirs
            )
        ]
        if len(filtered) == len(tool_calls):
            return action
        normalized = dict(action)
        normalized["tool_calls"] = filtered
        return normalized

    def _has_explicit_expected_artifacts(self, task: dict) -> bool:
        return any(
            isinstance(path, str) and path.strip()
            for path in [
                *list(task.get("expected_artifacts") or []),
                *list(task.get("expected_changed_files") or []),
            ]
        )

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
