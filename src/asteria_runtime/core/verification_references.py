"""Exact, run/task-bound references to registered methods and executed observations.

References select persisted data, never authorize it or parse/repair shell text.
"""
from __future__ import annotations

import hashlib
import json

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.task_verification import VERIFICATION_TOOLS, declared_commands
from asteria_runtime.core.verification_evidence import VerificationEvidenceError, available_executions
from asteria_runtime.storage.json_store import JsonStore


def verification_methods(task: dict, context: RuntimeContext | None) -> list[dict]:
    policy = task.get("verification_policy") or {}
    commands = declared_commands(task)
    if (context is None or not context.run_id or context.run_dir is None
            or not task.get("task_id") or commands != policy.get("commands")):
        return []
    provenance = policy.get("method_provenance") or {}
    methods = []
    for command in dict.fromkeys(commands):
        binding = {"version": 1, "run_id": context.run_id, "run_namespace": str(context.run_dir.resolve()),
                   "task_id": task["task_id"],
                   "command": command, "provenance": provenance}
        digest = hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf8")).hexdigest()
        methods.append({"verification_ref": f"verification-{digest}", "command": command,
                        "revision_eligibility": "planner_candidate_recheck_required"
                        if command in provenance.get("revisable_commands", []) else "protected_or_unproven"})
    return methods


def execution_method_receipt(task: dict, context: RuntimeContext, tool_name: str, data: dict) -> dict:
    """Associate an executed command with the task snapshot, never grant revision.

    An exact command entry and a reference entry identify the same recorded method.
    Membership/eligibility still require fresh authority checks at revision time;
    neither they nor the exit status establish requirement coverage.
    """
    if tool_name not in VERIFICATION_TOOLS or type(data.get("returncode")) is not int:
        return {}
    command = data.get("requested_command") or data.get("command")
    if not isinstance(command, str) or not command.strip():
        return {}
    receipt = {"method_relation": "unregistered_or_unknown", "requirement_coverage": "unassessed"}
    match = next((m for m in verification_methods(task, context) if m["command"] == command.strip()), None)
    if match is not None:
        receipt.update({"method_relation": "current_declared_task_method",
                        "verification_ref": match["verification_ref"],
                        "revision_eligibility": match["revision_eligibility"]})
    return receipt


def current_reference_task(context: RuntimeContext, task_id: str | None = None) -> dict:
    expected = task_id or context.task_id
    if (not context.run_id or context.run_dir is None or not expected
            or context.task_id is not None and context.task_id != expected):
        raise PermissionError("Verification references require a runtime-bound current task")
    store = JsonStore(context.validator)
    run = store.read(context.run_dir / "run.json", "run")
    if run["run_id"] != context.run_id or run["status"] != "running":
        raise PermissionError("Verification references require the matching running session")
    board = store.read(context.run_dir / "task_plan.json", "task_board")
    matches = [t for t in board["tasks"] if t["task_id"] == expected]
    if len(matches) != 1 or matches[0]["status"] != "in_progress":
        raise PermissionError("Verification reference task is missing, ambiguous or no longer active")
    return matches[0]


def referenced_command(task: dict, context: RuntimeContext, reference: str) -> str:
    matches = [m for m in verification_methods(task, context) if m["verification_ref"] == reference]
    if not isinstance(reference, str) or len(matches) != 1:
        raise PermissionError("Unknown or stale verification reference for the current run/task/method")
    return matches[0]["command"]


def resolve_verification_args(context: RuntimeContext, task: dict, tool_name: str, args: dict) -> dict:
    if "verification_ref" not in args:
        return args
    if tool_name != "run_tests" or set(args) - {"verification_ref", "timeout_seconds"}:
        raise PermissionError("Use run_tests with either verification_ref or command, never both")
    current = current_reference_task(context, task.get("task_id"))
    if tool_name not in current.get("allowed_tools", []):
        raise PermissionError("The current task does not allow the referenced execution tool")
    if verification_methods(current, context) != verification_methods(task, context):
        raise PermissionError("The in-memory verification contract is stale")
    command = referenced_command(current, context, args["verification_ref"])
    return {"command": command, **({"timeout_seconds": args["timeout_seconds"]} if "timeout_seconds" in args else {})}


def referenced_observation(records: list[dict], call_id: str, context: RuntimeContext, task: dict) -> dict:
    matches = [row for row in records if row["tool_call_id"] == call_id]
    if not isinstance(call_id, str) or len(matches) != 1:
        raise VerificationEvidenceError("Execution reference is missing or ambiguous", {
            "reason_code": "execution_reference_unresolved",
            "resolution": "missing" if not matches else "ambiguous",
            "available_executions": available_executions(records, context.run_id, task["task_id"]),
        })
    row = matches[0]
    observation = row["observation"]
    if (row["run_id"] != context.run_id or row["task_id"] != task["task_id"]
            or row["tool_name"] not in VERIFICATION_TOOLS
            or row["tool_name"] != observation.get("tool_name")
            or row["ok"] != observation.get("ok") or row["status"] != observation.get("status")):
        raise PermissionError("Execution reference must be a current-task verification observation")
    return row
