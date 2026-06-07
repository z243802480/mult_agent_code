from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from asteria_runtime.core.orchestration_route_recorder import record_orchestration_route
from asteria_runtime.core.orchestration_router import (
    OrchestrationRouteResult,
    resolve_orchestration_model_tier,
    resolve_orchestration_route,
    resolve_orchestration_router_mode,
)
from asteria_runtime.core.policy_config import load_policy_config
from asteria_runtime.models.base import ModelClient
from asteria_runtime.models.factory import create_model_client
from asteria_runtime.storage.run_store import RunStore
from asteria_runtime.storage.schema_validator import SchemaValidator


@dataclass(frozen=True)
class RouteCommandResult:
    route: OrchestrationRouteResult

    def to_dict(self, *, include_catalog: bool = True) -> dict:
        return self.route.to_dict(include_catalog=include_catalog)

    def to_text(self) -> str:
        return (
            f"Route: {self.route.capability_id}\n"
            f"Studio mode: {self.route.studio_mode}\n"
            f"Kind: {self.route.route_kind}\n"
            f"Source: {self.route.source}\n"
            f"Reason: {self.route.reason}"
        )


class RouteCommand:
    def __init__(
        self,
        root: Path,
        message: str,
        *,
        requested_mode: str = "auto",
        permission_level: str = "balanced",
        model_client: ModelClient | None = None,
        use_model: bool = True,
        router_mode_override: str | None = None,
    ) -> None:
        self.root = root.resolve()
        self.message = message
        self.requested_mode = requested_mode
        self.permission_level = permission_level
        self.model_client = model_client
        self.use_model = use_model
        self.router_mode_override = router_mode_override
        self.validator = SchemaValidator(Path(__file__).resolve().parents[3] / "schemas")

    def run(self) -> RouteCommandResult:
        agent_dir = self.root / ".asteria"
        policy = load_policy_config(agent_dir, self.validator) if agent_dir.exists() else {}
        router_mode = resolve_orchestration_router_mode(policy)
        if self.router_mode_override:
            router_mode = self.router_mode_override
        if not self.use_model:
            router_mode = "rules"
        model_tier = resolve_orchestration_model_tier(policy)

        def model_client_factory() -> ModelClient | None:
            if not agent_dir.exists():
                return None
            run_store = RunStore(agent_dir, self.validator)
            run_id = run_store.current_session_id()
            run_dir = run_store.run_dir(run_id) if run_id else None
            return create_model_client(run_dir, self.validator)

        route = resolve_orchestration_route(
            self.root,
            self.message,
            validator=self.validator,
            model_client=self.model_client,
            model_client_factory=model_client_factory if self.model_client is None else None,
            requested_mode=self.requested_mode,
            permission_level=self.permission_level,
            router_mode=router_mode,
        )
        if agent_dir.exists():
            record_orchestration_route(
                agent_dir,
                message=self.message,
                route=route,
                validator=self.validator,
                requested_mode=self.requested_mode,
                router_mode=router_mode,
                model_tier=model_tier,
            )
        return RouteCommandResult(route=route)
