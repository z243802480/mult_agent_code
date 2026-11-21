"""Bounded ledger facts for rejected method revisions; never grant authority."""

from collections import Counter
import hashlib

from asteria_runtime.core.task_verification import VERIFICATION_TOOLS


class VerificationEvidenceError(PermissionError):
    def __init__(self, message: str, evidence: dict) -> None:
        super().__init__(message)
        self.evidence = {**evidence, "requirement_coverage": "unassessed"}


def execution_receipt(record: dict) -> dict:
    observation = record.get("observation") or {}
    data = observation.get("data") or {}
    command = str(data.get("requested_command") or data.get("command") or "").strip()
    return {
        "tool_call_id": record.get("tool_call_id"),
        "observation_id": record.get("observation_id"),
        "tool_name": observation.get("tool_name"),
        "ok": observation.get("ok"), "status": observation.get("status"),
        "returncode": data.get("returncode") if type(data.get("returncode")) is int else None,
        "dispatch_state": observation.get("dispatch_state", "unknown"),
        "command_sha256": hashlib.sha256(command.encode("utf8")).hexdigest() if command else None,
        "command_excerpt": command[:240], "command_truncated": len(command) > 240,
    }


def available_executions(records: list[dict], run_id: str | None, task_id: str) -> dict:
    counts = Counter(row.get("tool_call_id") for row in records)
    eligible = []
    for row in records:
        obs = row.get("observation") or {}
        if (run_id and row.get("run_id") == run_id and row.get("task_id") == task_id
                and isinstance(row.get("tool_call_id"), str) and counts[row["tool_call_id"]] == 1
                and row.get("tool_name") in VERIFICATION_TOOLS
                and all(row.get(key) == obs.get(key) for key in ("tool_name", "ok", "status"))
                and (obs.get("data") or {}).get("tool_call_id", row["tool_call_id"]) == row["tool_call_id"]):
            eligible.append(row)
    return {"source": "current_run_task_ledger", "total": len(eligible),
            "truncated": len(eligible) > 8,
            "observations": [execution_receipt(row) for row in eligible[-8:]]}
