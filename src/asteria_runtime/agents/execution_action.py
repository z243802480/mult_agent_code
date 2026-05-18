from __future__ import annotations

import re

from asteria_runtime.core.runtime_request import normalize_runtime_requests
from asteria_runtime.agents.verification_command_normalizer import normalize_verification_command


def normalize_execution_action(action: dict, task: dict) -> dict:
    normalized = dict(action)
    normalized["schema_version"] = str(normalized.get("schema_version") or "0.1.0")
    normalized["task_id"] = str(normalized.get("task_id") or task["task_id"])
    normalized["summary"] = str(
        normalized.get("summary")
        or normalized.get("completion_notes")
        or f"Work on {task['task_id']}"
    )
    normalized["tool_calls"] = _normalize_tool_calls(normalized.get("tool_calls"), task)
    normalized["verification"] = _normalize_tool_calls(normalized.get("verification"), task)
    normalized["runtime_requests"] = normalize_runtime_requests(normalized.get("runtime_requests"))
    normalized["completion_notes"] = str(normalized.get("completion_notes") or normalized["summary"])
    return normalized


def _normalize_tool_calls(value: object, task: dict) -> list[dict]:
    if not isinstance(value, list):
        return []
    calls: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("tool_name") or item.get("name") or item.get("tool")
        if not tool_name:
            continue
        args = item.get("args") or item.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        args = _repair_tool_args(str(tool_name), args, task)
        call = {
            "tool_name": str(tool_name),
            "args": args,
        }
        reason = item.get("reason")
        if reason:
            call["reason"] = str(reason)
        calls.append(call)
    return calls


def _repair_tool_args(tool_name: str, args: dict, task: dict) -> dict:
    repaired = dict(args)
    if tool_name == "write_file":
        repaired.setdefault("path", _infer_path(task))
        repaired.setdefault("content", _infer_content(task))
        repaired.setdefault("overwrite", True)
        repaired = _repair_python_json_token_drift(repaired, task)
    if tool_name == "run_command" and isinstance(repaired.get("command"), str):
        repaired["command"] = normalize_verification_command(repaired["command"], task)
        repaired = _repair_command_json_token_drift(repaired, task)
    return {key: value for key, value in repaired.items() if value not in (None, "")}


def _repair_python_json_token_drift(args: dict, task: dict) -> dict:
    path = str(args.get("path") or "")
    content = args.get("content")
    if not path.endswith(".py") or not isinstance(content, str) or not _task_mentions_json(task):
        return args
    repaired = content
    if "import \n" in repaired and (".load(" in repaired or ".dump(" in repaired):
        repaired = repaired.replace("import \n", "import json\n", 1)
    repaired = repaired.replace("return .load(", "return json.load(")
    repaired = repaired.replace(".dump(", "json.dump(")
    repaired = repaired.replace("except (.JSONDecodeError", "except (json.JSONDecodeError")
    if repaired == content:
        return args
    normalized = dict(args)
    normalized["content"] = repaired
    return normalized


def _repair_command_json_token_drift(args: dict, task: dict) -> dict:
    command = args.get("command")
    if not isinstance(command, str) or not _task_mentions_json(task):
        return args
    repaired = command.replace("import ;", "import json;")
    repaired = repaired.replace("data = .load(", "data = json.load(")
    repaired = repaired.replace(".dump(", "json.dump(")
    if repaired == command:
        return args
    normalized = dict(args)
    normalized["command"] = repaired
    return normalized


def _task_mentions_json(task: dict) -> bool:
    return ".json" in _task_text(task).lower() or "json" in _task_text(task).lower()


def _infer_path(task: dict) -> str | None:
    text = _task_text(task)
    match = re.search(r"([A-Za-z0-9_.\-/\\]+\.txt)", text)
    if match:
        return match.group(1).strip("'\"")
    artifacts = task.get("expected_artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if isinstance(artifact, str) and "." in artifact and artifact != "implementation artifact":
                return artifact
    return None


def _infer_content(task: dict) -> str | None:
    text = _task_text(task)
    quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", text)
    for left, right in reversed(quoted):
        value = (left or right).strip()
        if value and not value.endswith(".txt"):
            return value
    marker = "content:"
    if marker in text.lower():
        return text.lower().split(marker, 1)[1].strip()
    return None


def _task_text(task: dict) -> str:
    parts = [
        str(task.get("title") or ""),
        str(task.get("description") or ""),
        " ".join(str(item) for item in task.get("acceptance", []) if item),
        str(task.get("notes") or ""),
    ]
    return " ".join(parts)
