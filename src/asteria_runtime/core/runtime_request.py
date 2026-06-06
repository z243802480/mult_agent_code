from __future__ import annotations

from dataclasses import dataclass, field


REQUEST_TYPES = {
    "scope_expansion",
    "context_request",
    "tool_request",
    "budget_request",
    "model_upgrade_request",
    "decision_request",
}

RISKS = {"low", "medium", "high"}


@dataclass(frozen=True)
class RuntimeRequest:
    runtime_request_id: str
    run_id: str | None
    task_id: str
    request_type: str
    risk: str
    reason: str
    details: dict = field(default_factory=dict)
    status: str = "recorded"
    decision_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "runtime_request_id": self.runtime_request_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "request_type": self.request_type,
            "risk": self.risk,
            "reason": self.reason,
            "details": self.details,
            "status": self.status,
            "decision_id": self.decision_id,
            "created_at": self.created_at,
        }


def normalize_runtime_requests(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    requests: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        request_type = str(item.get("request_type") or item.get("type") or "").strip()
        if request_type not in REQUEST_TYPES:
            continue
        risk = str(item.get("risk") or "").strip().lower()
        if risk not in RISKS:
            risk = _infer_risk(request_type, item.get("details"))
        reason = str(item.get("reason") or item.get("summary") or "").strip()
        if not reason:
            reason = f"Model requested {request_type}."
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        requests.append(
            {
                "request_type": request_type,
                "risk": risk,
                "reason": reason,
                "details": details,
            }
        )
    return requests


def _infer_risk(request_type: str, details: object) -> str:
    if request_type in {"budget_request", "model_upgrade_request", "decision_request"}:
        return "medium"
    if request_type == "scope_expansion" and isinstance(details, dict):
        if details.get("write_scope") or details.get("requested_write_scope"):
            return "medium"
    if request_type == "tool_request" and isinstance(details, dict):
        requested = details.get("tool") or details.get("tool_name") or details.get("allowed_tools")
        if requested:
            return "medium"
    return "low"


def scope_paths(request: dict) -> list[str]:
    details = request.get("details")
    payload = details if isinstance(details, dict) else {}
    paths: list[str] = []
    for key in ("write_scope", "requested_write_scope", "read_scope", "requested_read_scope"):
        value = payload.get(key)
        if isinstance(value, list):
            paths.extend(str(item) for item in value if item)
        elif value:
            paths.append(str(value))
    return paths


def is_benign_workspace_scope(paths: list[str]) -> bool:
    if not paths:
        return False
    for raw in paths:
        raw_norm = str(raw).replace("\\", "/").strip()
        if not raw_norm or ".." in raw_norm:
            return False
        normalized = raw_norm.lstrip("./")
        parts = [part for part in normalized.split("/") if part]
        if len(parts) != 1:
            return False
        if parts[0].startswith(".env") or parts[0] in {".git", "secrets"}:
            return False
        if not parts[0].endswith((".py", ".md", ".txt")):
            return False
    return True


def is_benign_context_paths(paths: list[str]) -> bool:
    if not paths:
        return False
    for raw in paths:
        normalized = str(raw).replace("\\", "/").strip().lstrip("./")
        if normalized in {"", "."}:
            continue
        if ".." in normalized:
            return False
        if normalized.startswith(".env") or normalized.startswith("secrets/"):
            return False
        if normalized == "docs" or normalized.startswith("docs/"):
            continue
        candidate = str(raw).replace("\\", "/").strip()
        if not is_benign_workspace_scope([candidate]):
            return False
    return True


def effective_runtime_request_risk(request: dict, *, auto_allow_low_risk: bool) -> str:
    risk = str(request.get("risk") or _infer_risk(str(request.get("request_type") or ""), request.get("details")))
    if not auto_allow_low_risk:
        return risk
    request_type = str(request.get("request_type") or "")
    paths = scope_paths(request)
    if request_type == "context_request" and is_benign_context_paths(paths):
        return "low"
    if risk == "medium" and request_type == "scope_expansion" and is_benign_workspace_scope(paths):
        return "low"
    return risk


def apply_runtime_request_to_task(task: dict, request: dict) -> bool:
    request_type = str(request.get("request_type") or "")
    raw_details = request.get("details")
    details: dict = raw_details if isinstance(raw_details, dict) else {}
    if request_type == "scope_expansion":
        changed = False
        changed |= _merge_list_field(
            task,
            "read_scope",
            _detail_list(details, "read_scope", "requested_read_scope"),
        )
        changed |= _merge_list_field(
            task,
            "write_scope",
            _detail_list(details, "write_scope", "requested_write_scope"),
        )
        return changed
    if request_type == "context_request":
        changed = _merge_list_field(
            task,
            "read_scope",
            _detail_list(details, "read_scope", "requested_read_scope", "paths"),
        )
        context_requirements = dict(task.get("context_requirements") or {})
        requested = details.get("context_requirements") if isinstance(details, dict) else {}
        if not isinstance(requested, dict):
            requested = details
        if requested:
            context_requirements.update(requested)
            task["context_requirements"] = context_requirements
            changed = True
        return changed
    if request_type == "tool_request":
        tools = _detail_list(details, "allowed_tools", "tools", "tool", "tool_name")
        return _merge_list_field(task, "allowed_tools", tools)
    if request_type == "budget_request":
        hints = dict(task.get("runtime_profile_hints") or {})
        hints["budget"] = details
        task["runtime_profile_hints"] = hints
        return True
    if request_type == "model_upgrade_request":
        hints = dict(task.get("runtime_profile_hints") or {})
        hints["model"] = details
        task["runtime_profile_hints"] = hints
        return True
    return False


def _detail_list(details: dict, *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = details.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value if item)
        elif value:
            values.append(str(value))
    return values


def _merge_list_field(task: dict, field: str, values: list[str]) -> bool:
    if not values:
        return False
    existing = [str(item) for item in task.get(field, []) if item]
    merged = list(dict.fromkeys([*existing, *values]))
    if merged == existing:
        return False
    task[field] = merged
    return True
