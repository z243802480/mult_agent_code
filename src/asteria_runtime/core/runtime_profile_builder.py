from __future__ import annotations

from dataclasses import dataclass

from asteria_runtime.core.agent_role_policy import role_contract_for
from asteria_runtime.core.capability_feedback import CapabilityFeedbackAdvisor
from asteria_runtime.core.context_mount_builder import ContextMountBuilder
from asteria_runtime.core.context_package_builder import ContextPackageBuilder
from asteria_runtime.core.runtime_context import RuntimeContext
from asteria_runtime.core.runtime_profile import (
    AccountProfile,
    BudgetProfile,
    ModelProfile,
    RuntimeProfile,
    SandboxProfile,
    ToolPermissionProfile,
)
from asteria_runtime.core.sandbox_backend import SandboxBackendSelector
from asteria_runtime.core.task_contract import (
    context_requirements,
    failure_policy,
    parallel_safety,
    read_scope,
    task_kind,
    validation_commands,
    write_scope,
)
from asteria_runtime.models.route_resolver import resolve_model_route
from asteria_runtime.models.route_diagnostics import route_diagnostic_for_tier
from asteria_runtime.storage.jsonl_store import JsonlStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class RuntimeProfileMount:
    runtime_profile_id: str
    runtime_context: dict


@dataclass(frozen=True)
class RuntimeProfileBuilder:
    validator: SchemaValidator

    def build_and_record(
        self,
        *,
        context: RuntimeContext,
        task: dict,
        worker_id: str,
        runtime_context: dict,
        artifact_refs: list[str] | None = None,
        failure_evidence_refs: list[str] | None = None,
        decision_refs: list[str] | None = None,
        validation_refs: list[str] | None = None,
    ) -> RuntimeProfileMount:
        scoped = self._runtime_context_for_task(
            context=context,
            task=task,
            runtime_context=runtime_context,
            artifact_refs=artifact_refs or [],
            failure_evidence_refs=failure_evidence_refs or [],
            decision_refs=decision_refs or [],
            validation_refs=validation_refs or [],
        )
        if context.run_dir is None:
            return RuntimeProfileMount(
                runtime_profile_id=self._default_runtime_profile_id(task),
                runtime_context=scoped,
            )

        profile_base_id = f"profile-{worker_id}"
        model_purpose = self._model_purpose(task)
        role_contract = role_contract_for(
            role=str(task.get("assigned_agent_id") or task.get("role") or "CoderAgent"),
            purpose=model_purpose,
            policy=context.policy,
        )
        model_selection = self._model_selection(task, context, model_purpose)
        model_tier = model_selection["selected_tier"]
        resolved_route = resolve_model_route(model_tier)
        model_profile = ModelProfile(
            model_profile_id=f"model-{profile_base_id}",
            purpose=model_purpose,
            provider=resolved_route.provider,
            model_name=resolved_route.model_name or f"{model_tier}-route",
            model_tier=model_tier,
            limits={
                "role": role_contract.role,
                "deadline_profile": role_contract.deadline_profile,
                "provider_call_seconds": role_contract.provider_call_seconds,
                "stream_idle_timeout_seconds": role_contract.stream_idle_timeout_seconds,
            },
        )
        tool_profile = ToolPermissionProfile(
            tool_permission_profile_id=f"tools-{profile_base_id}",
            allowed_tools=[str(tool) for tool in task.get("allowed_tools", [])],
            read_scope=read_scope(task),
            write_scope=write_scope(task),
            allow_network=bool(context.policy.get("permissions", {}).get("allow_network", False)),
            allow_shell=bool(context.policy.get("permissions", {}).get("allow_shell", True)),
            allow_destructive_shell=bool(
                context.policy.get("permissions", {}).get("allow_destructive_shell", False)
            ),
        )
        account_profile = AccountProfile(
            account_profile_id=f"account-{profile_base_id}",
            provider="runtime",
            credential_ref="AGENT_MODEL_API_KEY",
            permission_tier="standard",
        )
        sandbox_plan = SandboxBackendSelector().select_for_task(context.root, task)
        sandbox_profile = SandboxProfile(
            sandbox_profile_id=f"sandbox-{profile_base_id}",
            backend=sandbox_plan.backend,
            workspace_policy=sandbox_plan.workspace_policy,
            cleanup_policy="keep_evidence",
            export_required=["artifact_index", "diff", "failure_evidence"],
            reason=sandbox_plan.reason,
        )
        context_mount = scoped.get("context_mount") or {}
        runtime_profile = RuntimeProfile(
            runtime_profile_id=f"runtime-{profile_base_id}",
            agent_id=str(task.get("assigned_agent_id") or task.get("role") or "CoderAgent"),
            model_profile_id=model_profile.model_profile_id,
            tool_permission_profile_id=tool_profile.tool_permission_profile_id,
            account_profile_id=account_profile.account_profile_id,
            sandbox_profile_id=sandbox_profile.sandbox_profile_id,
            context_mount_id=str(
                context_mount.get("context_mount_id") or f"context-{profile_base_id}"
            ),
            budget=BudgetProfile(
                max_model_calls=role_contract.max_model_calls,
                max_tool_calls=max(1, len(task.get("allowed_tools", []))),
                max_runtime_minutes=max(1, (role_contract.provider_call_seconds + 59) // 60),
            ),
        )
        scoped["runtime_profile_id"] = runtime_profile.runtime_profile_id
        scoped["model_profile_id"] = model_profile.model_profile_id
        scoped["tool_permission_profile_id"] = tool_profile.tool_permission_profile_id
        scoped["sandbox_profile_id"] = sandbox_profile.sandbox_profile_id
        scoped["account_profile_id"] = account_profile.account_profile_id
        scoped["model_selection"] = model_selection
        scoped["model_route_resolution"] = resolved_route.to_dict()
        scoped["agent_role_contract"] = role_contract.to_dict()
        if context.policy.get("model_strategy_profile"):
            scoped["model_strategy_profile"] = context.policy["model_strategy_profile"]

        self._record_profiles(
            context=context,
            task=task,
            worker_id=worker_id,
            model_profile=model_profile,
            tool_profile=tool_profile,
            account_profile=account_profile,
            sandbox_profile=sandbox_profile,
            runtime_profile=runtime_profile,
            context_mount=context_mount,
        )
        return RuntimeProfileMount(
            runtime_profile_id=runtime_profile.runtime_profile_id,
            runtime_context=scoped,
        )

    def _runtime_context_for_task(
        self,
        *,
        context: RuntimeContext,
        task: dict,
        runtime_context: dict,
        artifact_refs: list[str],
        failure_evidence_refs: list[str],
        decision_refs: list[str],
        validation_refs: list[str],
    ) -> dict:
        scoped = dict(runtime_context)
        if context.run_id:
            scoped["context_mount"] = (
                ContextMountBuilder(context.run_id)
                .build(
                    task,
                    artifact_refs=artifact_refs,
                    failure_evidence_refs=failure_evidence_refs,
                    decision_refs=decision_refs,
                    validation_refs=validation_refs,
                )
                .to_dict()
            )
            scoped["context_package"] = ContextPackageBuilder(self.validator).build(
                context,
                task,
                scoped["context_mount"],
            )
        scoped["task_contract"] = {
            "read_scope": read_scope(task),
            "write_scope": write_scope(task),
            "context_requirements": context_requirements(task),
            "validation_commands": validation_commands(task),
            "failure_policy": failure_policy(task),
            "parallel_safety": parallel_safety(task),
        }
        purpose = self._model_purpose(task)
        scoped["route_guidance"] = self._route_guidance_for_task(context, purpose)
        scoped["agent_role_contract"] = role_contract_for(
            role=str(task.get("assigned_agent_id") or task.get("role") or "CoderAgent"),
            purpose=purpose,
            policy=context.policy,
        ).to_dict()
        return scoped

    def _record_profiles(
        self,
        *,
        context: RuntimeContext,
        task: dict,
        worker_id: str,
        model_profile: ModelProfile,
        tool_profile: ToolPermissionProfile,
        account_profile: AccountProfile,
        sandbox_profile: SandboxProfile,
        runtime_profile: RuntimeProfile,
        context_mount: dict,
    ) -> None:
        if context.run_dir is None:
            return
        store = JsonlStore(self.validator)
        store.append(
            context.run_dir / "model_profiles.jsonl", model_profile.to_dict(), "model_profile"
        )
        store.append(
            context.run_dir / "tool_permission_profiles.jsonl",
            tool_profile.to_dict(),
            "tool_permission_profile",
        )
        store.append(
            context.run_dir / "account_profiles.jsonl",
            account_profile.to_dict(),
            "account_profile",
        )
        store.append(
            context.run_dir / "sandbox_profiles.jsonl",
            sandbox_profile.to_dict(),
            "sandbox_profile",
        )
        if context_mount:
            store.append(context.run_dir / "context_mounts.jsonl", context_mount, "context_mount")
        store.append(
            context.run_dir / "runtime_profiles.jsonl",
            runtime_profile.to_dict(),
            "runtime_profile",
        )
        if context.event_logger:
            context.event_logger.record(
                context.run_id,
                "runtime_profile_mounted",
                "RuntimeProfileBuilder",
                f"Mounted {runtime_profile.runtime_profile_id} for {task['task_id']}.",
                {
                    "task_id": task["task_id"],
                    "worker_invocation_id": worker_id,
                    "runtime_profile_id": runtime_profile.runtime_profile_id,
                    "model_profile_id": model_profile.model_profile_id,
                    "tool_permission_profile_id": tool_profile.tool_permission_profile_id,
                    "context_mount_id": runtime_profile.context_mount_id,
                },
            )

    def _model_selection(self, task: dict, context: RuntimeContext, purpose: str) -> dict:
        kind = task_kind(task)
        default = self._default_model_tier(task, kind)
        strategy_tier, strategy_reason = self._strategy_adjusted_tier(
            task,
            context,
            kind,
            default,
        )
        capability_adjustment = self._capability_adjustment(context, purpose, strategy_tier)
        selected = capability_adjustment["selected_tier"]
        reason = strategy_reason
        if selected != strategy_tier:
            reason = f"capability_feedback_escalated_from_{strategy_tier}"
        return {
            "purpose": purpose,
            "task_kind": kind,
            "role_contract": role_contract_for(
                role=str(task.get("assigned_agent_id") or task.get("role") or "CoderAgent"),
                purpose=purpose,
                policy=context.policy,
            ).to_dict(),
            "default_tier": default,
            "strategy_tier": strategy_tier,
            "selected_tier": selected,
            "strategy": str(
                (context.policy.get("model_strategy_profile") or {}).get("strategy") or "auto"
            ),
            "reason": reason,
            "tier_pressure": self._tier_pressure(default, strategy_tier, selected),
            "capability_feedback": capability_adjustment["feedback"],
        }

    def _default_model_tier(self, task: dict, kind: str) -> str:
        _ = task
        if kind in {"architecture", "review"}:
            return "strong"
        elif kind in {"report", "decision"}:
            return "cheap"
        elif (
            kind in {"research", "diagnostic", "verification"}
            and parallel_safety(task) == "readonly"
        ):
            return "cheap"
        return "medium"

    def _model_tier(self, task: dict, context: RuntimeContext, purpose: str) -> str:
        return self._model_selection(task, context, purpose)["selected_tier"]

    def _strategy_adjusted_tier(
        self,
        task: dict,
        context: RuntimeContext,
        kind: str,
        default: str,
    ) -> tuple[str, str]:
        explicit = self._explicit_model_tier(task)
        if explicit:
            return explicit, "explicit_task_model_tier"
        profile = context.policy.get("model_strategy_profile") or {}
        strategy = str(profile.get("strategy") or "auto")
        if strategy == "quality" and default == "medium" and self._needs_stronger_model(task, kind):
            return "strong", "quality_strategy_escalated_high_risk_or_complex_task"
        if strategy == "economy" and default == "medium" and self._is_low_risk_task(task, kind):
            return "cheap", "economy_strategy_downgraded_low_risk_task"
        if strategy == "local":
            return default, "local_strategy_waiting_for_configured_provider_route"
        return default, "task_default"

    def _explicit_model_tier(self, task: dict) -> str | None:
        hints = task.get("runtime_profile_hints")
        candidate = None
        if isinstance(hints, dict):
            candidate = hints.get("model_tier")
        candidate = candidate or task.get("model_tier")
        value = str(candidate or "").strip().lower()
        if value in {"cheap", "medium", "strong"}:
            return value
        return None

    def _needs_stronger_model(self, task: dict, kind: str) -> bool:
        if kind in {"architecture", "review", "decision"}:
            return True
        priority = str(task.get("priority") or "").strip().lower()
        risk = str(task.get("risk") or task.get("risk_level") or "").strip().lower()
        complexity = str(task.get("complexity") or "").strip().lower()
        if priority in {"high", "critical", "p0"}:
            return True
        if risk in {"high", "critical"}:
            return True
        if complexity in {"high", "complex"}:
            return True
        expected = task.get("expected_changed_files") or task.get("expected_artifacts") or []
        return isinstance(expected, list) and len(expected) >= 5

    def _is_low_risk_task(self, task: dict, kind: str) -> bool:
        if kind in {"architecture", "review", "decision"}:
            return False
        if write_scope(task) and kind in {"implementation", "ui"}:
            return False
        priority = str(task.get("priority") or "").strip().lower()
        risk = str(task.get("risk") or task.get("risk_level") or "").strip().lower()
        if priority in {"high", "critical", "p0"} or risk in {"high", "critical"}:
            return False
        return parallel_safety(task) == "readonly" or kind in {"report", "research", "verification"}

    def _capability_adjusted_tier(self, context: RuntimeContext, purpose: str, default: str) -> str:
        return self._capability_adjustment(context, purpose, default)["selected_tier"]

    def _capability_adjustment(self, context: RuntimeContext, purpose: str, default: str) -> dict:
        guidance = CapabilityFeedbackAdvisor(self.validator).route_guidance(context.asteria_dir)
        hints = [
            item
            for item in [
                *list(guidance.get("blocking") or []),
                *list(guidance.get("review") or []),
            ]
            if isinstance(item, dict)
        ]
        if not hints or default == "strong":
            return {
                "selected_tier": default,
                "feedback": self._capability_feedback_summary(guidance, None, "no_escalation"),
            }
        route = self._matching_route_hint(hints, purpose, default)
        if not route:
            return {
                "selected_tier": default,
                "feedback": self._capability_feedback_summary(
                    guidance,
                    None,
                    "no_matching_route_hint",
                ),
            }
        if self._route_hint_is_stale(route, default):
            return {
                "selected_tier": default,
                "feedback": self._capability_feedback_summary(
                    guidance,
                    route,
                    "default_route_fallback_due_stale_capability_profile",
                ),
            }
        action = str(route.get("recommended_action") or "")
        weak_actions = {
            "fallback_or_retry_later",
            "pause_route_until_config_fixed",
            "review_route_before_scaling",
            "review_validation_or_route_before_scaling",
            "review_worker_route_before_scaling",
            "use_json_stricter_or_switch_model",
        }
        if action not in weak_actions:
            return {
                "selected_tier": default,
                "feedback": self._capability_feedback_summary(
                    guidance,
                    route,
                    "matching_hint_did_not_require_escalation",
                ),
            }
        selected = "medium" if default == "cheap" else "strong"
        return {
            "selected_tier": selected,
            "feedback": self._capability_feedback_summary(
                guidance,
                route,
                f"escalated_to_{selected}",
            ),
        }

    def _tier_pressure(self, default: str, strategy_tier: str, selected: str) -> dict:
        order = {"cheap": 0, "medium": 1, "strong": 2}
        default_index = order.get(default, 1)
        selected_index = order.get(selected, default_index)
        if selected_index > default_index:
            direction = "up"
        elif selected_index < default_index:
            direction = "down"
        else:
            direction = "neutral"
        return {
            "default_tier": default,
            "strategy_tier": strategy_tier,
            "selected_tier": selected,
            "direction": direction,
            "delta": selected_index - default_index,
            "uses_stronger_than_default": selected_index > default_index,
            "uses_cheaper_than_default": selected_index < default_index,
        }

    def _capability_feedback_summary(
        self,
        guidance: dict,
        route: dict | None,
        decision: str,
    ) -> dict:
        provider_strategy = guidance.get("provider_route_strategy")
        return {
            "status": guidance.get("status", "healthy"),
            "decision": decision,
            "matched_route": route or None,
            "blocking_count": len(list(guidance.get("blocking") or [])),
            "review_count": len(list(guidance.get("review") or [])),
            "recommended_actions": list(guidance.get("recommended_actions") or [])[:3],
            "provider_route_strategy": provider_strategy if isinstance(provider_strategy, dict) else {},
        }

    def _route_guidance_for_task(self, context: RuntimeContext, purpose: str) -> dict:
        guidance = CapabilityFeedbackAdvisor(self.validator).route_guidance(context.asteria_dir)
        relevant = [
            item
            for item in [
                *list(guidance.get("blocking") or []),
                *list(guidance.get("review") or []),
            ]
            if isinstance(item, dict) and item.get("purpose") == purpose
        ]
        return {
            "status": guidance.get("status", "healthy"),
            "purpose": purpose,
            "relevant": relevant[:3],
            "recommended_actions": list(guidance.get("recommended_actions") or [])[:3],
        }

    def _matching_route_hint(self, routes: list[dict], purpose: str, tier: str) -> dict | None:
        for route in routes:
            if not isinstance(route, dict):
                continue
            if route.get("purpose") == purpose and route.get("model_tier") == tier:
                return route
        return None

    def _route_hint_is_stale(self, route: dict, tier: str) -> bool:
        diagnostic = route_diagnostic_for_tier(tier)
        if diagnostic.source != "default_route_policy":
            return False
        hinted_model = str(route.get("model") or "").strip()
        if not hinted_model or hinted_model == "unknown":
            return True
        return hinted_model != str(diagnostic.model_name or "")

    def _model_purpose(self, task: dict) -> str:
        kind = task_kind(task)
        if kind == "research":
            return "research"
        if kind in {"diagnostic", "verification"}:
            return "debugging"
        if kind in {"report", "decision"}:
            return "summarization"
        if kind == "review":
            return "review"
        return "coding"

    def _default_runtime_profile_id(self, task: dict) -> str:
        role = str(task.get("role") or "CoderAgent").lower().replace("agent", "")
        return f"runtime-profile-execute-{role or 'coder'}"
