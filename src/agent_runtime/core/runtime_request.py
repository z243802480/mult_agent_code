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
