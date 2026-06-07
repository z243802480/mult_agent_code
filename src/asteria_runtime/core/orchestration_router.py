from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json

from asteria_runtime.core.orchestration_spawn_policy import SPAWN_DECISION_POLICY
from asteria_runtime.core.runtime_orchestration_catalog import (
    OrchestrationCapability,
    RuntimeOrchestrationCatalog,
    build_runtime_orchestration_catalog,
    orchestration_catalog_prompt_block,
)
from asteria_runtime.models.base import ChatMessage, ChatRequest, ModelClient
from asteria_runtime.models.json_extractor import JsonExtractionError, parse_json_object
from asteria_runtime.storage.schema_validator import SchemaValidator

MODEL_TIERS = ("strong", "medium", "cheap")
ROUTER_MODES = ("model", "rules")
ORCHESTRATION_ROUTE_TIER = "strong"


class OrchestrationRouterError(RuntimeError):
    pass


@dataclass(frozen=True)
class OrchestrationRouteResult:
    capability_id: str
    studio_mode: str
    route_kind: str
    reason: str
    source: str
    confidence: str = "medium"
    follow_up_notes: str = ""
    catalog: dict[str, Any] | None = None

    def to_dict(self, *, include_catalog: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": "0.1.0",
            "capability_id": self.capability_id,
            "studio_mode": self.studio_mode,
            "route_kind": self.route_kind,
            "reason": self.reason,
            "source": self.source,
            "confidence": self.confidence,
            "follow_up_notes": self.follow_up_notes,
        }
        if include_catalog:
            payload["catalog"] = self.catalog
        return payload


def resolve_orchestration_model_tier(policy: dict[str, Any] | None) -> str:
    """Orchestration routing is a high-stakes decision; always use strong."""
    policy = policy or {}
    studio = policy.get("studio") if isinstance(policy.get("studio"), dict) else {}
    explicit = str(studio.get("orchestration_model_tier") or "").strip().lower()
    if explicit and explicit != ORCHESTRATION_ROUTE_TIER:
        # Policy may list other tiers for legacy configs; orchestration stays strong.
        pass
    return ORCHESTRATION_ROUTE_TIER


def resolve_orchestration_router_mode(policy: dict[str, Any] | None) -> str:
    policy = policy or {}
    studio = policy.get("studio") if isinstance(policy.get("studio"), dict) else {}
    mode = str(studio.get("orchestration_router") or "model").strip().lower()
    if mode == "hybrid":
        return "model"
    return mode if mode in ROUTER_MODES else "model"


def resolve_orchestration_route(
    root: Path,
    message: str,
    *,
    validator: SchemaValidator,
    model_client: ModelClient | None = None,
    model_client_factory: Callable[[], ModelClient | None] | None = None,
    requested_mode: str = "auto",
    permission_level: str = "balanced",
    router_mode: str = "model",
    model_tier: str = ORCHESTRATION_ROUTE_TIER,
) -> OrchestrationRouteResult:
    catalog = build_runtime_orchestration_catalog(root, validator=validator)
    explicit = str(requested_mode or "auto").strip().lower()
    if explicit not in {"", "auto", "run"}:
        return _explicit_mode_route(explicit, catalog, str(message or ""))

    mode = router_mode if router_mode in ROUTER_MODES else "model"
    if mode == "hybrid":
        mode = "model"

    if mode == "rules":
        return _rules_route(message, catalog)

    client = model_client
    if client is None and model_client_factory is not None:
        client = model_client_factory()
    if client is not None:
        try:
            return _model_route(message, catalog, client, validator)
        except OrchestrationRouterError:
            return _rules_route(message, catalog)

    return _rules_route(message, catalog)


def _explicit_mode_route(
    mode: str,
    catalog: RuntimeOrchestrationCatalog,
    message: str,
) -> OrchestrationRouteResult:
    mapping = {
        "chat": "chat_answer",
        "plan": "read_only_plan",
        "run": "cold_goal_execute",
        "resume": "resume_run",
        "review": "review_run",
        "accept": "accept_run",
    }
    capability_id = mapping.get(mode, "chat_answer")
    capability = catalog.get(capability_id)
    if capability is None or not capability.available:
        return _conservative_fallback(catalog)
    return OrchestrationRouteResult(
        capability_id=capability.capability_id,
        studio_mode=capability.studio_mode,
        route_kind=capability.route_kind,
        reason=f"Explicit user mode `{mode}` mapped to {capability.capability_id}.",
        source="explicit",
        confidence="high",
        catalog=catalog.to_dict(),
    )


def _model_route(
    message: str,
    catalog: RuntimeOrchestrationCatalog,
    model_client: ModelClient,
    validator: SchemaValidator,
) -> OrchestrationRouteResult:
    available = catalog.available_capabilities()
    if not available:
        raise OrchestrationRouterError("No orchestration capabilities are available.")

    system_prompt = (
        "You are Asteria's orchestration router (Claude Code-aligned). "
        "Read the runtime capability catalog and the user message. "
        "Choose exactly one capability_id for the user's next step at the Studio boundary. "
        "Prefer the lightest path: chat for Q&A without edits; read_only_plan for analyze-before-edit; "
        "session_continue for follow-ups in an accepted session; cold_goal_execute for new work. "
        "Do not choose spawn_parallel_workers unless it is available and the goal truly requires "
        "multi-worker dispatch—small edits stay on session_agent via cold or continue paths. "
        "When user mentions orchestration_runner_state.jsonl, checkpoint resume, disjoint write fanout continuation, "
        "or resuming an L3 dynamic workflow, choose run_dynamic_orchestration if available—not read_only_plan. "
        "Do not choose run_dynamic_orchestration unless available and the goal requires multi-phase "
        "manifest orchestration (fanout, verifier, merge checkpoint, resume)—not for single scoped edits. "
        "When the user wants readonly exploration with a deliverable artifact in the workspace, prefer "
        "cold_goal_execute over chat_answer; parallel readonly work inside a run is an AgentLoop subagent "
        "decision, not L3 manifest orchestration. "
        "Subagent/worker splits inside a run are AgentLoop decisions, not ingress splits. "
        "Return only JSON matching OrchestrationChoice. "
        "Do not include code, shell commands, or implementation details."
    )
    user_prompt = "\n\n".join(
        [
            orchestration_catalog_prompt_block(catalog),
            "Spawn decision policy (strong model judgment; not keyword heuristics):",
            json.dumps(SPAWN_DECISION_POLICY.to_dict(), ensure_ascii=False, indent=2),
            "User message:",
            str(message or "").strip(),
            "",
            "Return JSON:",
            '{"schema_version":"0.1.0","capability_id":"...","reason":"...","confidence":"high|medium|low","follow_up_notes":""}',
        ]
    )
    response = model_client.chat(
        ChatRequest(
            purpose="orchestration_route",
            model_tier=ORCHESTRATION_ROUTE_TIER,
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            temperature=0.0,
            metadata={
                "purpose": "orchestration_route",
                "model_tier": ORCHESTRATION_ROUTE_TIER,
            },
        )
    )
    try:
        parsed = parse_json_object(response.content)
    except JsonExtractionError as exc:
        raise OrchestrationRouterError(f"Orchestration router returned invalid JSON: {exc}") from exc
    validator.validate("orchestration_choice", parsed)
    capability_id = str(parsed.get("capability_id") or "").strip()
    capability = catalog.get(capability_id)
    if capability is None:
        raise OrchestrationRouterError(f"Unknown capability_id: {capability_id}")
    if not capability.available:
        raise OrchestrationRouterError(
            f"Model selected unavailable capability `{capability_id}`: "
            f"{capability.unavailable_reason or 'blocked'}"
        )
    return OrchestrationRouteResult(
        capability_id=capability.capability_id,
        studio_mode=capability.studio_mode,
        route_kind=capability.route_kind,
        reason=str(parsed.get("reason") or capability.description),
        source="model",
        confidence=str(parsed.get("confidence") or "medium"),
        follow_up_notes=str(parsed.get("follow_up_notes") or ""),
        catalog=catalog.to_dict(),
    )


def _conservative_fallback(catalog: RuntimeOrchestrationCatalog) -> OrchestrationRouteResult:
    """Safe readonly fallback when strong routing is unavailable; not semantic NLU."""
    chat = catalog.get("chat_answer")
    if chat is not None and chat.available:
        return OrchestrationRouteResult(
            capability_id=chat.capability_id,
            studio_mode=chat.studio_mode,
            route_kind=chat.route_kind,
            reason="Strong orchestration router unavailable; defaulting to chat_answer.",
            source="conservative_fallback",
            confidence="low",
            catalog=catalog.to_dict(),
        )
    for capability in catalog.capabilities:
        if capability.available:
            return OrchestrationRouteResult(
                capability_id=capability.capability_id,
                studio_mode=capability.studio_mode,
                route_kind=capability.route_kind,
                reason="Strong orchestration router unavailable; selected first available capability.",
                source="conservative_fallback",
                confidence="low",
                catalog=catalog.to_dict(),
            )
    first = catalog.capabilities[0]
    return OrchestrationRouteResult(
        capability_id=first.capability_id,
        studio_mode=first.studio_mode,
        route_kind=first.route_kind,
        reason="Strong orchestration router unavailable; no available capability matched.",
        source="conservative_fallback",
        confidence="low",
        catalog=catalog.to_dict(),
    )


def _rules_route(message: str, catalog: RuntimeOrchestrationCatalog) -> OrchestrationRouteResult:
    """Maintainer/CI-only keyword router. Not used in production Studio default."""
    capability = _rule_pick(str(message or "").strip().lower(), catalog)
    return OrchestrationRouteResult(
        capability_id=capability.capability_id,
        studio_mode=capability.studio_mode,
        route_kind=capability.route_kind,
        reason=f"Maintainer rules mode selected {capability.capability_id}.",
        source="rules",
        confidence="medium",
        catalog=catalog.to_dict(),
    )


def _rule_pick(text: str, catalog: RuntimeOrchestrationCatalog) -> OrchestrationCapability:
    ordered_ids = [
        "resume_run",
        "session_continue_execute",
        "accept_run",
        "review_run",
        "read_only_plan",
        "cold_goal_execute",
        "chat_answer",
    ]
    if any(token in text for token in ("accept", "接受")):
        preferred = "accept_run"
    elif any(token in text for token in ("review", "评审", "检查")):
        preferred = "review_run"
    elif any(token in text for token in ("resume", "continue", "继续", "恢复", "接着")):
        preferred = "resume_run" if _available(catalog, "resume_run") else "session_continue_execute"
    elif _looks_like_read_only_plan(text):
        preferred = "read_only_plan"
    elif _looks_like_workspace_edit(text):
        preferred = "cold_goal_execute"
    else:
        preferred = "chat_answer"

    capability = catalog.get(preferred)
    if capability is not None and capability.available:
        return capability

    for capability_id in ordered_ids:
        item = catalog.get(capability_id)
        if item is not None and item.available:
            return item
    return catalog.capabilities[0]


def _available(catalog: RuntimeOrchestrationCatalog, capability_id: str) -> bool:
    item = catalog.get(capability_id)
    return bool(item and item.available)


def _looks_like_workspace_edit(text: str) -> bool:
    return any(
        token in text
        for token in (
            "implement",
            "fix",
            "change",
            "modify",
            "edit",
            "add",
            "create",
            "delete",
            "refactor",
            "write",
            "run test",
            "实现",
            "修复",
            "修改",
            "编辑",
            "新增",
            "添加",
            "增加",
            "创建",
            "删除",
            "重构",
            "写入",
            "跑测试",
            "补测试",
            "补一个",
            "执行",
        )
    )


def _looks_like_read_only_plan(text: str) -> bool:
    return any(
        token in text
        for token in (
            "analyze",
            "analysis",
            "read-only",
            "read only",
            "plan first",
            "制定计划",
            "先计划",
            "只读",
            "分析这个项目",
            "分析代码",
            "不要改",
            "别改",
            "先别动手",
            "不要动手",
            "don't change",
            "do not change",
            "without editing",
        )
    )
