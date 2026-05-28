from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asteria_runtime.core.capability_invocation_policy import CapabilityInvocationPolicy
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.user_progress_logger import UserProgressLogger
from asteria_runtime.utils.time import now_iso


@dataclass(frozen=True)
class CapabilityRequest:
    name: str
    capability_type: str
    contract_field: str
    invocation_id_field: str


TOOL_REQUEST = CapabilityRequest("tool", "tool", "allowed_tools", "tool_call_id")
MCP_REQUEST = CapabilityRequest("mcp", "mcp", "allowed_mcp", "mcp_invocation_id")
SKILL_REQUEST = CapabilityRequest("skill", "skill", "allowed_skills", "skill_invocation_id")


@dataclass(frozen=True)
class CapabilityDecisionRecorder:
    """Shared audit sink; Tool, MCP, and Skill keep separate execution adapters."""

    actor: str = "CapabilityDecisionRecorder"

    def decide(
        self,
        capability_name: str,
        *,
        request: CapabilityRequest,
        task: dict[str, Any],
        context: RuntimeContext,
    ) -> dict[str, Any]:
        profile = task.get("agent_loop_profile")
        intent = "implementation_goal"
        if isinstance(profile, dict) and profile.get("loop_profile_id") == "research":
            intent = "research_goal"
        elif isinstance(profile, dict) and profile.get("loop_profile_id") == "brainstorm":
            intent = "brainstorm_goal"
        permission_mode = str(context.policy.get("permission_mode") or "reviewed_auto")
        risk = str(task.get("risk") or ("medium" if task.get("write_scope") else "low"))
        decision = CapabilityInvocationPolicy().for_capability(
            capability_name,
            intent=intent,
            task_kind=str(task.get("task_kind") or "implementation"),
            permission_mode=permission_mode,
            risk=risk,
            capability_type=request.capability_type,
        )
        if not self._allowed_by_task_contract(capability_name, request, task):
            return {
                **decision,
                "decision": "deny",
                "allowed": False,
                "requires_decision": False,
                "reason": (
                    "capability is denied because the task capability contract "
                    f"does not include {request.capability_type}:{capability_name}"
                ),
            }
        return decision

    def record(
        self,
        *,
        context: RuntimeContext,
        task: dict[str, Any],
        capability_name: str,
        request: CapabilityRequest,
        invocation_id: str,
        decision: dict[str, Any],
    ) -> dict[str, Any] | None:
        if context.run_dir is None:
            return None
        path = context.run_dir / "capability_decisions.jsonl"
        payload = {
            "schema_version": "0.1.0",
            "decision_id": f"capability-{invocation_id}",
            "run_id": context.run_id,
            "task_id": str(task.get("task_id", "")),
            "invocation_id": invocation_id,
            request.invocation_id_field: invocation_id,
            "tool_call_id": invocation_id if request.capability_type == "tool" else None,
            "capability": capability_name,
            "capability_type": request.capability_type,
            "decision": decision,
            "created_at": now_iso(),
        }
        JsonlStore(context.validator).append(path, payload, schema_name=None)
        logger = UserProgressLogger(path.with_name("user_progress.jsonl"), context.validator)
        event = logger.record(
            run_id=context.run_id,
            channel="permission",
            event_type="permission_decision",
            phase="execute",
            status="running" if decision["decision"] != "deny" else "blocked",
            title="Capability decision recorded",
            summary=(
                f"{request.capability_type}:{capability_name}: {decision['decision']} "
                f"for {decision['intent']}/{decision['task_kind']}."
            ),
            data={"permission": decision, "capability_decision": decision},
            evidence_refs=[str(path)],
            call_chain=[self.actor, request.capability_type],
            execution_chain=[str(task.get("task_id", "")), request.capability_type, capability_name],
        )
        return event

    def decide_and_record(
        self,
        capability_name: str,
        *,
        request: CapabilityRequest,
        task: dict[str, Any],
        context: RuntimeContext,
        invocation_id: str,
    ) -> dict[str, Any]:
        decision = self.decide(
            capability_name,
            request=request,
            task=task,
            context=context,
        )
        self.record(
            context=context,
            task=task,
            capability_name=capability_name,
            request=request,
            invocation_id=invocation_id,
            decision=decision,
        )
        return decision

    def decide_tool(
        self,
        tool_name: str,
        *,
        task: dict[str, Any],
        context: RuntimeContext,
        tool_call_id: str,
    ) -> dict[str, Any]:
        return self.decide_and_record(
            tool_name,
            request=TOOL_REQUEST,
            task=task,
            context=context,
            invocation_id=tool_call_id,
        )

    def decide_mcp(
        self,
        server_or_tool_name: str,
        *,
        task: dict[str, Any],
        context: RuntimeContext,
        mcp_invocation_id: str,
    ) -> dict[str, Any]:
        return self.decide_and_record(
            server_or_tool_name,
            request=MCP_REQUEST,
            task=task,
            context=context,
            invocation_id=mcp_invocation_id,
        )

    def decide_skill(
        self,
        skill_name: str,
        *,
        task: dict[str, Any],
        context: RuntimeContext,
        skill_invocation_id: str,
    ) -> dict[str, Any]:
        return self.decide_and_record(
            skill_name,
            request=SKILL_REQUEST,
            task=task,
            context=context,
            invocation_id=skill_invocation_id,
        )

    def _allowed_by_task_contract(
        self,
        capability_name: str,
        request: CapabilityRequest,
        task: dict[str, Any],
    ) -> bool:
        if request.capability_type == "tool":
            return capability_name in set(task.get(request.contract_field) or [])
        if request.capability_type == "mcp":
            allowed = set(task.get(request.contract_field) or task.get("allowed_mcp_tools") or [])
            server_name = capability_name.split("/", 1)[0]
            return not allowed or capability_name in allowed or server_name in allowed
        if request.capability_type == "skill":
            allowed = set(task.get(request.contract_field) or [])
            return not allowed or capability_name in allowed
        return False
