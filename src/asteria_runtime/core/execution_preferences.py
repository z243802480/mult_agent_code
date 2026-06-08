from __future__ import annotations

import re


def normalize_execution_preferences(value: object, *, original_goal: str = "") -> dict:
    """Preserve explicit user execution controls without routing by domain keywords."""

    del value
    delegation = "required" if _explicit_subagent_request(original_goal) else "auto"
    requested_capability = "subagent" if delegation == "required" else None
    requested_read_scope = _explicit_directory_scopes(original_goal)
    return {
        "delegation": delegation,
        "requested_capability": requested_capability,
        "requested_read_scope": list(dict.fromkeys(requested_read_scope)),
    }


def apply_execution_preferences_to_task(task: dict, goal_spec: dict | None) -> None:
    if not isinstance(goal_spec, dict):
        return
    preferences = normalize_execution_preferences(
        goal_spec.get("execution_preferences"),
        original_goal=str(goal_spec.get("original_goal") or ""),
    )
    task["execution_preferences"] = preferences
    requested_scope = preferences["requested_read_scope"]
    if requested_scope:
        current = _string_list(task.get("read_scope"))
        task["read_scope"] = list(dict.fromkeys([*current, *requested_scope]))


def _explicit_subagent_request(text: str) -> bool:
    normalized = str(text or "").lower()
    english = (
        re.search(
            r"\b(?:delegate|delegated|delegation|use|assign|dispatch)\b"
            r"[^.\n]{0,100}\b(?:subagent|sub-agent|child agent)\b",
            normalized,
        )
        or re.search(
            r"\b(?:subagent|sub-agent|child agent)\b"
            r"[^.\n]{0,100}\b(?:must|should|required|delegate|perform|inspect|review)\b",
            normalized,
        )
    )
    chinese = re.search(r"(?:委托|分派|交给|使用).{0,40}(?:子智能体|子代理|子 agent)", normalized)
    return bool(english or chinese)


def _explicit_directory_scopes(text: str) -> list[str]:
    scopes: list[str] = []
    for match in re.finditer(
        r"(?<![\w.-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*/)(?=\s|[,.):;]|$)",
        str(text or ""),
    ):
        path = match.group(1).replace("\\", "/").strip()
        if path and ".." not in path:
            scopes.append(path)
    return list(dict.fromkeys(scopes))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).replace("\\", "/").strip() for item in value if str(item).strip()]
