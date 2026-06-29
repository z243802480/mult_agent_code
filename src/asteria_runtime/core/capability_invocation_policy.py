from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityInvocationPolicy:
    """Describe what runtime capabilities a runtime surface may ask to invoke."""

    _TOOL_KINDS = {
        "read_file": "read",
        "list_files": "read",
        "search": "read",
        "search_text": "read",
        "write_file": "write",
        "apply_patch": "write",
        "restore_backup": "write",
        "run_command": "execute",
        "shell": "execute",
        "run_tests": "verify",
        "review_agent": "verify",
        "merge_gate": "verify",
    }
    _ARTIFACT_SKILLS = {
        "document": "documents",
        "presentation": "presentations",
        "spreadsheet": "spreadsheets",
    }

    def for_intent(self, intent: str, *, permission_mode: str = "reviewed_auto") -> dict[str, Any]:
        if intent == "ordinary_chat":
            return self._profile(
                intent,
                task_kind="chat",
                risk="low",
                permission_mode=permission_mode,
                allow_tools=False,
                allow_mcp=False,
                allow_skills=False,
                groups=[],
                tool_permissions={},
                skill_permissions={},
                mcp_permission="deny",
                reason="lightweight Ask context should not attach long-task capabilities by default",
            )
        if intent == "debug_question":
            return self._profile(
                intent,
                task_kind="debug",
                risk="low",
                permission_mode=permission_mode,
                allow_tools=False,
                allow_mcp=False,
                allow_skills=False,
                groups=["runtime_inspection", "debug_context"],
                tool_permissions={},
                skill_permissions={},
                mcp_permission="deny",
                reason="debug answers may inspect mounted runtime evidence but do not execute tools",
            )
        if intent in {"progress_question", "status_question", "plan_question", "next_step_question"}:
            return self._profile(
                intent,
                task_kind="status",
                risk="low",
                permission_mode=permission_mode,
                allow_tools=False,
                allow_mcp=False,
                allow_skills=False,
                groups=["runtime_status", "goal_memory", "workspace_state"],
                tool_permissions={},
                skill_permissions={},
                mcp_permission="deny",
                reason="status and planning answers may consume durable runtime context",
            )
        return self._profile(
            intent,
            task_kind="unknown",
            risk="medium",
            permission_mode=permission_mode,
            allow_tools=False,
            allow_mcp=False,
            allow_skills=False,
            groups=["runtime_context"],
            tool_permissions={},
            skill_permissions={},
            mcp_permission="deny",
            reason="unknown chat intent receives context only until explicitly promoted",
        )

    def for_goal(
        self,
        intent: str,
        *,
        permission_mode: str = "reviewed_auto",
        risk: str = "medium",
    ) -> dict[str, Any]:
        task_kind = self._goal_task_kind(intent)
        return self.for_task(
            task_kind=task_kind,
            intent=intent,
            permission_mode=permission_mode,
            risk=risk,
        )

    def for_plan(
        self,
        *,
        intent: str = "implementation_goal",
        task_kind: str = "planning",
        permission_mode: str = "reviewed_auto",
        risk: str = "medium",
    ) -> dict[str, Any]:
        profile = self.for_task(
            intent=intent,
            task_kind=task_kind,
            permission_mode=permission_mode,
            risk=risk,
        )
        profile["allowed_capability_groups"] = list(
            dict.fromkeys([*profile["allowed_capability_groups"], "planner"])
        )
        profile["reason"] = "planning may inspect context and draft tasks, but execution is gated later"
        return profile

    def for_task(
        self,
        *,
        task_kind: str,
        intent: str = "implementation_goal",
        permission_mode: str = "reviewed_auto",
        risk: str = "medium",
    ) -> dict[str, Any]:
        normalized_kind = self._normalize(task_kind)
        normalized_intent = self._normalize(intent)
        normalized_risk = self._risk(risk)
        if normalized_intent in {"ordinary_chat", "chat"}:
            return self.for_intent("ordinary_chat", permission_mode=permission_mode)
        if normalized_intent in {"brainstorm", "brainstorm_goal"} or normalized_kind == "brainstorm":
            return self._profile(
                normalized_intent,
                task_kind=normalized_kind,
                risk=normalized_risk,
                permission_mode=permission_mode,
                allow_tools=True,
                allow_mcp=False,
                allow_skills=False,
                groups=["runtime_context", "read_only_tools"],
                tool_permissions=self._tool_permissions(permission_mode, normalized_risk, read_only=True),
                skill_permissions={},
                mcp_permission="deny",
                reason="brainstorming may inspect local context but should not write or call external services",
            )
        if normalized_intent in {"research", "research_goal"} or normalized_kind == "research":
            return self._profile(
                normalized_intent,
                task_kind=normalized_kind,
                risk=normalized_risk,
                permission_mode=permission_mode,
                allow_tools=True,
                allow_mcp=True,
                allow_skills=False,
                groups=["runtime_context", "read_only_tools", "mcp_research"],
                tool_permissions=self._tool_permissions(permission_mode, normalized_risk, read_only=True),
                skill_permissions={},
                mcp_permission=self._mcp_permission(permission_mode, normalized_risk),
                reason="research may read local context and request external MCP sources through policy",
            )
        artifact_skill = self._ARTIFACT_SKILLS.get(normalized_kind)
        skill_perm = self._skill_permission(permission_mode, normalized_risk)
        # Skills are loadable procedure/instruction capabilities, gated by the task's allowed_skills
        # contract + permission mode (mirroring MCP) — not restricted to the artifact-skill map.
        # Loading a skill returns its SKILL.md procedure; the model then acts through already-gated
        # tools, so skill loading itself is low-risk.
        skill_permissions = {artifact_skill: skill_perm} if artifact_skill else {}
        return self._profile(
            normalized_intent,
            task_kind=normalized_kind,
            risk=normalized_risk,
            permission_mode=permission_mode,
            allow_tools=True,
            allow_mcp=normalized_risk != "low",
            allow_skills=True,
            groups=[
                "runtime_context",
                "direct_tools",
                "verification",
                "skill",
                *(["artifact_skill"] if skill_permissions else []),
            ],
            tool_permissions=self._tool_permissions(permission_mode, normalized_risk),
            skill_permissions=skill_permissions,
            skill_permission=skill_perm,
            mcp_permission=self._mcp_permission(permission_mode, normalized_risk),
            reason="goal execution may use controlled tools; writes, shell, MCP, and skills follow risk and permission mode",
        )

    def for_capability(
        self,
        capability_name: str,
        *,
        task_kind: str,
        intent: str = "implementation_goal",
        permission_mode: str = "reviewed_auto",
        risk: str = "medium",
        capability_type: str = "tool",
    ) -> dict[str, Any]:
        profile = self.for_task(
            intent=intent,
            task_kind=task_kind,
            permission_mode=permission_mode,
            risk=risk,
        )
        capability = self._normalize(capability_type)
        name = self._normalize(capability_name)
        if capability == "mcp":
            decision = profile["mcp_permission"] if profile["allow_mcp"] else "deny"
            return self._decision(name, capability, decision, profile)
        if capability == "skill":
            if not profile["allow_skills"]:
                return self._decision(name, capability, "deny", profile)
            # The task's allowed_skills contract gates WHICH skills; this policy gates the
            # mode/risk permission. A name-specific artifact-skill permission still wins if present.
            decision = profile["skill_permissions"].get(name) or profile.get("skill_permission", "deny")
            return self._decision(name, capability, decision, profile)
        kind = self._TOOL_KINDS.get(name, "unknown")
        decision = profile["tool_permissions"].get(kind, "deny") if profile["allow_tools"] else "deny"
        return self._decision(name, capability, decision, profile, tool_kind=kind)

    def for_tool(
        self,
        tool_name: str,
        *,
        task_kind: str,
        intent: str = "implementation_goal",
        permission_mode: str = "reviewed_auto",
        risk: str = "medium",
        capability_type: str = "tool",
    ) -> dict[str, Any]:
        return self.for_capability(
            tool_name,
            intent=intent,
            task_kind=task_kind,
            permission_mode=permission_mode,
            risk=risk,
            capability_type=capability_type,
        )

    def _profile(
        self,
        intent: str,
        *,
        task_kind: str,
        risk: str,
        permission_mode: str,
        allow_tools: bool,
        allow_mcp: bool,
        allow_skills: bool,
        groups: list[str],
        tool_permissions: dict[str, str],
        skill_permissions: dict[str, str],
        mcp_permission: str,
        reason: str,
        skill_permission: str = "deny",
    ) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "intent": intent,
            "task_kind": task_kind,
            "risk": risk,
            "permission_mode": permission_mode,
            "allow_tools": allow_tools,
            "allow_mcp": allow_mcp,
            "allow_skills": allow_skills,
            "allowed_capability_groups": groups,
            "tool_permissions": tool_permissions,
            "mcp_permission": mcp_permission,
            "skill_permissions": skill_permissions,
            "skill_permission": skill_permission,
            "decision_required_when": [
                "permission is ask",
                "requested capability is denied",
                "risk is high and capability writes, executes, delegates, or calls external services",
            ],
            "reason": reason,
        }

    def _tool_permissions(
        self,
        permission_mode: str,
        risk: str,
        *,
        read_only: bool = False,
    ) -> dict[str, str]:
        if permission_mode == "ask_everything":
            base = {"read": "ask", "write": "ask", "execute": "ask", "verify": "ask"}
        elif permission_mode == "auto":
            base = {"read": "allow", "write": "allow", "execute": "ask", "verify": "allow"}
        else:
            base = {"read": "allow", "write": "ask", "execute": "ask", "verify": "allow"}
        if read_only:
            base = {**base, "write": "deny", "execute": "ask"}
        if risk == "high":
            base = {**base, "write": "ask", "execute": "ask"}
        return base

    def _mcp_permission(self, permission_mode: str, risk: str) -> str:
        if permission_mode == "ask_everything" or risk in {"medium", "high"}:
            return "ask"
        return "allow" if permission_mode == "auto" else "ask"

    def _skill_permission(self, permission_mode: str, risk: str) -> str:
        if permission_mode == "ask_everything" or risk == "high":
            return "ask"
        return "allow"

    def _goal_task_kind(self, intent: str) -> str:
        normalized = self._normalize(intent)
        if normalized in {"research", "research_goal"}:
            return "research"
        if normalized in {"brainstorm", "brainstorm_goal"}:
            return "brainstorm"
        for artifact_kind in self._ARTIFACT_SKILLS:
            if artifact_kind in normalized:
                return artifact_kind
        return "implementation"

    def _decision(
        self,
        name: str,
        capability_type: str,
        decision: str,
        profile: dict[str, Any],
        *,
        tool_kind: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "0.1.0",
            "capability": name,
            "capability_type": capability_type,
            "tool_kind": tool_kind,
            "decision": decision,
            "allowed": decision in {"allow", "ask"},
            "requires_decision": decision == "ask",
            "intent": profile["intent"],
            "task_kind": profile["task_kind"],
            "risk": profile["risk"],
            "permission_mode": profile["permission_mode"],
            "reason": self._decision_reason(decision, profile),
        }

    def _decision_reason(self, decision: str, profile: dict[str, Any]) -> str:
        if decision == "allow":
            return "capability is allowed by intent, task kind, risk, and permission mode"
        if decision == "ask":
            return "capability is available but requires an explicit runtime decision"
        return f"capability is denied by policy for {profile['intent']}/{profile['task_kind']}"

    def _risk(self, value: str) -> str:
        normalized = self._normalize(value)
        if normalized in {"low", "medium", "high"}:
            return normalized
        return "medium"

    def _normalize(self, value: str) -> str:
        return value.strip().lower().replace("-", "_")
