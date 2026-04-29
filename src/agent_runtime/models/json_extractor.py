from __future__ import annotations

import ast
import json
import re
from typing import Any


class JsonExtractionError(ValueError):
    pass


def parse_json_object(content: str) -> dict[str, Any]:
    text = _strip_wrappers(content)
    try:
        parsed = _loads_candidate(text)
    except (json.JSONDecodeError, ValueError, SyntaxError):
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    candidates = _json_object_candidates(text)
    if not candidates:
        raise JsonExtractionError("No JSON object found in model response.")

    last_error: Exception | None = None
    for candidate in reversed(candidates):
        try:
            parsed = _loads_candidate(candidate)
        except (json.JSONDecodeError, ValueError, SyntaxError) as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
        last_error = JsonExtractionError("Extracted JSON value was not an object.")

    if last_error:
        raise JsonExtractionError(f"Could not parse JSON object from model response: {last_error}")
    raise JsonExtractionError("Could not parse JSON object from model response.")


def _strip_wrappers(content: str) -> str:
    text = content.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    return text


def _json_object_candidates(content: str) -> list[str]:
    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(content):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(content[start : index + 1])
                start = None
    return candidates


def _loads_candidate(candidate: str) -> Any:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = _repair_common_json(candidate)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return ast.literal_eval(repaired)


def _repair_common_json(candidate: str) -> str:
    repaired = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)", r'\1"\2"\3', candidate)
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired
