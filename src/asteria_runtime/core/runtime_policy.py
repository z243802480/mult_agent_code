from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.permission_policy import permission_policy_profile
from asteria_runtime.core.permission_preview import permission_preview_for_runtime_requests
from asteria_runtime.core.runtime_request import (
    RuntimeRequest,
    apply_runtime_request_to_task,
    effective_runtime_request_risk,
)
from asteria_runtime.core.task_board import TaskBoard
from asteria_runtime.core.task_contract import parallel_safety, path_in_read_scope, path_in_write_scope, read_scope, task_kind, write_scope
from asteria_runtime.core.task_execution_evidence import TaskExecutionEvidenceRecorder
from asteria_runtime.security.shell_guard import ShellGuard, ShellPolicyError
from asteria_runtime.storage.json_store import JsonStore
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator
from asteria_runtime.tools.patch_tools import PatchApplyError, parse_unified_diff
from asteria_runtime.utils.time import now_iso


class ToolPermissionDenied(PermissionError):
    def __init__(
        self,
        message: str,
        *,
        request_type: str,
        details: dict,
        risk: str = "medium",
    ) -> None:
        super().__init__(message)
        self.request_type = request_type
        self.details = details
        self.risk = risk


@dataclass(frozen=True)
class RuntimeRequestPolicyResult:
    task_id: str
    status: str
    summary: str
    evidence_path: Path | None
    permission_preview: dict


@dataclass(frozen=True)
class ToolPermissionPolicy:
    root: Path
    validator: SchemaValidator

    def permission_profile(self, context: RuntimeContext) -> dict:
        profile = context.policy.get("permission_policy")
        if isinstance(profile, dict) and profile:
            return profile
        mode = context.policy.get("permission_mode") or "reviewed_auto"
        return permission_policy_profile(str(mode))

    def enforce_tool_permission_profile(self, task: dict, tool_name: str, args: dict) -> None:
        write_tools = {"write_file", "apply_patch", "restore_backup"}
        if tool_name not in write_tools:
            self._enforce_read_scope(task, tool_name, args)
            return
        if parallel_safety(task) == "readonly":
            raise PermissionError(
                f"ToolPermissionProfile denied write tool for readonly task {task['task_id']}: "
                f"{tool_name}"
            )
        if not write_scope(task):
            requested_paths = self._write_paths_for_tool(tool_name, args)
            raise ToolPermissionDenied(
                f"ToolPermissionProfile requires write_scope for {task['task_id']}: {tool_name}",
                request_type="scope_expansion",
                details={"write_scope": requested_paths},
            )
        if not isinstance(task.get("write_scope"), list):
            return
        for path in self._write_paths_for_tool(tool_name, args):
            if not path_in_write_scope(path, write_scope(task), kind=task_kind(task)):
                raise ToolPermissionDenied(
                    f"ToolPermissionProfile denied write path for {task['task_id']}: {path}",
                    request_type="scope_expansion",
                    details={"write_scope": [path]},
                )

    def create_policy_decision_if_needed(
        self,
        *,
        action: dict,
        task: dict,
        context: RuntimeContext,
    ) -> dict | None:
        for call in [*action.get("tool_calls", []), *action.get("verification", [])]:
            tool_name = call["tool_name"]
            if tool_name not in {"run_command", "run_tests"}:
                continue
            command = str(call.get("args", {}).get("command") or "")
            if not command:
                continue
            denial = self.shell_denial(context.policy, command)
            if denial is None or self.has_execution_approval(
                context, task, tool_name, call["args"]
            ):
                continue
            return self._create_execution_decision(context, task, tool_name, call["args"], denial)
        return None

    def context_with_approval(
        self,
        context: RuntimeContext,
        task: dict,
        tool_name: str,
        args: dict,
    ) -> RuntimeContext:
        if tool_name not in {"run_command", "run_tests"}:
            return context
        if not self.has_execution_approval(context, task, tool_name, args):
            return context
        policy = deepcopy(context.policy)
        permissions = policy.setdefault("permissions", {})
        permissions["allow_shell"] = True
        permissions["allow_shell_operators"] = True
        permissions["allow_destructive_shell"] = True
        permissions["allow_remote_push"] = True
        permissions["allow_deploy"] = True
        permissions["allow_global_package_install"] = True
        return RuntimeContext(
            root=context.root,
            run_id=context.run_id,
            policy=policy,
            validator=context.validator,
            event_logger=context.event_logger,
            budget=context.budget,
            agent_dir_override=context.asteria_dir,
            run_dir_override=context.run_dir,
        )

    def shell_denial(self, policy: dict, command: str) -> str | None:
        try:
            ShellGuard(policy["permissions"]).validate(command)
        except ShellPolicyError as exc:
            return str(exc)
        return None

    def has_execution_approval(
        self,
        context: RuntimeContext,
        task: dict,
        tool_name: str,
        args: dict,
    ) -> bool:
        if context.run_dir is None:
            return False
        for decision in self._matching_decisions(context.run_dir, task, tool_name, args):
            if decision["status"] in {"resolved", "defaulted"}:
                return decision.get("selected_option_id") == "approve_once"
        return False

    def args_fingerprint(self, args: dict) -> str:
        return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _enforce_read_scope(self, task: dict, tool_name: str, args: dict) -> None:
        path = None
        if tool_name in {"read_file", "list_files", "search_text", "find_files", "diff_workspace"}:
            path = str(args.get("path") or ".")
        if path is None:
            return
        if not isinstance(task.get("read_scope"), list):
            return
        scope = read_scope(task)
        if scope and not path_in_read_scope(path, scope, kind=task_kind(task)):
            raise ToolPermissionDenied(
                f"ToolPermissionProfile denied read path for {task['task_id']}: {path}",
                request_type="context_request",
                details={"read_scope": [path], "context_requirements": {"requested_paths": [path]}},
            )

    def _write_paths_for_tool(self, tool_name: str, args: dict) -> list[str]:
        if tool_name == "write_file" and args.get("path"):
            return [str(args["path"])]
        if tool_name == "apply_patch":
            patch_text = args.get("patch") if args.get("patch") is not None else args.get("diff")
            if not isinstance(patch_text, str):
                return []
            try:
                return [file_patch.path for file_patch in parse_unified_diff(patch_text)]
            except PatchApplyError:
                return []
        return []

    def _path_in_scope(self, path: str, scope: list[str]) -> bool:
        normalized = self._normalize_scope_path(path)
        for item in scope:
            allowed = self._normalize_scope_path(str(item))
            if allowed in {"", "."}:
                return True
            if allowed.endswith("/"):
                if normalized.startswith(allowed):
                    return True
            elif normalized == allowed:
                return True
        return False

    def _normalize_scope_path(self, path: str) -> str:
        normalized = path.replace("\\", "/").strip()
        if normalized.startswith("./"):
            normalized = normalized[2:]
        if normalized and not normalized.endswith("/") and "." not in normalized.rsplit("/", 1)[-1]:
            normalized += "/"
        return normalized

    def _create_execution_decision(
        self,
        context: RuntimeContext,
        task: dict,
        tool_name: str,
        args: dict,
        denial: str,
    ) -> dict:
        if context.run_id is None or context.run_dir is None:
            raise RuntimeError("Cannot create execution decision without a run directory.")
        existing = self._matching_decisions(context.run_dir, task, tool_name, args)
        for decision in existing:
            if decision["status"] == "pending":
                return decision
        decisions_path = context.run_dir / "decisions.jsonl"
        decision_id = self._next_jsonl_id(decisions_path, "decision")
        decision = {
            "schema_version": "0.1.0",
            "decision_id": decision_id,
            "status": "pending",
            "question": (
                f"Approve one-time execution for task {task['task_id']}? "
                f"Policy blocked `{tool_name}` because: {denial}"
            ),
            "recommended_option_id": "skip",
            "options": [
                {
                    "option_id": "approve_once",
                    "label": "Approve once",
                    "tradeoff": "Allow this exact command once for this task; keeps global policy unchanged.",
                    "action": "record_constraint",
                },
                {
                    "option_id": "approve_similar_for_session",
                    "label": "Approve similar for this session",
                    "tradeoff": "Allow commands with the same intent and prefix during this session; global policy stays unchanged.",
                    "action": "record_constraint",
                },
                {
                    "option_id": "skip",
                    "label": "Keep blocked",
                    "tradeoff": "Do not run the command; the task remains blocked until replanned or changed.",
                    "action": "record_constraint",
                },
            ],
            "default_option_id": "skip",
            "impact": {"scope": "medium", "budget": "low", "risk": "high", "quality": "medium"},
            "selected_option_id": None,
            "created_at": now_iso(),
            "metadata": {
                "kind": "execution_policy_approval",
                "task_id": task["task_id"],
                "tool_name": tool_name,
                "args_fingerprint": self.args_fingerprint(args),
                "denial": denial,
                "permission_mode": self.permission_profile(context).get("mode"),
                "ask_options": self.permission_profile(context).get("ask_options", []),
            },
            "resolved_at": None,
        }
        self.validator.validate("decision_point", decision)
        JsonlStore(self.validator).append(decisions_path, decision, "decision_point")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "decision_created",
                "ToolPermissionPolicy",
                str(decision["question"]),
                {"decision_id": decision_id},
            )
        return decision

    def _matching_decisions(
        self,
        run_dir: Path,
        task: dict,
        tool_name: str,
        args: dict,
    ) -> list[dict]:
        path = run_dir / "decisions.jsonl"
        if not path.exists():
            return []
        fingerprint = self.args_fingerprint(args)
        matches = []
        for decision in JsonlStore(self.validator).read_all(path, "decision_point"):
            metadata = decision.get("metadata") or {}
            if (
                metadata.get("kind") == "execution_policy_approval"
                and metadata.get("task_id") == task["task_id"]
                and metadata.get("tool_name") == tool_name
                and metadata.get("args_fingerprint") == fingerprint
            ):
                matches.append(decision)
        return matches

    def _jsonl_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    def _next_jsonl_id(self, path: Path, prefix: str) -> str:
        return f"{prefix}-{self._jsonl_count(path) + 1:04d}"


@dataclass(frozen=True)
class RuntimeRequestPolicy:
    validator: SchemaValidator
    evidence_recorder: TaskExecutionEvidenceRecorder
    record_task_failure: Callable[..., None]

    def handle_runtime_requests(
        self,
        *,
        action: dict,
        task: dict,
        task_board: TaskBoard,
        context: RuntimeContext,
    ) -> RuntimeRequestPolicyResult | None:
        requests = action.get("runtime_requests") or []
        if not requests:
            return None
        recorded = [
            self._record_runtime_request(context, task, request)
            for request in requests
            if isinstance(request, dict)
        ]
        if not recorded:
            return None
        auto_allow = ToolPermissionPolicy(context.root, self.validator).permission_profile(context).get(
            "auto_allow_low_risk",
            False,
        )
        for request in recorded:
            request["risk"] = effective_runtime_request_risk(request, auto_allow_low_risk=auto_allow)
        if auto_allow and all(request["risk"] == "low" for request in recorded):
            if self._auto_apply_runtime_requests(context, task, recorded):
                return None
        needs_decision = [request for request in recorded if request["risk"] in {"medium", "high"}]
        decision = (
            self._create_runtime_request_decision(context, task, needs_decision)
            if needs_decision
            else None
        )
        final_requests = []
        for request in recorded:
            if decision and request["runtime_request_id"] in decision["metadata"].get(
                "runtime_request_ids", []
            ):
                request = dict(request)
                request["status"] = "decision_created"
                request["decision_id"] = decision["decision_id"]
                self._rewrite_runtime_request(context, request)
            final_requests.append(request)

        reason = self._runtime_request_block_reason(final_requests, decision)
        task_board.update_status(task["task_id"], "blocked")
        task_board.update_notes(task["task_id"], reason)
        self.record_task_failure(
            context,
            task,
            "runtime_request",
            reason,
            candidate={
                "runtime_request_ids": [
                    request["runtime_request_id"] for request in final_requests
                ],
                "decision_id": decision["decision_id"] if decision else None,
            },
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "runtime_request_blocked_task",
                "RuntimeRequestPolicy",
                reason,
                {
                    "task_id": task["task_id"],
                    "runtime_request_ids": [
                        request["runtime_request_id"] for request in final_requests
                    ],
                    "decision_id": decision["decision_id"] if decision else None,
                },
            )
        evidence_path = self.evidence_recorder.record(
            context,
            task,
            action,
            [],
            [],
            "blocked",
            reason,
            actor="RuntimeRequestPolicy",
            candidate={
                "runtime_request_ids": [
                    request["runtime_request_id"] for request in final_requests
                ],
                "decision_id": decision["decision_id"] if decision else None,
            },
            failure_type="runtime_request",
        )
        return RuntimeRequestPolicyResult(
            task_id=task["task_id"],
            status="blocked",
            summary=reason,
            evidence_path=evidence_path,
            permission_preview=permission_preview_for_runtime_requests(final_requests),
        )

    def _auto_apply_runtime_requests(
        self,
        context: RuntimeContext,
        task: dict,
        requests: list[dict],
    ) -> bool:
        if context.run_dir is None:
            return False
        task_plan_path = context.run_dir / "task_plan.json"
        store = JsonStore(self.validator)
        task_plan = store.read(task_plan_path, "task_board")
        target = next(
            (item for item in task_plan["tasks"] if item["task_id"] == task["task_id"]),
            None,
        )
        if target is None:
            return False
        prior_status = target.get("status")
        changed = False
        for request in requests:
            changed |= apply_runtime_request_to_task(target, request)
            updated = dict(request)
            updated["status"] = "auto_applied"
            self._rewrite_runtime_request(context, updated)
        if not changed:
            return False
        ids = ", ".join(request["runtime_request_id"] for request in requests)
        target["notes"] = f"Auto-applied low-risk runtime request(s): {ids}."
        target["updated_at"] = now_iso()
        if prior_status == "blocked":
            target["status"] = "ready"
        self.validator.validate("task", target)
        store.write(task_plan_path, task_plan, "task_board")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "runtime_request_auto_applied",
                "RuntimeRequestPolicy",
                target["notes"],
                {
                    "task_id": task["task_id"],
                    "runtime_request_ids": [request["runtime_request_id"] for request in requests],
                },
            )
        return True

    def _record_runtime_request(
        self,
        context: RuntimeContext,
        task: dict,
        request: dict,
    ) -> dict:
        raw_details = request.get("details")
        details: dict = raw_details if isinstance(raw_details, dict) else {}
        runtime_request = RuntimeRequest(
            runtime_request_id=(
                self._next_jsonl_id(context.run_dir / "runtime_requests.jsonl", "runtime-request")
                if context.run_dir
                else "runtime-request-0001"
            ),
            run_id=context.run_id,
            task_id=task["task_id"],
            request_type=str(request["request_type"]),
            risk=str(request["risk"]),
            reason=str(request["reason"]),
            details=details,
            status="recorded",
            created_at=now_iso(),
        ).to_dict()
        self.validator.validate("runtime_request", runtime_request)
        if context.run_dir:
            JsonlStore(self.validator).append(
                context.run_dir / "runtime_requests.jsonl",
                runtime_request,
                "runtime_request",
            )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "runtime_request_recorded",
                "RuntimeRequestPolicy",
                f"{runtime_request['request_type']}: {runtime_request['reason']}",
                {
                    "task_id": task["task_id"],
                    "runtime_request_id": runtime_request["runtime_request_id"],
                    "request_type": runtime_request["request_type"],
                    "risk": runtime_request["risk"],
                },
            )
        return runtime_request

    def _rewrite_runtime_request(self, context: RuntimeContext, updated: dict) -> None:
        if context.run_dir is None:
            return
        path = context.run_dir / "runtime_requests.jsonl"
        store = JsonlStore(self.validator)
        requests = store.read_all(path, "runtime_request") if path.exists() else []
        rewritten = [
            updated if item["runtime_request_id"] == updated["runtime_request_id"] else item
            for item in requests
        ]
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rewritten),
            encoding="utf-8",
        )

    def _create_runtime_request_decision(
        self,
        context: RuntimeContext,
        task: dict,
        requests: list[dict],
    ) -> dict | None:
        if context.run_dir is None:
            return None
        decisions_path = context.run_dir / "decisions.jsonl"
        decision_id = self._next_jsonl_id(decisions_path, "decision")
        request_ids = [request["runtime_request_id"] for request in requests]
        decision = {
            "schema_version": "0.1.0",
            "decision_id": decision_id,
            "status": "pending",
            "question": self._runtime_request_question(task, requests),
            "recommended_option_id": "review_contract",
            "options": [
                {
                    "option_id": "review_contract",
                    "label": "Review contract",
                    "tradeoff": "Pause execution and revise scope, context, tools, budget, or model routing deliberately.",
                    "action": "require_replan",
                },
                {
                    "option_id": "reject_request",
                    "label": "Reject request",
                    "tradeoff": "Keep current task boundary and require the worker to find another valid path.",
                    "action": "record_constraint",
                },
            ],
            "default_option_id": "review_contract",
            "impact": self._runtime_request_impact(requests),
            "selected_option_id": None,
            "created_at": now_iso(),
            "metadata": {
                "kind": "runtime_request",
                "task_id": task["task_id"],
                "runtime_request_ids": request_ids,
                "request_types": sorted({request["request_type"] for request in requests}),
                "permission_preview": permission_preview_for_runtime_requests(requests),
            },
            "resolved_at": None,
        }
        self.validator.validate("decision_point", decision)
        JsonlStore(self.validator).append(decisions_path, decision, "decision_point")
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "decision_created",
                "RuntimeRequestPolicy",
                str(decision["question"]),
                {"decision_id": decision_id, "runtime_request_ids": request_ids},
            )
        return decision

    def _runtime_request_question(self, task: dict, requests: list[dict]) -> str:
        kinds = ", ".join(sorted({request["request_type"] for request in requests}))
        return f"Runtime request for {task['task_id']} requires contract review: {kinds}."

    def _runtime_request_impact(self, requests: list[dict]) -> dict:
        risk = "high" if any(request["risk"] == "high" for request in requests) else "medium"
        return {"scope": "medium", "budget": "medium", "risk": risk, "quality": "medium"}

    def _runtime_request_block_reason(self, requests: list[dict], decision: dict | None) -> str:
        ids = ", ".join(request["runtime_request_id"] for request in requests)
        if decision:
            return f"Runtime request requires decision {decision['decision_id']}: {ids}"
        return f"Runtime request recorded for contract review: {ids}"

    def _jsonl_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    def _next_jsonl_id(self, path: Path, prefix: str) -> str:
        return f"{prefix}-{self._jsonl_count(path) + 1:04d}"
